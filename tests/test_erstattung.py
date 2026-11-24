import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.demo.dateien import Firma, pdf, uid
from app.dienste import reisekosten, waehrung
from app.dienste.fehler import Ungueltig
from app.modelle import Benutzer, Kurs

from .conftest import rechnung

AT, DE = "Österreich", "Deutschland"
LOKAL = Firma("Gasthaus Muster", "Platz 1", "1080", "Wien", uid("2718281"), None)


@pytest.mark.parametrize(
    ("ende", "betrag"),
    [
        ("2026-03-02T11:00", "0"),
        ("2026-03-02T11:01", "10.00"),
        ("2026-03-02T13:30", "15.00"),
        ("2026-03-02T19:00", "27.50"),
        ("2026-03-02T19:01", "30.00"),
        ("2026-03-03T08:00", "30.00"),
        ("2026-03-03T09:00", "32.50"),
        ("2026-03-04T08:00", "60.00"),
    ],
)
def test_taggeld_inland(ende, betrag):
    assert reisekosten.taggeld([{"land": AT, "von": "2026-03-02T08:00"}], ende)[0] == Decimal(betrag)


@pytest.mark.parametrize(
    ("mahlzeiten", "betrag"),
    [([], "30.00"), (["fruehstueck"], "30.00"), (["mittag"], "15.00"), (["mittag", "abend"], "0.00")],
)
def test_gestellte_mahlzeiten_inland(mahlzeiten, betrag):
    summe, _ = reisekosten.taggeld([{"land": AT, "von": "2026-03-02T06:00"}], "2026-03-02T20:00", {"2026-03-02": mahlzeiten})
    assert summe == Decimal(betrag)


def test_kurze_reise_mit_mahlzeit_wird_nicht_negativ():
    summe, _ = reisekosten.taggeld([{"land": AT, "von": "2026-03-02T08:00"}], "2026-03-02T12:00", {"2026-03-02": ["mittag"]})
    assert summe == 0


def test_ausland_mit_grenzuebertritt():
    etappen = [
        {"land": AT, "von": "2026-03-02T06:00"},
        {"land": DE, "von": "2026-03-02T09:00"},
        {"land": AT, "von": "2026-03-02T17:00"},
    ]
    summe, zeilen = reisekosten.taggeld(etappen, "2026-03-02T20:00")
    satz = Decimal(reisekosten.saetze()["ausland"][DE]["tag"])
    assert summe == reisekosten.runden(satz * 8 / 12 + Decimal(30) * 4 / 12)
    assert zeilen[0]["land"] == f"{DE}, {AT}"


def test_kurzer_grenzuebertritt_zaehlt_als_inland():
    etappen = [
        {"land": AT, "von": "2026-03-02T06:00"},
        {"land": DE, "von": "2026-03-02T09:00"},
        {"land": AT, "von": "2026-03-02T12:00"},
    ]
    assert reisekosten.taggeld(etappen, "2026-03-02T20:00")[0] == Decimal("30.00")


def test_ausland_zwei_mahlzeiten_lassen_ein_drittel():
    summe, _ = reisekosten.taggeld(
        [{"land": DE, "von": "2026-03-02T06:00"}], "2026-03-02T20:00", {"2026-03-02": ["mittag", "abend"]}
    )
    assert summe == reisekosten.runden(Decimal(reisekosten.saetze()["ausland"][DE]["tag"]) / 3)


@pytest.mark.parametrize(
    ("etappen", "ende"),
    [
        ([], "2026-03-02T20:00"),
        ([{"land": "Atlantis", "von": "2026-03-02T06:00"}], "2026-03-02T20:00"),
        ([{"land": AT, "von": "2026-03-02T06:00"}], "2026-03-01T20:00"),
        ([{"land": AT, "von": "gestern"}], "2026-03-01T20:00"),
        ([{"land": AT, "von": "2026-01-01T06:00"}], "2026-12-01T20:00"),
    ],
)
def test_unmoegliche_reisen(etappen, ende):
    with pytest.raises(Ungueltig):
        reisekosten.taggeld(etappen, ende)


def test_naechte_und_kilometer():
    etappen = [{"land": AT, "von": "2026-03-02T06:00"}]
    assert reisekosten.naechtigung([{"land": AT, "anzahl": 2}], etappen, "2026-03-04T10:00") == Decimal("34.00")
    with pytest.raises(Ungueltig):
        reisekosten.naechtigung([{"land": AT, "anzahl": 3}], etappen, "2026-03-04T10:00")
    assert reisekosten.kilometer(Decimal(100), "pkw") == Decimal("50.00")
    assert reisekosten.kilometer(Decimal(100), "pkw", 2) == Decimal("80.00")
    assert reisekosten.kilometer(Decimal(10), "fahrrad", 2) == Decimal("2.50")
    for strecke, fahrzeug in ((Decimal(0), "pkw"), (Decimal(6000), "pkw"), (Decimal(10), "rakete")):
        with pytest.raises(Ungueltig):
            reisekosten.kilometer(strecke, fahrzeug)


def antrag(haus, wer="dora"):
    return haus.rufe(wer, "POST", "/erstattungen", erwarte=201, json={"titel": "Reise"}).json()["id"]


def posten(haus, nummer, art="auslage", wer="dora", erwarte=201, datei=None, titel="", datum=None, **angaben):
    daten = {"art": art, "titel": titel, "angaben": json.dumps(angaben)}
    if datum:
        daten["datum"] = datum.isoformat()
    dateien = {"datei": datei} if datei else None
    return haus.rufe(wer, "POST", f"/erstattungen/{nummer}/posten", erwarte=erwarte, data=daten, files=dateien).json()


def vollstaendig(haus, wer="dora"):
    nummer = antrag(haus, wer)
    beleg = ("essen.pdf", pdf(rechnung("R-1", "50", wer=LOKAL)))
    posten(haus, nummer, datei=beleg, wer=wer, grund="Kundentermin")
    return nummer


def test_beleg_wird_gelesen(haus):
    nummer = vollstaendig(haus)
    daten = haus.rufe("dora", "GET", f"/erstattungen/{nummer}", erwarte=200).json()
    eintrag = daten["eintraege"][0]
    assert (eintrag["titel"], eintrag["betrag"], eintrag["ust"]) == (LOKAL.name, "60.00", "10.00")
    assert eintrag["daten"]["erkannt"] and daten["maengel"] == [] and daten["summe"] == "60.00"
    bild = haus.rufe("dora", "GET", f"/erstattungen/{nummer}/posten/{eintrag['id']}/bild", erwarte=200)
    assert bild.headers["content-type"] == "image/png"


def test_ablauf_bis_zur_zahlung(haus):
    nummer = vollstaendig(haus)
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)
    assert "eingereicht" in haus.rufe("anna", "GET", "/mitteilungen").json()[0]["text"]
    haus.rufe("dora", "PATCH", f"/erstattungen/{nummer}", erwarte=409, json={"titel": "Anders"})
    haus.rufe("anna", "POST", f"/erstattungen/{nummer}/zurueckgeben", erwarte=200, json={"grund": "Anlass genauer"})
    haus.rufe("dora", "PATCH", f"/erstattungen/{nummer}", erwarte=200, json={"titel": "Reise nach Linz"})
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)
    haus.rufe("anna", "PATCH", f"/erstattungen/{nummer}", erwarte=200, json={"konto": "7600", "kostenstelle": "100"})
    haus.fordere(nummer, "ben", art="erstattung")
    haus.entscheide("ben", nummer, art="erstattung")
    offen = haus.rufe("anna", "GET", "/zahlungen/offen", erwarte=200).json()
    assert offen[0]["betrag"] == "60.00" and offen[0]["name"] == "Dora"
    wartet = haus.rufe("anna", "GET", "/exporte/wartend", erwarte=200).json()
    assert wartet[0]["kreditor"] == "3600" and wartet[0]["hindernis"] is None
    haus.rufe("anna", "POST", "/exporte", erwarte=201, json={"format": "zip"})
    lauf = {"posten": [{"art": "erstattung", "id": nummer}], "ausfuehrung": date.today().isoformat()}
    haus.rufe("anna", "POST", "/zahlungen", erwarte=201, json=lauf)
    pdf_datei = haus.rufe("dora", "GET", f"/erstattungen/{nummer}/pdf", erwarte=200)
    assert pdf_datei.content.startswith(b"%PDF")


def test_eigene_erstattung_darf_man_nicht_freigeben(haus):
    nummer = vollstaendig(haus, "lea")
    haus.rufe("lea", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)
    haus.sofort(nummer, "lea", art="erstattung", erwarte=409)
    haus.sofort(nummer, "chef", art="erstattung")


def test_posten_ausschliessen(haus):
    nummer = vollstaendig(haus)
    posten(haus, nummer, titel="Minibar", datum=date.today(), betrag="9.90", grund="privat", eigenbeleg="kein Beleg")
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)
    daten = haus.rufe("anna", "GET", f"/erstattungen/{nummer}").json()
    zweiter = daten["eintraege"][1]["id"]
    haus.rufe("dora", "PATCH", f"/erstattungen/{nummer}/posten/{zweiter}", erwarte=403, json={"ausgeschlossen": True})
    daten = haus.rufe(
        "anna", "PATCH", f"/erstattungen/{nummer}/posten/{zweiter}", erwarte=200, json={"ausgeschlossen": True}
    ).json()
    assert daten["summe"] == "60.00"


def test_unvollstaendiges_laesst_sich_nicht_einreichen(haus):
    nummer = antrag(haus)
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=409)
    posten(haus, nummer, "bewirtung", titel="Essen", datum=date.today(), betrag="80", trinkgeld="5")
    maengel = haus.rufe("dora", "GET", f"/erstattungen/{nummer}").json()["maengel"]
    assert len(maengel) == 3
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=409)


def test_kilometer_und_taggeld_ueber_die_api(haus):
    nummer = antrag(haus)
    daten = posten(haus, nummer, "kilometer", datum=date.today(), start="Wien", ziel="Linz", km="184,5", hin_zurueck=True)
    assert daten["eintraege"][0]["titel"] == "Wien - Linz" and daten["eintraege"][0]["betrag"] == "184.50"
    reise = {"etappen": [{"land": AT, "von": "2026-03-02T06:00"}], "ende": "2026-03-03T18:00"}
    daten = posten(haus, nummer, "taggeld", **reise, naechte=[{"land": AT, "anzahl": 1}])
    assert daten["eintraege"][1]["betrag"] == "77.00"
    probe = {"art": "taggeld", "daten": reise}
    assert haus.rufe("dora", "POST", "/erstattungen/rechnen", erwarte=200, json=probe).json()["betrag"] == "60.00"


def test_grenze_fuer_kilometergeld(haus):
    nummer = antrag(haus)
    for _ in range(4):
        posten(haus, nummer, "kilometer", datum=date.today(), km="800", fahrzeug="fahrrad", titel="Rad")
    daten = haus.rufe("dora", "GET", f"/erstattungen/{nummer}").json()
    assert "3000 km" in daten["warnungen"][0]


def test_fremdwaehrung(haus):
    nummer = antrag(haus)
    werte = {"titel": "Hotel", "datum": date(2026, 3, 2), "betrag": "109.50", "waehrung": "CHF", "grund": "Messe"}
    posten(haus, nummer, erwarte=422, **werte)
    with haus.db() as db:
        db.add(Kurs(waehrung="CHF", datum=date(2026, 2, 27), kurs="0.9450"))
        db.commit()
    daten = posten(haus, nummer, **werte)
    assert daten["eintraege"][0]["betrag"] == "115.87"
    daten = posten(haus, nummer, **werte, kurs="1,095")
    assert daten["eintraege"][1]["betrag"] == "100.00"


def test_ezb_kurse_werden_gelesen(haus):
    xml = (
        b'<?xml version="1.0"?><g:Envelope xmlns:g="urn:g" xmlns="urn:e"><Cube><Cube time="2026-03-02">'
        b'<Cube currency="USD" rate="1.0800"/></Cube></Cube></g:Envelope>'
    )
    with haus.db() as db:
        waehrung.uebernimm(db, xml)
        assert waehrung.kurs(db, "USD", date(2026, 3, 4)) == Decimal("1.0800")
        assert waehrung.kurs(db, "EUR", date(2026, 3, 4)) == 1
        with pytest.raises(Ungueltig):
            waehrung.kurs(db, "USD", date(2026, 4, 1))


def test_sichtbarkeit(haus):
    nummer = vollstaendig(haus)
    for wer in ("ben", "anna", "eva", "admin"):
        assert haus.rufe(wer, "GET", f"/erstattungen/{nummer}").status_code == 404
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)
    assert haus.rufe("anna", "GET", f"/erstattungen/{nummer}").status_code == 200
    assert haus.rufe("ben", "GET", f"/erstattungen/{nummer}").status_code == 404
    assert haus.rufe("dora", "GET", "/erstattungen?sicht=alle").status_code == 403
    assert len(haus.rufe("anna", "GET", "/erstattungen?sicht=pruefen").json()) == 1


@pytest.mark.parametrize(
    "angaben",
    [{"betrag": "-5"}, {"betrag": "1e9"}, {"unbekannt": "x"}, {"waehrung": "Euro"}, {"km": "viele"}, {"grund": "a\x00b"}],
)
def test_ungueltige_angaben(haus, angaben):
    posten(haus, antrag(haus), titel="X", datum=date.today(), erwarte=422, **angaben)


def test_verwerfen(haus):
    nummer = vollstaendig(haus)
    haus.rufe("anna", "DELETE", f"/erstattungen/{nummer}", erwarte=404)
    haus.rufe("dora", "DELETE", f"/erstattungen/{nummer}", erwarte=204)
    assert haus.rufe("dora", "GET", "/erstattungen").json() == []


def test_iban_kommt_aus_dem_profil(haus):
    with haus.db() as db:
        db.get(Benutzer, haus.p["dora"]).iban = None
        db.commit()
    nummer = vollstaendig(haus)
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=409)
    haus.rufe("dora", "PATCH", f"/erstattungen/{nummer}", erwarte=422, json={"iban": "AT00"})
    haus.rufe("dora", "PATCH", f"/erstattungen/{nummer}", erwarte=200, json={"iban": "AT61 1904 3002 3457 3201"})
    haus.rufe("dora", "POST", f"/erstattungen/{nummer}/einreichen", erwarte=200)


def test_zukuenftige_kurse_sind_kein_absturz(haus):
    morgen = date.today() + timedelta(days=1)
    posten(haus, antrag(haus), titel="X", datum=morgen, betrag="1", waehrung="USD", erwarte=422)
