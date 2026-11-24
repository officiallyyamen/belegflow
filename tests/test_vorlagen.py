from datetime import date
from decimal import Decimal

import pytest

from app.demo.dateien import Firma, Posten, Vorlage, iban, pdf, uid
from app.demo.vorlagen import BONS, GESTALTUNG
from app.dienste.extraktion import RegelExtraktor, pdf_text

KUNDE = Firma("Muster Holding GmbH", "Beispielgasse 5", "1030", "Wien", uid("2222222"), iban(900))
VON, BIS = date(2026, 11, 1), date(2026, 11, 2)
ARTEN = {
    "GUTSCHRIFT": "gutschrift",
    "ANGEBOT": "angebot",
    "LIEFERSCHEIN": "lieferschein",
    "AUFTRAGSBESTÄTIGUNG": "auftragsbestaetigung",
    "VERTRAG": "vertrag",
}


@pytest.mark.parametrize("name", sorted({*GESTALTUNG, *BONS, "Unbekannt GmbH"}))
@pytest.mark.parametrize("anzahl", [1, 3])
def test_vorlage_wird_vollstaendig_gelesen(name, anzahl):
    firma = Firma(name, "Weg 1", "1010", "Wien", uid("1234567"), iban(77))
    posten = [
        Posten("PM-100", "Kopierpapier A4", Decimal(40), "Stk", Decimal("11.90")),
        Posten("FB-7", "Fachbuch", Decimal(2), "Stk", Decimal("1045.50"), 10),
        Posten("RB-1", "Reinigung", Decimal("1.5"), "Std", Decimal(890)),
    ][:anzahl]
    v = Vorlage(
        firma,
        KUNDE,
        "AB-9",
        date(2026, 11, 3),
        posten,
        leistung=(VON, BIS),
        bestellnummer="BA-9",
    )
    inhalt = pdf(v)
    r = RegelExtraktor().lies(inhalt, "application/pdf", pdf_text(inhalt))
    assert (r.art, r.lieferant, r.lieferant_uid, r.lieferant_adresse) == ("rechnung", name, firma.uid, "Weg 1, 1010 Wien")
    assert (r.empfaenger, r.empfaenger_adresse) == (KUNDE.name, "Beispielgasse 5, 1030 Wien")
    assert (r.nummer, r.bestellnummer, r.iban, r.waehrung) == ("AB-9", "BA-9", firma.iban, "EUR")
    assert (r.datum, r.leistung_von, r.leistung_bis, r.faellig_am) == (
        "2026-11-03",
        "2026-11-01",
        "2026-11-02",
        "2026-12-03",
    )
    assert (Decimal(r.netto), Decimal(r.ust), Decimal(r.brutto)) == (v.netto, v.ust, v.brutto)
    assert {(p.nummer, p.text, Decimal(p.netto)) for p in r.positionen} == {(p.nummer, p.text, p.netto) for p in posten}
    assert len(r.steuerzeilen) == len(v.steuern)


@pytest.mark.parametrize(
    "titel,art",
    [
        ("GUTSCHRIFT", "gutschrift"),
        ("ANGEBOT", "angebot"),
        ("LIEFERSCHEIN", "lieferschein"),
        ("AUFTRAGSBESTÄTIGUNG", "auftragsbestaetigung"),
        ("VERTRAG", "vertrag"),
    ],
)
@pytest.mark.parametrize("name", sorted(GESTALTUNG))
def test_belegart_wird_erkannt(name, titel, art):
    firma = Firma(name, "Weg 1", "1010", "Wien", uid("1234567"), iban(77))
    posten = [] if titel == "VERTRAG" else [Posten("PM-100", "Papier", Decimal(4), "Stk", Decimal("11.90"))]
    v = Vorlage(
        firma,
        KUNDE,
        "AB-9",
        date(2026, 11, 3),
        posten,
        titel=titel,
        ziel=None,
        zeilen=["Mietvertrag über Büroflächen"] if not posten else [],
        ohne_summen=titel == "LIEFERSCHEIN",
    )
    inhalt = pdf(v)
    r = RegelExtraktor().lies(inhalt, "application/pdf", pdf_text(inhalt))
    assert (r.art, r.lieferant, r.nummer) == (art, name, "AB-9")
