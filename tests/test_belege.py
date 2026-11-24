from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.demo.dateien import Firma, Posten, iban, pdf, uid
from app.modelle import Benutzer

from .conftest import EIGEN, PAPIER, PUTZ, rechnung


def codes(beleg, *stufen):
    return {e["code"] for e in beleg["pruefbericht"] if e["stufe"] in stufen}


def test_rechnung_wird_gelesen_und_geprueft(haus):
    nummer = haus.lade(rechnung(skonto=(2, 10), bestellnummer="BA-1"))
    b = haus.beleg(nummer)
    assert (b["art"], b["status"], b["stufe"]) == ("rechnung", "neu", "ok")
    assert (b["lieferant"], b["lieferant_uid"], b["iban"]) == (PAPIER.name, PAPIER.uid, PAPIER.iban)
    assert (b["netto"], b["ust"], b["brutto"]) == ("500.00", "100.00", "600.00")
    assert b["steuerzeilen"] == [{"satz": "20", "netto": "500.00", "ust": "100.00"}]
    assert b["skonto_prozent"] == "2" and b["bestellnummer"] == "BA-1"
    assert b["positionen"][0]["text"] == "Ware"
    assert b["erkannt"]["brutto"] == "Regeln"
    assert {"hochgeladen", "erkannt", "geprueft"} <= {v["aktion"] for v in b["verlauf"]}


def test_gleiche_datei_wird_abgelehnt(haus):
    inhalt = pdf(rechnung())
    erster = haus.lade(inhalt)
    antwort = haus.rufe("anna", "POST", "/belege", erwarte=201, files=[("dateien", ("x.pdf", inhalt))]).json()[0]
    assert antwort["fehler"] == "Diese Datei wurde bereits erfasst" and antwort["id"] == erster


def test_andere_mandanten_duerfen_dieselbe_datei_haben(haus):
    inhalt = pdf(rechnung())
    haus.lade(inhalt)
    haus.lade(inhalt, "boris", mandant="b")


@pytest.mark.parametrize("inhalt", [b"", b"GIF89a", b"MZ\x90", b"<html></html>", b"<?xml version='1.0'?><x/>"])
def test_fremde_dateien_werden_abgelehnt(haus, inhalt):
    antwort = haus.rufe("anna", "POST", "/belege", erwarte=201, files=[("dateien", ("x.pdf", inhalt))]).json()[0]
    assert antwort["fehler"] and antwort["id"] is None


def test_zu_grosse_datei(haus):
    inhalt = b"%PDF-" + b"0" * (10 * 1024 * 1024)
    antwort = haus.rufe("anna", "POST", "/belege", erwarte=201, files=[("dateien", ("x.pdf", inhalt))]).json()[0]
    assert "größer" in antwort["fehler"]


def test_kaputtes_pdf_und_bild_brauchen_handarbeit(haus):
    for inhalt in (b"%PDF-1.4 kaputt", b"\x89PNG\r\n\x1a\nkaputt"):
        b = haus.beleg(haus.lade(inhalt))
        assert b["stufe"] in ("sperre", "ok")
        assert b["lieferant"] is None


def test_falsche_summe_sperrt(haus):
    b = haus.beleg(haus.lade(rechnung(falsch=Decimal(100))))
    assert b["stufe"] == "sperre" and "summe" in codes(b, "sperre")
    eintrag = next(e for e in b["pruefbericht"] if e["code"] == "summe")
    assert (eintrag["erwartet"], eintrag["vorhanden"]) == ("600.00", "700.00")


def test_kleinbetrag_braucht_weniger_angaben(haus):
    ohne = Firma("Taxi e.U.", "Weg 1", "1010", "Wien", None, PAPIER.iban)
    klein = haus.beleg(haus.lade(rechnung("T-1", "40", wer=ohne)))
    assert not codes(klein, "fehler", "sperre")
    gross = haus.beleg(haus.lade(rechnung("T-2", "800", wer=ohne)))
    assert "uid" in codes(gross, "fehler")


def test_ueber_zehntausend_braucht_eigene_uid(haus):
    ohne = haus.beleg(haus.lade(rechnung("G-1", "9000")))
    assert "empfaenger_uid" in codes(ohne, "fehler")
    mit = haus.beleg(haus.lade(rechnung("G-2", "9000", mit_uid=True)))
    assert "empfaenger_uid" in codes(mit, "ok")


def test_falscher_empfaenger_faellt_auf(haus):
    anderer = Firma("Ganz Andere GmbH", "Weg 9", "8010", "Graz", EIGEN.uid)
    b = haus.beleg(haus.lade(rechnung(an=anderer)))
    assert "empfaenger_name" in codes(b, "fehler")
    assert "empfaenger_plz" in codes(b, "warnung")


def test_neue_iban_sperrt_bis_zur_bestaetigung(haus):
    haus.frei(rechnung("PM-1"))
    fremd = Firma(PAPIER.name, PAPIER.strasse, PAPIER.plz, PAPIER.ort, PAPIER.uid, iban(55))
    nummer = haus.kontiert(rechnung("PM-2", wer=fremd))
    assert "iban_neu" in codes(haus.beleg(nummer), "sperre")
    haus.sofort(nummer, erwarte=409)
    aktion = {"aktion": "iban_bestaetigen", "grund": "telefonisch bestätigt"}
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=403, json=aktion)
    haus.rufe("lea", "POST", f"/belege/{nummer}/aktion", erwarte=422, json=aktion | {"grund": ""})
    haus.rufe("lea", "POST", f"/belege/{nummer}/aktion", erwarte=200, json=aktion)
    haus.sofort(nummer)


def test_bestaetigung_gilt_nur_fuer_diese_iban(haus):
    haus.frei(rechnung("PM-1"))
    fremd = Firma(PAPIER.name, PAPIER.strasse, PAPIER.plz, PAPIER.ort, PAPIER.uid, iban(55))
    nummer = haus.kontiert(rechnung("PM-2", wer=fremd))
    haus.rufe(
        "lea", "POST", f"/belege/{nummer}/aktion", erwarte=200, json={"aktion": "iban_bestaetigen", "grund": "geprüft"}
    )
    haus.aendere(nummer, iban=iban(56))
    assert "iban_neu" in codes(haus.beleg(nummer), "sperre")


def test_gesperrte_iban(haus):
    nummer = haus.kontiert(rechnung())
    haus.rufe("anna", "POST", "/sperren", erwarte=201, json={"art": "iban", "wert": PAPIER.iban, "grund": "Betrug"})
    assert "iban_gesperrt" in codes(haus.beleg(nummer), "sperre")
    haus.sofort(nummer, erwarte=409)
    sperre = haus.rufe("anna", "GET", "/sperren").json()[0]
    haus.rufe("anna", "DELETE", f"/sperren/{sperre['id']}", erwarte=403)
    haus.rufe("admin", "DELETE", f"/sperren/{sperre['id']}", erwarte=200)
    haus.sofort(nummer)


def test_duplikat_behalten_oder_anhaengen(haus):
    erster = haus.kontiert(rechnung("PM-1"))
    zweiter = haus.kontiert(rechnung("PM-1", tage=9))
    assert not codes(haus.beleg(erster), "sperre")
    assert haus.beleg(zweiter)["duplikat_von"] == erster
    dritter = haus.lade(rechnung("PM-1", tage=8))
    haus.rufe("anna", "POST", f"/belege/{dritter}/anhaengen", erwarte=200, json={"ziel": erster})
    assert [a["dateiname"] for a in haus.beleg(erster)["anhaenge"]] == ["beleg.pdf"]
    assert haus.beleg(dritter)["status"] == "papierkorb"
    haus.rufe(
        "anna", "POST", f"/belege/{zweiter}/aktion", erwarte=200, json={"aktion": "kein_duplikat", "grund": "Teilrechnung"}
    )
    assert "duplikat" not in codes(haus.beleg(zweiter), "sperre")
    haus.sofort(zweiter)


def test_konto_wird_vom_partner_gelernt(haus):
    haus.frei(rechnung("PM-1"), konto="7200", kostenstelle="200")
    b = haus.beleg(haus.lade(rechnung("PM-2")))
    assert (b["konto"], b["kostenstelle"]) == ("7200", "200")
    assert b["erkannt"]["konto"] == "Historie"
    assert b["partner"]["kreditor"] == "330001"


def test_aehnliche_belege_schlagen_konto_vor(haus):
    for nummer in range(4):
        wer = Firma(f"Reiniger {nummer} GmbH", "Weg 1", "1010", "Wien", uid(f"90000{nummer}1"), iban(20 + nummer))
        ware = [Posten("R-1", "Fensterreinigung Stiegenhaus monatlich", Decimal(1), "Stk", Decimal(500))]
        haus.frei(rechnung(f"R-{nummer}", wer=wer, posten=ware), konto="7200", kostenstelle="200")
        wer = Firma(f"Händler {nummer} GmbH", "Weg 2", "1010", "Wien", uid(f"80000{nummer}1"), iban(30 + nummer))
        ware = [Posten("K-1", "Kopierpapier Ordner Kugelschreiber", Decimal(1), "Stk", Decimal(500))]
        haus.frei(rechnung(f"H-{nummer}", wer=wer, posten=ware), konto="7600", kostenstelle="100")
    neu = Firma("Unbekannt GmbH", "Weg 3", "1010", "Wien", uid("7000001"), iban(40))
    ware = [Posten("X-1", "Fensterreinigung Stiegenhaus einmalig", Decimal(1), "Stk", Decimal(500))]
    b = haus.beleg(haus.lade(rechnung("U-1", wer=neu, posten=ware)))
    assert (b["konto"], b["erkannt"].get("konto")) == ("7200", "Ähnliche Belege")


def test_korrektur_wird_protokolliert_und_verliert_erkennung(haus):
    nummer = haus.lade(rechnung())
    b = haus.aendere(nummer, nummer="PM-9")
    assert "nummer" not in b["erkannt"] and b["automatisch"] is False
    eintrag = next(v for v in b["verlauf"] if v["aktion"] == "geaendert")
    assert eintrag["details"]["alt"] == {"nummer": "PM-1"} and eintrag["details"]["neu"] == {"nummer": "PM-9"}


@pytest.mark.parametrize(
    "werte",
    [{"brutto": "viel"}, {"datum": "morgen"}, {"unbekannt": 1}, {"notiz": "a\x00b"}, {"art": "brief"}, {"waehrung": "euro"}],
)
def test_ungueltige_eingaben(haus, werte):
    haus.aendere(haus.lade(rechnung()), erwarte=422, **werte)


def test_aufteilung_muss_aufgehen(haus):
    nummer = haus.lade(rechnung())
    teil = {"konto": "7600", "kostenstelle": "100", "netto": "300", "satz": "20"}
    haus.aendere(nummer, aufteilung=[teil])
    haus.sofort(nummer, erwarte=409)
    haus.aendere(nummer, aufteilung=[teil, teil | {"kostenstelle": "200", "netto": "200"}])
    haus.sofort(nummer)


def test_kommentar_mit_erwaehnung(haus):
    nummer = haus.lade(rechnung())
    assert haus.rufe("cleo", "GET", f"/belege/{nummer}").status_code == 404
    haus.rufe("anna", "POST", f"/belege/{nummer}/kommentar", erwarte=201, json={"text": "@Cleo bitte ansehen"})
    mitteilung = haus.rufe("cleo", "GET", "/mitteilungen", erwarte=200).json()[0]
    assert mitteilung["ziel"] == f"beleg/{nummer}" and not mitteilung["gelesen"]
    haus.rufe("cleo", "POST", "/mitteilungen/gelesen", erwarte=204, json={})
    assert haus.rufe("cleo", "GET", "/zaehler").json()["mitteilungen"] == 0
    assert haus.rufe("cleo", "GET", f"/belege/{nummer}").status_code == 200


def test_eingeschraenkte_sichtbarkeit(haus):
    nummer = haus.lade(rechnung())
    sicht = {"eingeschraenkt": True, "personen": [haus.p["dora"]]}
    haus.rufe("anna", "PUT", f"/belege/{nummer}/sichtbarkeit", erwarte=200, json=sicht)
    assert haus.rufe("eva", "GET", f"/belege/{nummer}").status_code == 404
    assert haus.rufe("chef", "GET", f"/belege/{nummer}").status_code == 404
    assert haus.rufe("dora", "GET", f"/belege/{nummer}").status_code == 200
    assert haus.rufe("admin", "GET", f"/belege/{nummer}").status_code == 200
    assert haus.rufe("eva", "GET", "/suche?q=PM-1").json()["belege"] == []
    assert haus.rufe("eva", "GET", "/eingang").json()["gesamt"] == 0


def test_klaerung_papierkorb_und_ablage(haus):
    nummer = haus.lade(rechnung())
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=200, json={"aktion": "klaerung"})
    assert haus.rufe("anna", "GET", "/eingang?klaerung=true").json()["gesamt"] == 1
    assert haus.rufe("anna", "GET", "/eingang").json()["gesamt"] == 0
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=409, json={"aktion": "ablegen"})
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=200, json={"aktion": "papierkorb"})
    assert haus.rufe("anna", "GET", "/archiv?status=papierkorb").json()["gesamt"] == 1
    haus.aendere(nummer, erwarte=409, konto="1")
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=200, json={"aktion": "wiederherstellen"})
    assert haus.beleg(nummer)["status"] == "neu"


def test_vertrag(haus):
    vertrag = rechnung("WV-1", titel="VERTRAG", ziel=None, posten=[], zeilen=["Wartungsvertrag für den Aufzug"])
    vertrag.posten = []
    nummer = haus.lade(vertrag)
    b = haus.beleg(nummer)
    assert b["art"] == "vertrag" and b["vertrag"]["typ"] is None
    bald = (date.today() + timedelta(days=7)).isoformat()
    werte = {"typ": "Wartung", "kuendigen_bis": bald, "verantwortlich_id": haus.p["ben"], "informieren": [haus.p["eva"]]}
    haus.rufe("anna", "PATCH", f"/belege/{nummer}/vertrag", erwarte=200, json=werte)
    haus.rufe("anna", "PATCH", f"/belege/{nummer}/vertrag", erwarte=422, json={"verantwortlich_id": haus.p["boris"]})
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=200, json={"aktion": "ablegen"})
    assert haus.rufe("anna", "GET", "/vertraege").json()[0]["vertrag"]["kuendigen_bis"] == bald
    texte = haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/erinnerungen", erwarte=200).json()
    assert {e["name"] for e in texte} == {"Ben", "Eva"}


def test_schlagwoerter_werden_vorgeschlagen(haus):
    erster = haus.frei(rechnung("PM-1"))
    haus.rufe("anna", "PUT", f"/belege/{erster}/schlagwoerter", erwarte=200, json={"namen": ["Büro", " Büro ", "2026"]})
    zweiter = haus.beleg(haus.lade(rechnung("PM-2")))
    assert zweiter["schlagwort_vorschlaege"] == ["Büro", "2026"] or set(zweiter["schlagwort_vorschlaege"]) == {
        "Büro",
        "2026",
    }


def test_verknuepfungen(haus):
    angebot = haus.lade(rechnung("AN-1", titel="ANGEBOT", ziel=None))
    auftrag = haus.lade(rechnung("AB-1", titel="AUFTRAGSBESTÄTIGUNG", ziel=None, bestellnummer="B-7"))
    rechnungsnummer = haus.lade(rechnung("PM-1", bestellnummer="B-7"))
    b = haus.beleg(rechnungsnummer)
    assert (auftrag, "gleiche Bestellnummer") in {(v["id"], v["hinweis"]) for v in b["verknuepfung_vorschlaege"]}
    pfad = f"/belege/{rechnungsnummer}/verknuepfung"
    haus.rufe("anna", "POST", pfad, erwarte=201, json={"art": "beleg", "id": auftrag})
    haus.rufe("anna", "POST", pfad, erwarte=201, json={"art": "beleg", "id": angebot})
    haus.rufe("anna", "POST", pfad, erwarte=422, json={"art": "beleg", "id": rechnungsnummer})
    assert {v["id"] for v in haus.beleg(auftrag)["verknuepfungen"]} == {rechnungsnummer}
    haus.rufe("anna", "DELETE", f"{pfad}/beleg/{angebot}", erwarte=200)
    assert haus.beleg(angebot)["verknuepfungen"] == []


def test_anhang_und_dateien(haus):
    nummer = haus.lade(rechnung())
    haus.rufe("anna", "POST", f"/belege/{nummer}/anhaenge", erwarte=201, files={"datei": ("regie.pdf", pdf(rechnung("X")))})
    anhang = haus.beleg(nummer)["anhaenge"][0]
    antwort = haus.rufe("anna", "GET", f"/anhaenge/{anhang['id']}/datei", erwarte=200)
    assert antwort.headers["content-type"] == "application/pdf" and "sandbox" in antwort.headers["content-security-policy"]
    assert haus.rufe("dora", "GET", f"/anhaenge/{anhang['id']}/datei").status_code == 404
    bild = haus.rufe("anna", "GET", f"/belege/{nummer}/bild", erwarte=200)
    assert bild.headers["content-type"] == "image/png" and bild.headers["x-seiten"] == "1"
    assert haus.rufe("anna", "GET", f"/belege/{nummer}/bild?seite=2").status_code == 422


def test_sammelaktionen(haus):
    eins, zwei = haus.kontiert(rechnung("PM-1")), haus.kontiert(rechnung("PM-2", wer=PUTZ))
    gesperrt = haus.kontiert(rechnung("PM-3", falsch=Decimal(5)))
    daten = {"nummern": [eins, zwei, gesperrt], "aktion": "freigeben"}
    haus.rufe("ben", "POST", "/belege/sammel", erwarte=403, json=daten)
    antwort = haus.rufe("chef", "POST", "/belege/sammel", erwarte=200, json=daten).json()
    assert antwort["fertig"] == [eins, zwei] and antwort["fehler"][0]["id"] == gesperrt


def test_suche_und_filter(haus):
    haus.frei(rechnung("PM-1001"))
    haus.frei(rechnung("RB-1", wer=PUTZ, netto="50"))
    haus.lade(rechnung("PM-1002", tage=3))

    def archiv(abfrage):
        return haus.rufe("anna", "GET", f"/archiv?{abfrage}", erwarte=200).json()["gesamt"]

    assert archiv("") == 2
    assert archiv("suche=1001") == 1
    assert archiv("suche=1001&modus=exakt") == 0
    assert archiv("suche=pm-1001&modus=exakt") == 1
    assert archiv("suche=pm-1&modus=beginnt") == 1
    assert archiv("suche=PM_1001") == 0
    assert archiv("betrag_ab=100") == 1
    assert archiv("betrag_bis=100") == 1
    assert archiv("kostenstelle=999") == 0
    assert haus.rufe("anna", "GET", "/archiv?betrag_ab=abc").status_code == 422
    treffer = haus.rufe("anna", "GET", "/suche?q=reinigung", erwarte=200).json()
    assert len(treffer["belege"]) == 1 and treffer["partner"][0]["name"] == PUTZ.name


def test_ueberfaellige_belege(haus):
    haus.lade(rechnung("PM-1", tage=40))
    haus.lade(rechnung("PM-2", tage=2))
    assert haus.rufe("anna", "GET", "/eingang?merkmal=ueberfaellig").json()["gesamt"] == 1
    assert haus.rufe("anna", "GET", "/zaehler").json()["eingang"]["ueberfaellig"] == 1


def test_uebersicht(haus):
    haus.frei(rechnung("PM-1"))
    haus.rufe("anna", "POST", "/budgets", erwarte=201, json={"art": "kostenstelle", "wert": "100", "budget": "1000"})
    jahr = (date.today() - timedelta(days=10)).year
    daten = haus.rufe("anna", "GET", f"/uebersicht?jahr={jahr}&basis=netto&nach=partner", erwarte=200).json()
    assert daten["budgets"][0]["verbraucht"] == "500.00"
    assert daten["verteilung"][0]["summe"] == "500.00"
    assert daten["kennzahlen"]["belege"] == 1
    klein = haus.rufe("dora", "GET", "/uebersicht", erwarte=200).json()
    assert "budgets" not in klein and "eingang" not in klein["zaehler"]


def test_abwesende_stehen_in_den_stammdaten(haus):
    with haus.db() as db:
        ben = db.get(Benutzer, haus.p["ben"])
        ben.abwesend_von, ben.vertretung_id = date.today(), haus.p["cleo"]
        db.commit()
    personen = haus.rufe("anna", "GET", "/stammdaten", erwarte=200).json()["personen"]
    assert [p["name"] for p in personen if p["abwesend"]] == ["Ben"]
