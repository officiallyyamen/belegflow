import json

import anthropic
import httpx2
import pytest

from app.extraktion import ClaudeExtraktor, ExtraktionsFehler, RegelExtraktor, als_betrag, als_datum, felder
from app.pruefung import iban_gueltig, uid_gueltig
from app.schemas import Rechnung

ANTWORT = {
    "lieferant": "Papier Muster GmbH",
    "lieferant_uid": "ATU 1234 5675",
    "empfaenger": "Musterverwaltung GmbH",
    "rechnungsnummer": "PM-1",
    "rechnungsdatum": "2026-11-14",
    "faellig_am": None,
    "iban": "AT61 1904 3002 3457 3201",
    "waehrung": "EUR",
    "steuerzeilen": [{"satz": "20", "netto": "500.00", "ust": "100.00"}],
    "netto": "500.00",
    "ust": "100.00",
    "brutto": "600.00",
}


def claude(status=200, text=None, ende="end_turn", anfragen=None):
    def antworte(anfrage):
        if anfragen is not None:
            anfragen.append(json.loads(anfrage.content))
        if status != 200:
            fehler = {"type": "error", "error": {"type": "api_error", "message": "Fehler"}}
            return httpx2.Response(status, json=fehler)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": text or json.dumps(ANTWORT)}],
                "stop_reason": ende,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    verbindung = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(antworte))
    return ClaudeExtraktor(anthropic.Anthropic(api_key="test", http_client=verbindung, max_retries=0))


def test_claude_liest_rechnung():
    anfragen = []
    rechnung = claude(anfragen=anfragen).lies(b"%PDF-1.4", "application/pdf")
    werte = felder(rechnung)
    assert werte["lieferant_uid"] == "ATU12345675"
    assert werte["iban"] == "AT611904300234573201"
    anfrage = anfragen[0]
    assert anfrage["messages"][0]["content"][0]["type"] == "document"
    assert anfrage["output_config"]["effort"] == "low"
    assert anfrage["output_config"]["format"]["type"] == "json_schema"


def test_claude_liest_bilder():
    anfragen = []
    claude(anfragen=anfragen).lies(b"\x89PNG", "image/png")
    assert anfragen[0]["messages"][0]["content"][0]["type"] == "image"


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_api_fehler_werden_abgefangen(status):
    with pytest.raises(ExtraktionsFehler):
        claude(status=status).lies(b"%PDF-1.4", "application/pdf")


def test_unvollstaendige_antwort():
    with pytest.raises(ExtraktionsFehler):
        claude(ende="max_tokens").lies(b"%PDF-1.4", "application/pdf")


def test_unbrauchbare_antwort():
    with pytest.raises(ExtraktionsFehler):
        claude(text="kein JSON").lies(b"%PDF-1.4", "application/pdf")


def test_regeln_lesen_keine_bilder():
    with pytest.raises(ExtraktionsFehler):
        RegelExtraktor().lies(b"\x89PNG", "image/png")


def test_unsinnige_werte_werden_verworfen():
    assert als_betrag("abc") is None
    assert als_betrag("NaN") is None
    assert als_betrag("999999999999") is None
    assert als_datum("31.12.2026") is None
    rechnung = Rechnung(**(ANTWORT | {"brutto": "viel", "waehrung": "Euro und mehr"}))
    assert felder(rechnung)["brutto"] is None


@pytest.mark.parametrize("uid, gueltig", [("ATU12345675", True), ("ATU12345678", False), ("ATU1234567", False)])
def test_uid(uid, gueltig):
    assert uid_gueltig(uid) is gueltig


@pytest.mark.parametrize(
    "iban, gueltig",
    [("AT611904300234573201", True), ("AT611904300234573202", False), ("AT6119043002345732", False), ("X", False)],
)
def test_iban(iban, gueltig):
    assert iban_gueltig(iban) is gueltig
