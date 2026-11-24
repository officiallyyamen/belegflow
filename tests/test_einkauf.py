from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.demo.dateien import Firma, Posten, pdf, uid
from app.dienste.karten import geld
from app.modelle import Karte

from .conftest import PAPIER, rechnung

TISCH = {"nummer": "T-9", "text": "Schreibtisch", "menge": "6", "einzelpreis": "489"}


def bestelle(haus, wer="dora", erwarte=201, **mehr):
    daten = {
        "lieferant": PAPIER.name,
        "titel": "Tische",
        "positionen": [TISCH],
        "kostenstelle": "200",
        "konto": "7600",
    } | mehr
    return haus.rufe(wer, "POST", "/anforderungen", erwarte=erwarte, json=daten).json()


def freigegeben(haus, **mehr):
    nummer = bestelle(haus, **mehr)["id"]
    haus.fordere(nummer, "ben", wer="dora", art="anforderung")
    haus.entscheide("ben", nummer, art="anforderung")
    return nummer


def lies(haus, nummer, wer="anna"):
    return haus.rufe(wer, "GET", f"/anforderungen/{nummer}", erwarte=200).json()


def test_bestellung_bekommt_nummer_nach_freigabe(haus):
    nummer = bestelle(haus)["id"]
    daten = lies(haus, nummer)
    assert (daten["status"], daten["nummer"], daten["netto"]) == ("neu", None, "2934.00")
    haus.fordere(nummer, "ben", wer="dora", art="anforderung")
    haus.entscheide("ben", nummer, art="anforderung")
    jahr = date.today().year
    assert lies(haus, nummer)["nummer"] == f"BA-{jahr}-0001"
    assert lies(haus, freigegeben(haus))["nummer"] == f"BA-{jahr}-0002"
    assert "freigegeben" in haus.rufe("dora", "GET", "/mitteilungen").json()[0]["text"]


def test_eigene_bestellung_nicht_selbst_freigeben(haus):
    nummer = bestelle(haus, "lea")["id"]
    haus.sofort(nummer, "lea", art="anforderung", erwarte=409)
    haus.sofort(nummer, "chef", art="anforderung")


def test_dreifacher_abgleich(haus):
    nummer = freigegeben(haus)
    bestellnummer = lies(haus, nummer)["nummer"]
    ware = [Posten("T-9", "Schreibtisch", Decimal(5), "Stk", Decimal(499))]
    beleg = haus.kontiert(rechnung("MT-1", posten=ware, bestellnummer=bestellnummer))
    assert haus.beleg(beleg)["verknuepfung_vorschlaege"][0]["art"] == "anforderung"
    haus.rufe("anna", "POST", f"/belege/{beleg}/verknuepfung", erwarte=201, json={"art": "anforderung", "id": nummer})
    zeile = haus.beleg(beleg)["abgleich"][0]
    assert (zeile["menge_ok"], zeile["preis_ok"], zeile["geliefert"]) == (True, False, None)
    eingang = {"datum": date.today().isoformat(), "lieferschein": "LS-1", "mengen": {"0": "4"}}
    haus.rufe("dora", "POST", f"/anforderungen/{nummer}/wareneingang", erwarte=201, json=eingang)
    zeile = haus.beleg(beleg)["abgleich"][0]
    assert (zeile["menge_ok"], zeile["geliefert"], zeile["berechnet"]) == (False, "4", "5")
    assert lies(haus, nummer)["status"] == "teilweise"


def test_status_folgt_den_rechnungen(haus):
    nummer = freigegeben(haus)
    eins = haus.lade(rechnung("MT-1", "1000"))
    zwei = haus.lade(rechnung("MT-2", "1934"))
    for beleg, status in ((eins, "teilweise"), (zwei, "erfuellt")):
        haus.rufe("anna", "POST", f"/belege/{beleg}/verknuepfung", erwarte=201, json={"art": "anforderung", "id": nummer})
        assert lies(haus, nummer)["status"] == status
    haus.rufe("anna", "DELETE", f"/belege/{zwei}/verknuepfung/anforderung/{nummer}", erwarte=200)
    assert lies(haus, nummer)["status"] == "teilweise"
    kacheln = haus.rufe("anna", "GET", "/anforderungen?sicht=alle", erwarte=200).json()["kacheln"]
    assert kacheln["teilweise"] == {"anzahl": 1, "summe": "2934.00"}


def test_nicht_freigegebene_lassen_sich_nicht_verknuepfen(haus):
    nummer = bestelle(haus)["id"]
    beleg = haus.lade(rechnung())
    haus.rufe("anna", "POST", f"/belege/{beleg}/verknuepfung", erwarte=409, json={"art": "anforderung", "id": nummer})
    eingang = {"datum": date.today().isoformat(), "mengen": {"0": "1"}}
    haus.rufe("dora", "POST", f"/anforderungen/{nummer}/wareneingang", erwarte=409, json=eingang)


@pytest.mark.parametrize(
    "werte",
    [
        {"positionen": [], "netto": None},
        {"positionen": [TISCH | {"menge": "0"}]},
        {"positionen": [TISCH | {"menge": "-1"}]},
        {"positionen": [], "netto": "-5"},
        {"lieferant": ""},
    ],
)
def test_ungueltige_bestellungen(haus, werte):
    bestelle(haus, erwarte=422, **werte)


@pytest.mark.parametrize("mengen", [{"9": "1"}, {"x": "1"}, {"0": "0"}, {}])
def test_ungueltiger_wareneingang(haus, mengen):
    nummer = freigegeben(haus)
    eingang = {"datum": date.today().isoformat(), "mengen": mengen}
    haus.rufe("dora", "POST", f"/anforderungen/{nummer}/wareneingang", erwarte=422, json=eingang)


def test_aendern_nur_vor_der_freigabe(haus):
    nummer = bestelle(haus)["id"]
    daten = haus.rufe(
        "dora", "PATCH", f"/anforderungen/{nummer}", erwarte=200, json={"positionen": [TISCH | {"menge": "2"}]}
    )
    assert daten.json()["netto"] == "978.00"
    assert haus.rufe("ben", "PATCH", f"/anforderungen/{nummer}", json={"titel": "X1"}).status_code == 404
    haus.fordere(nummer, "ben", wer="dora", art="anforderung")
    haus.rufe("dora", "PATCH", f"/anforderungen/{nummer}", erwarte=409, json={"titel": "Anders"})


def test_vorschlag_und_pdf(haus):
    haus.partner(konto="7600", kostenstelle="100")
    vorschlag = haus.rufe("dora", "GET", "/anforderungen/vorschlag?lieferant=Papier%20Muster", erwarte=200).json()
    assert (vorschlag["konto"], vorschlag["kostenstelle"]) == ("7600", "100")
    nummer = bestelle(haus, titel="Böse <b>Tische</b> & mehr")["id"]
    assert haus.rufe("dora", "GET", f"/anforderungen/{nummer}/pdf", erwarte=200).content.startswith(b"%PDF")


HOTEL = Firma("Hotel Beispiel GmbH", "Seeweg 5", "5020", "Salzburg", uid("1618033"), None)


def karte(haus, inhaber="dora", letzte4="4242", **mehr):
    daten = {"name": "Reise", "inhaber_id": haus.p[inhaber], "letzte4": letzte4, "limit_monat": "500"} | mehr
    return haus.rufe("anna", "POST", "/karten", erwarte=201, json=daten).json()["id"]


def importiere(haus, *zeilen, erwarte=201, kopf="Karte;Datum;Händler;Betrag;Währung"):
    inhalt = "\r\n".join((kopf, *zeilen)).encode()
    return haus.rufe("anna", "POST", "/transaktionen/import", erwarte=erwarte, files={"datei": ("t.csv", inhalt)}).json()


def test_karte_beantragen_und_freischalten(haus):
    daten = {"name": "Messe", "limit_monat": "300", "grund": "Messe", "konto": "7600"}
    neu = haus.rufe("dora", "POST", "/karten", erwarte=201, json=daten).json()
    assert neu["status"] == "beantragt" and neu["konto"] is None
    haus.rufe("dora", "POST", "/karten", erwarte=403, json=daten | {"inhaber_id": haus.p["ben"]})
    haus.rufe("anna", "PATCH", f"/karten/{neu['id']}", erwarte=409, json={"status": "aktiv"})
    haus.rufe("anna", "PATCH", f"/karten/{neu['id']}", erwarte=200, json={"status": "aktiv", "letzte4": "1111"})
    haus.rufe("dora", "PATCH", f"/karten/{neu['id']}", erwarte=403, json={"limit_monat": "9999"})
    assert haus.rufe("ben", "GET", "/karten").json() == []


def test_import_ordnet_sichere_treffer_zu(haus):
    karte(haus, konto="7200", kostenstelle="200")
    beleg = haus.lade(rechnung("H-1", "200", 10, wer=HOTEL, tage=3), "dora")
    vorher = date.today() - timedelta(days=2)
    zeile = f"**** 4242;{vorher:%d.%m.%Y};HOTEL BEISPIEL SALZBURG;220,00;EUR"
    ergebnis = importiere(haus, zeile, f"**** 4242;{vorher:%d.%m.%Y};TANKSTELLE;60,10;EUR")
    assert (ergebnis["neu"], ergebnis["zugeordnet"]) == (2, 1)
    b = haus.beleg(beleg)
    assert (b["zahlstatus"], b["konto"], b["kostenstelle"]) == ("karte", "7200", "200")
    assert importiere(haus, zeile)["bekannt"] == 1
    offen = haus.rufe("dora", "GET", "/transaktionen?status=fehlt", erwarte=200).json()
    assert [t["haendler"] for t in offen] == ["TANKSTELLE"]
    assert haus.rufe("anna", "GET", "/zahlungen/offen").json() == []


def test_gleiche_zeilen_in_einer_datei_bleiben_getrennt(haus):
    karte(haus)
    zeile = f"4242;{date.today():%d.%m.%Y};PARKEN;4,00;EUR"
    assert importiere(haus, zeile, zeile)["neu"] == 2
    assert importiere(haus, zeile, zeile)["bekannt"] == 2


def test_import_meldet_unbekanntes(haus):
    karte(haus)
    ergebnis = importiere(haus, "9999;01.01.2026;X;1,00;EUR", "4242;gestern;X;1,00;EUR", "4242;01.01.2026;X;viel;EUR")
    assert ergebnis["neu"] == 0 and len(ergebnis["uebersprungen"]) == 3
    importiere(haus, "x", kopf="Spalte", erwarte=422)


def test_beleg_nachreichen_und_loesen(haus):
    karte(haus)
    importiere(haus, f"4242;{date.today():%d.%m.%Y};HOTEL BEISPIEL;220,00;EUR")
    buchung = haus.rufe("dora", "GET", "/transaktionen").json()[0]
    assert haus.rufe("ben", "GET", "/transaktionen").json() == []
    inhalt = pdf(rechnung("H-1", "200", 10, wer=HOTEL))
    antwort = haus.rufe(
        "dora", "POST", f"/transaktionen/{buchung['id']}/datei", erwarte=201, files={"datei": ("h.pdf", inhalt)}
    ).json()
    assert antwort["status"] == "zugeordnet" and antwort["hinweise"] == []
    haus.rufe("dora", "DELETE", f"/transaktionen/{buchung['id']}/beleg", erwarte=403)
    assert haus.rufe("anna", "DELETE", f"/transaktionen/{buchung['id']}/beleg", erwarte=200).json()["status"] == "fehlt"


def test_mitarbeit_darf_nur_eigene_belege_zuordnen(haus):
    karte(haus)
    importiere(haus, f"4242;{date.today():%d.%m.%Y};X;60,00;EUR")
    buchung = haus.rufe("dora", "GET", "/transaktionen").json()[0]["id"]
    fremder = haus.lade(rechnung())
    haus.rufe("dora", "POST", f"/transaktionen/{buchung}/beleg", erwarte=404, json={"beleg_id": fremder})
    haus.rufe("dora", "POST", f"/transaktionen/{buchung}/ohne-beleg", erwarte=200, json={"grund": "Beleg verloren"})
    haus.rufe("dora", "POST", f"/transaktionen/{buchung}/ohne-beleg", erwarte=409, json={"grund": "noch einmal"})


def test_limits_werden_gemeldet(haus):
    karte(haus, limit_zahlung="100")
    heute = f"{date.today():%d.%m.%Y}"
    importiere(haus, f"4242;{heute};A;450,00;EUR", f"4242;{heute};B;60,00;EUR")
    hinweise = {t["haendler"]: t["hinweise"] for t in haus.rufe("anna", "GET", "/transaktionen").json()}
    assert hinweise["A"] == ["Über dem Limit pro Zahlung", "Monatslimit überschritten"]
    assert hinweise["B"] == ["Monatslimit überschritten"]
    eintrag = haus.rufe("anna", "GET", "/karten").json()[0]
    assert (eintrag["ausgegeben"], eintrag["fehlende_belege"]) == ("510.00", 2)


@pytest.mark.parametrize(
    ("text", "wert"), [("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("-5,00", "-5.00"), ("x", None)]
)
def test_geldformate(text, wert):
    assert geld(text) == (Decimal(wert) if wert else None)


def test_fremde_karten_bleiben_verborgen(haus):
    nummer = karte(haus, "ben", "7777")
    assert haus.rufe("dora", "GET", f"/karten/{nummer}").status_code == 404
    with haus.db() as db:
        assert db.get(Karte, nummer).status == "aktiv"
