from decimal import Decimal

import pytest

from app.demo.dateien import Posten, cii, ebinterface, iban, pdf, ubl, zugferd
from app.dienste.erechnung import aus_pdf, lies
from app.dienste.werte import felder

from .conftest import PAPIER, rechnung

POSTEN = [
    Posten("A-1", "Kopierpapier & Ordner", Decimal(40), "Stk", Decimal("12.00")),
    Posten("B-2", "Fachbuch", Decimal(2), "Stk", Decimal("45.50"), 10),
]
FORMATE = [(ubl, "XRechnung"), (cii, "ZUGFeRD"), (ebinterface, "ebInterface 6.1")]


def vorlage():
    return rechnung("E-1", posten=POSTEN, mit_uid=True)


@pytest.mark.parametrize(("baue", "name"), FORMATE)
def test_alle_formate_liefern_dieselben_werte(baue, name):
    v = vorlage()
    gelesen, art = lies(baue(v))
    w = felder(gelesen)
    assert art == name
    assert (w["lieferant"], w["lieferant_uid"], w["iban"]) == (PAPIER.name, PAPIER.uid, PAPIER.iban)
    assert (w["empfaenger"], w["empfaenger_uid"]) == (v.empfaenger.name, v.empfaenger.uid)
    assert w["empfaenger_adresse"] == "Beispielgasse 5, 1030 Wien"
    assert (w["nummer"], w["datum"], w["faellig_am"]) == ("E-1", v.datum, v.faellig)
    assert (w["leistung_von"], w["leistung_bis"]) == v.leistung
    assert (w["netto"], w["ust"], w["brutto"]) == (Decimal("571.00"), Decimal("105.10"), Decimal("676.10"))
    assert w["steuerzeilen"] == [
        {"satz": "20", "netto": "480.00", "ust": "96.00"},
        {"satz": "10", "netto": "91.00", "ust": "9.10"},
    ]
    assert [(p["nummer"], p["menge"], p["einheit"], p["einzelpreis"]) for p in w["positionen"]] == [
        ("A-1", "40", "Stk", "12"),
        ("B-2", "2", "Stk", "45.5"),
    ]
    assert w["positionen"][0]["text"] == "Kopierpapier & Ordner"


@pytest.mark.parametrize("baue", [ubl, ebinterface])
def test_bestellnummer_und_skonto(baue):
    w = felder(lies(baue(rechnung("E-2", bestellnummer="BA-9", skonto=(2, 10))))[0])
    assert w["bestellnummer"] == "BA-9" and w["skonto_prozent"] == "2"
    assert (w["skonto_bis"] - w["datum"]).days == 10


@pytest.mark.parametrize(("baue", "name"), FORMATE)
def test_hochladen_ohne_ki(haus, baue, name):
    b = haus.beleg(haus.lade(baue(vorlage()), name="rechnung.xml"))
    assert (b["e_rechnung"], b["stufe"], b["brutto"]) == (name, "ok", "676.10")
    assert b["erkannt"]["brutto"] == "E-Rechnung"
    assert haus.rufe("anna", "GET", f"/belege/{b['id']}/bild").status_code == 415
    datei = haus.rufe("anna", "GET", f"/belege/{b['id']}/datei", erwarte=200)
    assert datei.headers["content-disposition"].startswith("attachment")


def test_zugferd_pdf_nimmt_die_xml_daten(haus):
    inhalt = zugferd(vorlage())
    assert aus_pdf(inhalt) and aus_pdf(pdf(vorlage())) is None
    b = haus.beleg(haus.lade(inhalt))
    assert (b["e_rechnung"], b["dateityp"], b["brutto"]) == ("ZUGFeRD", "application/pdf", "676.10")
    assert haus.rufe("anna", "GET", "/eingang?merkmal=e_rechnung").json()["gesamt"] == 1


def test_gutschrift_als_xml():
    xml = ubl(vorlage()).replace(b"InvoiceTypeCode>380", b"InvoiceTypeCode>381")
    assert lies(xml)[0].art == "gutschrift"


def test_abweichung_zwischen_pdf_und_xml_gewinnt_xml(haus):
    v = vorlage()
    v.lieferant.iban, alt = iban(77), v.lieferant.iban
    try:
        b = haus.beleg(haus.lade(zugferd(v)))
        assert b["iban"] == iban(77)
    finally:
        v.lieferant.iban = alt


@pytest.mark.parametrize(
    "xml",
    [
        b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a SYSTEM 'file:///etc/passwd'>]><Invoice>&a;</Invoice>",
        b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]><Invoice>&a;</Invoice>",
        b"<Invoice xmlns='urn:irgendwas'/>",
        b"<kaputt",
    ],
)
def test_gefaehrliches_und_fremdes_xml(haus, xml):
    assert lies(xml) is None
    antwort = haus.rufe("anna", "POST", "/belege", erwarte=201, files=[("dateien", ("x.xml", xml))]).json()[0]
    assert antwort["fehler"] == "XML ist keine bekannte E-Rechnung"
