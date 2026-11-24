import json
from decimal import Decimal

import anthropic
import httpx2
import pytest

from app.demo.dateien import iban, pdf, uid
from app.dienste.extraktion import (
    ExtraktionsFehler,
    ModellExtraktor,
    RechnungAntwort,
    RegelExtraktor,
    art_aus_text,
    pdf_text,
)
from app.dienste.pruefung import iban_gueltig, uid_gueltig
from app.dienste.werte import Rechnung, als_betrag, als_datum, felder

from .conftest import rechnung

ANTWORT = {name: "" for name in RechnungAntwort.model_fields} | {
    "art": "rechnung",
    "lieferant": "Papier Muster GmbH",
    "lieferant_uid": "ATU 1234 5675",
    "nummer": "PM-1",
    "datum": "2026-11-14",
    "iban": "AT61 1904 3002 3457 3201",
    "waehrung": "EUR",
    "netto": "500.00",
    "ust": "100.00",
    "brutto": "600.00",
    "steuerzeilen": [{"satz": "20", "netto": "500.00", "ust": "100.00"}],
    "positionen": [
        {
            "nummer": "",
            "text": "Papier",
            "menge": "40",
            "einheit": "Stk",
            "einzelpreis": "12.5",
            "netto": "500.00",
            "satz": "20",
        }
    ],
}


def modell(status=200, text=None, ende="end_turn", anfragen=None):
    def antworte(anfrage):
        if anfragen is not None:
            anfragen.append(json.loads(anfrage.content))
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "Fehler"}})
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "test",
                "content": [{"type": "text", "text": text or json.dumps(ANTWORT)}],
                "stop_reason": ende,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    verbindung = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(antworte))
    return ModellExtraktor(anthropic.Anthropic(api_key="test", http_client=verbindung, max_retries=0))


def test_modell_liest_dokumente():
    anfragen = []
    werte = felder(modell(anfragen=anfragen).lies(b"%PDF-1.4", "application/pdf", ""))
    assert (werte["lieferant_uid"], werte["iban"]) == ("ATU12345675", "AT611904300234573201")
    assert werte["empfaenger"] is None and werte["positionen"][0]["menge"] == "40"
    anfrage = anfragen[0]
    assert anfrage["messages"][0]["content"][0]["type"] == "document"
    assert anfrage["output_config"]["effort"] == "low"
    schema = anfrage["output_config"]["format"]["schema"]
    assert set(schema["required"]) == set(schema["properties"]) and "anyOf" not in json.dumps(schema)


def test_modell_liest_bilder():
    anfragen = []
    modell(anfragen=anfragen).lies(b"\x89PNG", "image/png", "")
    assert anfragen[0]["messages"][0]["content"][0]["type"] == "image"


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_api_fehler_werden_abgefangen(status):
    with pytest.raises(ExtraktionsFehler):
        modell(status=status).lies(b"%PDF-1.4", "application/pdf", "")


@pytest.mark.parametrize(
    ("ende", "text"), [("max_tokens", None), ("refusal", None), ("end_turn", "kein json"), ("end_turn", "{}")]
)
def test_unbrauchbare_antworten(ende, text):
    with pytest.raises(ExtraktionsFehler):
        modell(ende=ende, text=text).lies(b"%PDF-1.4", "application/pdf", "")


def test_ausfall_der_ki_verhindert_den_eingang_nicht(haus, monkeypatch):
    monkeypatch.setattr("app.dienste.belege.extraktor", lambda: modell(status=500))
    b = haus.beleg(haus.lade(rechnung()))
    assert b["status"] == "neu" and b["stufe"] == "sperre"
    assert b["pruefbericht"][0]["code"] == "extraktion"


def test_ki_ergebnis_wird_geprueft(haus, monkeypatch):
    falsch = json.dumps(ANTWORT | {"brutto": "9999.00"})
    monkeypatch.setattr("app.dienste.belege.extraktor", lambda: modell(text=falsch))
    b = haus.beleg(haus.lade(rechnung()))
    assert b["stufe"] == "sperre" and b["erkannt"]["brutto"] == "Sprachmodell"


def test_regeln_lesen_text():
    inhalt = pdf(rechnung(skonto=(3, 14), bestellnummer="B-1", mit_uid=True))
    werte = felder(RegelExtraktor().lies(inhalt, "application/pdf", pdf_text(inhalt)))
    assert werte["empfaenger_adresse"] == "Beispielgasse 5, 1030 Wien"
    assert werte["brutto"] == Decimal("600.00") and werte["positionen"][0]["menge"] == "1"
    assert (werte["skonto_bis"] - werte["datum"]).days == 14


def test_regeln_lesen_keine_bilder():
    with pytest.raises(ExtraktionsFehler):
        RegelExtraktor().lies(b"", "image/png", "")
    with pytest.raises(ExtraktionsFehler):
        RegelExtraktor().lies(b"", "application/pdf", " ")
    with pytest.raises(ExtraktionsFehler):
        pdf_text(b"%PDF-kaputt")


@pytest.mark.parametrize(
    ("text", "art"),
    [
        ("Firma\nRECHNUNG\nAngebot 5", "rechnung"),
        ("Firma\nRechnung an: X\nGUTSCHRIFT", "gutschrift"),
        ("Firma\nMietvertrag\nMiete", "vertrag"),
        ("Firma\nLieferschein Nr. 5", "lieferschein"),
        ("Firma\nGuten Tag", "sonstiges"),
    ],
)
def test_belegart(text, art):
    assert art_aus_text(text) == art


@pytest.mark.parametrize(
    ("nummer", "gut"),
    [(uid("1234567"), True), ("ATU12345670", False), ("ATU1234567", False), ("DE123456789", True), ("X", False)],
)
def test_uid(nummer, gut):
    assert uid_gueltig(nummer) is gut


@pytest.mark.parametrize(
    ("nummer", "gut"),
    [
        ("AT611904300234573201", True),
        (iban(5), True),
        ("AT611904300234573202", False),
        ("DE89370400440532013000", True),
        ("AT61", False),
    ],
)
def test_iban(nummer, gut):
    assert iban_gueltig(nummer) is gut


@pytest.mark.parametrize("wert", ["NaN", "Infinity", "1e30", "abc", "", None])
def test_unsinnige_betraege(wert):
    assert als_betrag(wert) is None


def test_werte_werden_begrenzt():
    werte = felder(Rechnung(lieferant="x" * 900, waehrung="Euro", skonto_prozent="500", datum="irgendwann"))
    assert len(werte["lieferant"]) == 255 and werte["waehrung"] == "EUR"
    assert werte["skonto_prozent"] is None and werte["datum"] is None


@pytest.mark.parametrize(
    ("text", "iso"), [("2026-11-14", "2026-11-14"), ("14.11.2026", "2026-11-14"), ("20261114", "2026-11-14")]
)
def test_datum(text, iso):
    assert als_datum(text).isoformat() == iso
