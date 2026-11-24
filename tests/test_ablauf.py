import csv
import io

from sqlalchemy import update

from app.db import Protokoll, sitzungen


def codes(antwort, stufe="fehler"):
    return {h["code"] for h in antwort.json()["hinweise"] if h["stufe"] == stufe}


def test_guter_beleg_ist_bereit(lade, pdf):
    antwort = lade(pdf())
    assert antwort.status_code == 201
    daten = antwort.json()
    assert daten["status"] == "bereit"
    assert daten["brutto"] == "600.00"
    assert daten["lieferant_uid"] == "ATU12345675"


def test_anmeldung_und_rollen(client, rufe, lade, pdf):
    assert client.get("/belege").status_code == 401
    assert rufe("GET", "/belege", "falsch").status_code == 401
    assert rufe("GET", "/belege", "t-eingang").status_code == 403
    assert lade(pdf(), token="t-ben").status_code == 403
    nummer = lade(pdf("PM-2")).json()["id"]
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-anna").status_code == 403
    assert rufe("PATCH", f"/belege/{nummer}", "t-ben", json={"konto": "1"}).status_code == 403


def test_gleiche_datei_wird_abgewiesen(lade, pdf):
    inhalt = pdf()
    erste = lade(inhalt).json()["id"]
    zweite = lade(inhalt)
    assert zweite.status_code == 409
    assert zweite.json()["beleg_id"] == erste


def test_falsche_dateien(lade):
    assert lade(b"").status_code == 422
    assert lade(b"MZ kein Beleg").status_code == 422
    assert lade(b"%PDF-" + b"x" * (10 * 1024 * 1024 + 1)).status_code == 422


def test_unlesbares_pdf_geht_in_die_pruefung(rufe, lade):
    antwort = lade(b"%PDF-1.4 kaputt")
    assert antwort.status_code == 201
    assert antwort.json()["status"] == "pruefen"
    assert "extraktion" in codes(antwort)
    nummer = antwort.json()["id"]
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").status_code == 409


def test_falsche_summe(lade, pdf):
    assert "summe" in codes(lade(pdf(summe_falsch=100.0)))


def test_falsche_uid(lade, pdf):
    assert "uid" in codes(lade(pdf(lieferant=("Firma", "ATU87654321", "AT61 1904 3002 3457 3201"))))


def test_kleinbetrag_braucht_keine_uid(lade, pdf):
    antwort = lade(pdf(netto=100.0, lieferant=("Firma", None, "AT61 1904 3002 3457 3201")))
    assert antwort.json()["status"] == "bereit"


def test_rechnung_ueber_400_euro_braucht_uid(lade, pdf):
    antwort = lade(pdf(netto=400.0, lieferant=("Firma", None, "AT61 1904 3002 3457 3201")))
    assert "pflichtfeld" in codes(antwort)


def test_doppelte_rechnungsnummer(lade, pdf):
    lade(pdf("PM-1"))
    assert "duplikat" in codes(lade(pdf("PM-1", tage=5)))


def test_duplikat_sperrt_das_original_nicht(rufe, lade, pdf):
    original = lade(pdf("PM-1")).json()["id"]
    lade(pdf("PM-1", tage=5))
    rufe("PATCH", f"/belege/{original}", json={"konto": "7600", "kostenstelle": "100"})
    assert rufe("POST", f"/belege/{original}/freigabe", "t-ben").status_code == 200


def test_neue_iban_braucht_bestaetigung(rufe, lade, pdf, freigegeben):
    freigegeben("PM-1")
    andere = ("Papier Muster GmbH", "ATU12345675", "AT48 3200 0000 1234 5864")
    antwort = lade(pdf("PM-2", lieferant=andere))
    assert "iban_neu" in codes(antwort)
    nummer = antwort.json()["id"]
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").status_code == 409
    bestaetigt = rufe("POST", f"/belege/{nummer}/iban-bestaetigung", "t-ben", json={"grund": "Telefonisch geprüft"})
    assert bestaetigt.json()["status"] == "bereit"
    assert "iban_neu" in codes(bestaetigt, "warnung")
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").status_code == 200


def test_iban_aenderung_hebt_bestaetigung_auf(rufe, lade, pdf, freigegeben):
    freigegeben("PM-1")
    andere = ("Papier Muster GmbH", "ATU12345675", "AT48 3200 0000 1234 5864")
    nummer = lade(pdf("PM-2", lieferant=andere)).json()["id"]
    rufe("POST", f"/belege/{nummer}/iban-bestaetigung", "t-ben", json={"grund": "Telefonisch geprüft"})
    antwort = rufe("PATCH", f"/belege/{nummer}", json={"iban": "DE89 3704 0044 0532 0130 00"})
    assert "iban_neu" in codes(antwort)


def test_vier_augen(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    rufe("PATCH", f"/belege/{nummer}", "t-chef", json={"konto": "7600", "kostenstelle": "100"})
    selbst = rufe("POST", f"/belege/{nummer}/freigabe", "t-chef")
    assert selbst.status_code == 409
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").json()["freigegeben_von"] == "Ben"


def test_freigabe_braucht_konto(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").status_code == 409


def test_korrektur_macht_beleg_bereit(rufe, lade, pdf):
    nummer = lade(pdf(summe_falsch=100.0)).json()["id"]
    antwort = rufe("PATCH", f"/belege/{nummer}", json={"brutto": "600.00"})
    assert antwort.json()["status"] == "bereit"
    assert antwort.json()["bearbeitet_von"] == "Anna"


def test_ungueltige_korrektur(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    assert rufe("PATCH", f"/belege/{nummer}", json={"brutto": "abc"}).status_code == 422
    zeile = {"satz": "x", "netto": "1", "ust": "1"}
    assert rufe("PATCH", f"/belege/{nummer}", json={"steuerzeilen": [zeile]}).status_code == 422


def test_freigegebener_beleg_ist_gesperrt(rufe, freigegeben):
    nummer = freigegeben()
    assert rufe("PATCH", f"/belege/{nummer}", json={"brutto": "1.00"}).status_code == 409
    assert rufe("POST", f"/belege/{nummer}/ablehnung", "t-ben", json={"grund": "zu spät"}).status_code == 409


def test_konto_wird_vorgeschlagen(lade, pdf, freigegeben):
    freigegeben("PM-1")
    assert lade(pdf("PM-2")).json()["konto"] == "7600"


def test_export(rufe, freigegeben):
    freigegeben()
    antwort = rufe("POST", "/export")
    assert antwort.content.startswith(b"\xef\xbb\xbf")
    zeilen = list(csv.DictReader(io.StringIO(antwort.content.decode("utf-8-sig")), delimiter=";"))
    assert zeilen[0]["Netto"] == "500,00"
    assert zeilen[0]["USt"] == "100,00"
    assert zeilen[0]["Konto"] == "7600"
    assert rufe("POST", "/export").status_code == 404


def test_export_entschaerft_formeln(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    rufe("PATCH", f"/belege/{nummer}", json={"lieferant": "=1+1", "konto": "1", "kostenstelle": "1"})
    assert rufe("POST", f"/belege/{nummer}/freigabe", "t-ben").status_code == 200
    assert "'=1+1" in rufe("POST", "/export").content.decode("utf-8-sig")


def test_protokoll_erkennt_manipulation(rufe, freigegeben):
    nummer = freigegeben()
    aktionen = [eintrag["aktion"] for eintrag in rufe("GET", f"/belege/{nummer}/protokoll").json()]
    assert aktionen == ["erfasst", "korrigiert", "freigegeben"]
    assert rufe("GET", "/protokoll/pruefung").json() == {"gueltig": True, "fehler_bei": None}
    with sitzungen()() as db:
        db.execute(update(Protokoll).where(Protokoll.id == 2).values(benutzer="Fremd"))
        db.commit()
    assert rufe("GET", "/protokoll/pruefung").json() == {"gueltig": False, "fehler_bei": 2}


def test_datei(rufe, lade, pdf):
    inhalt = pdf()
    nummer = lade(inhalt).json()["id"]
    assert rufe("GET", f"/belege/{nummer}/datei").content == inhalt
    assert rufe("GET", "/belege/999").status_code == 404


def test_bild_vom_beleg(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    antwort = rufe("GET", f"/belege/{nummer}/bild")
    assert antwort.content.startswith(b"\x89PNG")
    assert antwort.headers["x-seiten"] == "1"
    assert rufe("GET", f"/belege/{nummer}/bild?seite=2").status_code == 422
    kaputt = lade(b"%PDF-1.4 kaputt").json()["id"]
    assert rufe("GET", f"/belege/{kaputt}/bild").status_code == 422


def test_uebersicht_zaehlt_automatische_belege(rufe, lade, pdf):
    assert rufe("GET", "/uebersicht").json()["quote"] is None
    erster = lade(pdf("PM-1")).json()["id"]
    zweiter = lade(pdf("PM-2", summe_falsch=10.0)).json()["id"]
    daten = rufe("GET", "/uebersicht").json()
    assert daten["quote"] == 50
    assert daten["fehler"][0]["anzahl"] == 1
    assert len(daten["monate"]) == 6
    assert daten["monate"][-1]["anzahl"] == 2
    rufe("PATCH", f"/belege/{zweiter}", json={"brutto": "600.00"})
    assert rufe("GET", "/uebersicht").json()["quote"] == 50
    rufe("PATCH", f"/belege/{erster}", json={"konto": "7600"})
    assert rufe("GET", f"/belege/{erster}").json()["automatisch"] is True


def test_regel_setzt_konto(rufe, lade, pdf):
    regel = {"lieferant_uid": "ATU 1234 5675", "lieferant": "Papier", "konto": "7600", "kostenstelle": "200"}
    assert rufe("POST", "/regeln", "t-ben", json=regel).status_code == 403
    angelegt = rufe("POST", "/regeln", json=regel)
    assert angelegt.status_code == 201
    assert rufe("POST", "/regeln", json=regel).status_code == 409
    assert lade(pdf()).json()["kostenstelle"] == "200"
    assert rufe("DELETE", f"/regeln/{angelegt.json()['id']}").status_code == 204
    assert rufe("GET", "/regeln").json() == []


def test_suche_und_lieferanten(rufe, lade, pdf):
    lade(pdf("PM-1"))
    lade(pdf("PM-2"))
    assert len(rufe("GET", "/belege?suche=pm-2").json()) == 1
    assert rufe("GET", "/belege?suche=%25").json() == []
    assert rufe("GET", "/lieferanten").json()[0]["belege"] == 2


def test_benutzerliste_enthaelt_keine_tokens(rufe):
    antwort = rufe("GET", "/benutzer")
    assert len(antwort.json()) == 4
    assert "t-anna" not in antwort.text


def test_oberflaeche_hat_schutz(client):
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]
    assert client.get("/static/icons.svg").headers["cache-control"] == "no-cache"
    assert client.get("/belege").headers["cache-control"] == "no-store"


def test_kommentar_steht_im_verlauf(rufe, lade, pdf):
    nummer = lade(pdf()).json()["id"]
    antwort = rufe("POST", f"/belege/{nummer}/kommentar", "t-ben", json={"text": "Bitte prüfen"})
    assert antwort.status_code == 201
    assert antwort.json()[-1]["details"] == {"text": "Bitte prüfen"}
    assert rufe("POST", f"/belege/{nummer}/kommentar", "t-eingang", json={"text": "x"}).status_code == 403
    assert rufe("GET", "/protokoll/pruefung").json()["gueltig"] is True
