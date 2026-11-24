import csv
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from app.demo.dateien import Posten
from app.dienste.export import BMD_SPALTEN, monatsende

from .conftest import PAPIER, PUTZ, rechnung


def exportiere(haus, art="csv", erwarte=201, **mehr):
    return haus.rufe("anna", "POST", "/exporte", erwarte=erwarte, json={"format": art} | mehr).json()


def inhalt(haus, eintrag):
    return haus.rufe("anna", "GET", f"/exporte/{eintrag['id']}/datei", erwarte=200).content


def zeilen(roh, kodierung="utf-8-sig"):
    return list(csv.DictReader(io.StringIO(roh.decode(kodierung), newline=""), delimiter=";"))


def zahl(text):
    return Decimal(text.replace(",", ".")) if text else Decimal(0)


def test_csv(haus):
    posten = [
        Posten("A", "Ware", Decimal(1), "Stk", Decimal(100)),
        Posten("B", "Buch", Decimal(1), "Stk", Decimal(50), 10),
    ]
    nummer = haus.frei(rechnung(posten=posten))
    eintrag = exportiere(haus)
    gelesen = zeilen(inhalt(haus, eintrag))
    assert [(z["Steuersatz"], z["Netto"], z["USt"]) for z in gelesen] == [("20", "100,00", "20,00"), ("10", "50,00", "5,00")]
    assert {z["Konto"] for z in gelesen} == {"7600"} and gelesen[0]["Beleg"] == str(nummer)
    assert haus.beleg(nummer)["status"] == "exportiert"
    exportiere(haus, erwarte=409)


def test_formeln_werden_entschaerft(haus):
    nummer = haus.kontiert(rechnung())
    haus.aendere(nummer, lieferant="=HYPERLINK(1)", nummer="+1", buchungstext="@x")
    haus.sofort(nummer)
    gelesen = zeilen(inhalt(haus, exportiere(haus)))[0]
    assert gelesen["Lieferant"].startswith("'=") and gelesen["Rechnungsnummer"].startswith("'+")
    assert gelesen["Buchungstext"] == "'@x"


def test_bmd_ist_ausgeglichen(haus):
    haus.frei(rechnung("PM-1", skonto=(2, 14)))
    haus.frei(rechnung("RB-1", "90", wer=PUTZ))
    gelesen = zeilen(inhalt(haus, exportiere(haus, "bmd")), "cp1252")
    assert tuple(gelesen[0]) == BMD_SPALTEN
    for beleg in {z["belegnr"] for z in gelesen}:
        teile = [z for z in gelesen if z["belegnr"] == beleg]
        assert sum(zahl(z["betrag"]) + zahl(z["steuer"]) for z in teile) == 0
        assert [z["buchcode"] for z in teile] == ["2", "1"]
        assert teile[0]["gkonto"] == "0" and teile[1]["gkonto"] == teile[0]["konto"]
    kreditor = next(z for z in gelesen if z["extbelegnr"] == "PM-1" and z["gkonto"] == "0")
    assert (kreditor["betrag"], kreditor["skontopz"], kreditor["skontotage"], kreditor["zziel"]) == (
        "-600,00",
        "2",
        "14",
        "30",
    )
    aufwand = next(z for z in gelesen if z["extbelegnr"] == "PM-1" and z["gkonto"] != "0")
    assert (aufwand["steuercode"], aufwand["prozent"], aufwand["steuer"], aufwand["kost"]) == ("2", "20", "100,00", "100")


def test_bmd_gutschrift_dreht_vorzeichen(haus):
    haus.frei(rechnung("GS-1", titel="GUTSCHRIFT", ziel=None))
    gelesen = zeilen(inhalt(haus, exportiere(haus, "bmd")), "cp1252")
    assert [(z["betrag"], z["buchcode"]) for z in gelesen] == [("600,00", "1"), ("-500,00", "2")]


def test_bmd_felder_ohne_trennzeichen(haus):
    nummer = haus.kontiert(rechnung())
    haus.aendere(nummer, buchungstext='Text; mit "Zeichen" und viel zu vielen Buchstaben am Ende')
    haus.sofort(nummer)
    roh = inhalt(haus, exportiere(haus, "bmd")).decode("cp1252")
    assert all(zeile.count(";") == len(BMD_SPALTEN) - 1 for zeile in roh.strip().split("\r\n"))
    assert max(len(z["text"]) for z in zeilen(roh.encode("cp1252"), "cp1252")) <= 40


def test_aufteilung_geht_in_einzelne_zeilen(haus):
    nummer = haus.kontiert(rechnung())
    teile = [
        {"konto": "7600", "kostenstelle": "100", "netto": "300", "satz": "20"},
        {"konto": "7200", "kostenstelle": "200", "netto": "200", "satz": "20"},
    ]
    haus.aendere(nummer, aufteilung=teile)
    haus.sofort(nummer)
    gelesen = zeilen(inhalt(haus, exportiere(haus)))
    assert [(z["Konto"], z["Kostenstelle"], z["Netto"]) for z in gelesen] == [
        ("7600", "100", "300,00"),
        ("7200", "200", "200,00"),
    ]


def test_zip_enthaelt_belege(haus):
    nummer = haus.frei(rechnung())
    eintrag = exportiere(haus, "zip")
    with zipfile.ZipFile(io.BytesIO(inhalt(haus, eintrag))) as archiv:
        assert set(archiv.namelist()) == {"buchungen.csv", "bmd.csv", f"belege/{nummer}.pdf"}
        assert archiv.read(f"belege/{nummer}.pdf").startswith(b"%PDF")


def test_auswahl_und_hindernis(haus):
    eins, zwei = haus.frei(rechnung("PM-1")), haus.frei(rechnung("PM-2"))
    eintrag = exportiere(haus, posten=[{"art": "beleg", "id": zwei}])
    assert eintrag["posten"] == [{"art": "beleg", "id": zwei}]
    partner = haus.beleg(eins)["partner"]["id"]
    haus.rufe("anna", "PATCH", f"/partner/{partner}", erwarte=200, json={"kreditor": ""})
    wartet = haus.rufe("anna", "GET", "/exporte/wartend", erwarte=200).json()
    assert wartet[0]["hindernis"] == "Kreditorenkonto fehlt"
    exportiere(haus, erwarte=409)


def test_rueckstellung_und_aufloesung(haus):
    letzter = date.today().replace(day=1) - timedelta(days=1)
    tage = (date.today() - letzter).days
    nummer = haus.kontiert(rechnung(tage=tage))
    periode = f"{letzter:%Y-%m}"
    vorschau = haus.rufe("anna", "GET", f"/exporte/rueckstellungen?periode={periode}", erwarte=200).json()
    assert [b["id"] for b in vorschau["neu"]] == [nummer] and vorschau["aufloesen"] == []
    eintrag = haus.rufe("anna", "POST", "/exporte/rueckstellungen", erwarte=201, json={"periode": periode}).json()
    gelesen = zeilen(inhalt(haus, eintrag), "cp1252")
    assert [z["betrag"] for z in gelesen] == ["-500,00", "500,00"] and gelesen[0]["belegdatum"] == f"{letzter:%d.%m.%Y}"
    haus.rufe("anna", "POST", "/exporte/rueckstellungen", erwarte=409, json={"periode": periode})
    haus.sofort(nummer)
    eintrag = haus.rufe("anna", "POST", "/exporte/rueckstellungen", erwarte=201, json={"periode": periode}).json()
    assert [z["betrag"] for z in zeilen(inhalt(haus, eintrag), "cp1252")] == ["500,00", "-500,00"]
    haus.rufe("anna", "POST", "/exporte/rueckstellungen", erwarte=409, json={"periode": periode})


def test_monatsende():
    assert monatsende("2028-02") == date(2028, 2, 29)


def test_stammdaten(haus):
    haus.frei(rechnung())
    eintrag = haus.rufe("anna", "POST", "/exporte/stammdaten", erwarte=201).json()
    assert zeilen(inhalt(haus, eintrag))[0]["Name"] == PAPIER.name


def test_partner_pflegen(haus):
    daten = {"name": "Neu GmbH", "uid": "ATU 1234 5675", "ibans": ["AT61 1904 3002 3457 3201"], "zahlungsziel": 14}
    neu = haus.rufe("anna", "POST", "/partner", erwarte=201, json=daten).json()
    assert neu["uid"] == "ATU12345675" and neu["ibans"] == ["AT611904300234573201"] and neu["kreditor"] == "330001"
    haus.rufe("anna", "PATCH", f"/partner/{neu['id']}", erwarte=422, json={"ibans": ["AT00"]})
    haus.rufe("anna", "PATCH", f"/partner/{neu['id']}", erwarte=200, json={"konto": "7600", "kostenstelle": "200"})
    b = haus.beleg(haus.lade(rechnung()))
    assert b["partner"]["id"] == neu["id"] and (b["konto"], b["kostenstelle"]) == ("7600", "200")
