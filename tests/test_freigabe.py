from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.demo.dateien import Firma
from app.modelle import Automatik, Beleg, Benutzer, Team

from .conftest import PAPIER, rechnung


def team(haus, *mitglieder):
    with haus.db() as db:
        neu = Team(mandant_id=haus.m["a"], name="Leitung", mitglieder=[haus.p[m] for m in mitglieder])
        db.add(neu)
        db.commit()
        return {"art": "team", "id": neu.id}


def workflow(haus, name, bedingung, *schritte, rang=10):
    daten = {"name": name, "rang": rang, "bedingung": bedingung, "schritte": list(schritte)}
    liste = haus.rufe("admin", "POST", "/workflows", erwarte=201, json=daten).json()
    return next(w["id"] for w in liste if w["name"] == name)


def person(haus, kurz):
    return {"art": "person", "id": haus.p[kurz]}


def test_zwei_schritte_in_reihenfolge(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben", "cleo")
    assert haus.beleg(nummer)["status"] == "freigabe"
    haus.entscheide("cleo", nummer, erwarte=403)
    haus.entscheide("ben", nummer)
    assert haus.beleg(nummer)["status"] == "freigabe"
    haus.entscheide("ben", nummer, erwarte=403)
    haus.entscheide("cleo", nummer)
    b = haus.beleg(nummer)
    assert b["status"] == "freigegeben" and [s["von"] for s in b["freigabe"]] == ["Ben", "Cleo"]
    haus.entscheide("cleo", nummer, erwarte=409)


def test_ablehnen_braucht_grund_und_beendet_alles(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben", "cleo")
    haus.entscheide("ben", nummer, ja=False, erwarte=422)
    haus.entscheide("ben", nummer, ja=False, grund="Leistung fehlt")
    b = haus.beleg(nummer)
    assert b["status"] == "abgelehnt" and [s["status"] for s in b["freigabe"]] == ["abgelehnt", "entfallen"]
    assert "Leistung fehlt" in haus.rufe("anna", "GET", "/mitteilungen").json()[0]["text"]
    haus.rufe("anna", "POST", f"/freigaben/beleg/{nummer}/oeffnen", erwarte=204)
    assert haus.beleg(nummer)["status"] == "neu"


def test_vier_augen(haus):
    nummer = haus.kontiert(rechnung(), "chef")
    haus.sofort(nummer, "chef", erwarte=409)
    haus.fordere(nummer, "chef", erwarte=204)
    haus.entscheide("chef", nummer, erwarte=409)
    haus.rufe("anna", "POST", f"/freigaben/beleg/{nummer}/zurueckziehen", erwarte=204)
    haus.sofort(nummer)


def test_sofort_nur_bei_sichtbaren_belegen(haus):
    nummer = haus.kontiert(rechnung())
    haus.sofort(nummer, "ben", erwarte=404)
    haus.sofort(nummer, "anna", erwarte=403)
    haus.sofort(nummer, "lea")


def test_vier_augen_laesst_sich_abschalten(haus):
    haus.rufe("admin", "PATCH", "/mandant", erwarte=200, json={"vier_augen": False})
    haus.sofort(haus.kontiert(rechnung(), "chef"), "chef")


def test_ohne_kontierung_keine_freigabe(haus):
    nummer = haus.lade(rechnung())
    haus.fordere(nummer, "ben", erwarte=409)
    haus.sofort(nummer, erwarte=409)


def test_fehler_brauchen_begruendung(haus):
    ohne = Firma("Ohne UID GmbH", "Weg 1", "1010", "Wien", None, PAPIER.iban)
    nummer = haus.kontiert(rechnung(wer=ohne))
    antwort = haus.sofort(nummer, erwarte=409)
    assert antwort.json()["grund_noetig"] is True
    haus.sofort(nummer, grund="Lieferant ist Kleinunternehmer")
    eintrag = next(v for v in haus.beleg(nummer)["verlauf"] if v["aktion"] == "freigegeben")
    assert eintrag["details"]["grund"] == "Lieferant ist Kleinunternehmer"


def test_sperre_laesst_sich_nicht_begruenden(haus):
    nummer = haus.kontiert(rechnung(falsch=Decimal(10)))
    haus.sofort(nummer, erwarte=409, grund="passt schon")


def test_nur_freigabeberechtigte_als_ziel(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "dora", erwarte=422)
    haus.fordere(nummer, erwarte=409)
    haus.fordere(nummer, "ben", wer="ben", erwarte=404)


def test_team_und_vertretung(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, team(haus, "ben"))
    haus.entscheide("cleo", nummer, erwarte=404)
    with haus.db() as db:
        ben = db.get(Benutzer, haus.p["ben"])
        ben.abwesend_von, ben.abwesend_bis = date.today(), date.today() + timedelta(days=2)
        ben.vertretung_id = haus.p["cleo"]
        db.commit()
    offen = haus.rufe("cleo", "GET", "/freigaben", erwarte=200).json()
    assert [e["id"] for e in offen] == [nummer] and offen[0]["kann"]
    haus.entscheide("cleo", nummer)
    schritt = haus.beleg(nummer)["freigabe"][0]
    assert (schritt["von"], schritt["in_vertretung"]) == ("Cleo", "Ben")


def test_weiterleiten(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben")
    daten = {"ziel": person(haus, "cleo"), "grund": "bin befangen"}
    haus.rufe("cleo", "POST", f"/freigaben/beleg/{nummer}/weiterleiten", erwarte=404, json=daten)
    haus.rufe("ben", "POST", f"/freigaben/beleg/{nummer}/weiterleiten", erwarte=204, json=daten)
    haus.entscheide("cleo", nummer)


def test_listen_der_freigaben(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben")

    def liste(wer, sicht):
        return [e["id"] for e in haus.rufe(wer, "GET", f"/freigaben?sicht={sicht}", erwarte=200).json()]

    assert liste("ben", "meine") == [nummer]
    assert liste("cleo", "meine") == []
    assert liste("anna", "angefragt") == [nummer]
    assert liste("eva", "alle") == [nummer]
    assert haus.rufe("ben", "GET", "/freigaben?sicht=alle").status_code == 403
    antwort = haus.rufe(
        "ben", "POST", "/freigaben/sammel", erwarte=200, json={"eintraege": [{"art": "beleg", "id": nummer}]}
    )
    assert antwort.json()["fertig"] == [nummer]


def test_workflow_nach_bedingung(haus):
    workflow(haus, "Klein", {"art": "beleg", "bis": "100"}, person(haus, "ben"))
    workflow(haus, "Groß", {"art": "beleg"}, person(haus, "cleo"), person(haus, "ben"), rang=20)
    klein, gross = haus.kontiert(rechnung("K-1", "50")), haus.kontiert(rechnung("G-1", "500"))
    assert haus.beleg(klein)["workflow"]["name"] == "Klein"
    assert haus.beleg(gross)["workflow"]["name"] == "Groß"
    haus.fordere(gross)
    assert [s["ziel"] for s in haus.beleg(gross)["freigabe"]] == ["Cleo", "Ben"]


@pytest.mark.parametrize("kurz", ["dora", "boris"])
def test_workflow_nur_mit_berechtigten(haus, kurz):
    daten = {"name": "Falsch", "schritte": [person(haus, kurz)]}
    haus.rufe("admin", "POST", "/workflows", erwarte=422, json=daten)


def regel(haus, aktion, **mehr):
    daten = {"name": "Regel", "aktion": aktion, "max_brutto": "700", "gleiche": 2} | mehr
    return haus.rufe("admin", "POST", "/automatiken", erwarte=201, json=daten).json()


def test_automatik_gibt_nach_gleichen_buchungen_frei(haus):
    regel(haus, "freigeben")
    haus.frei(rechnung("PM-1"))
    dritter = haus.lade(rechnung("PM-2"))
    assert haus.beleg(dritter)["status"] == "neu"
    haus.sofort(dritter)
    vierter = haus.beleg(haus.lade(rechnung("PM-3")))
    assert (vierter["status"], vierter["automatik"]) == ("freigegeben", "freigegeben")
    eintrag = next(v for v in vierter["verlauf"] if v["aktion"] == "freigegeben")
    assert eintrag["wer"] == "Automatik" and eintrag["details"]["regel"] == "Regel"


def test_automatik_achtet_auf_betrag_fehler_und_iban(haus):
    regel(haus, "freigeben")
    haus.frei(rechnung("PM-1"))
    haus.frei(rechnung("PM-2"))
    assert haus.beleg(haus.lade(rechnung("PM-3", "900")))["status"] == "neu"
    assert haus.beleg(haus.lade(rechnung("PM-4", falsch=Decimal(5))))["status"] == "neu"
    fremd = Firma(PAPIER.name, PAPIER.strasse, PAPIER.plz, PAPIER.ort, PAPIER.uid, "AT611904300234573201")
    assert haus.beleg(haus.lade(rechnung("PM-5", wer=fremd)))["status"] == "neu"


def test_automatik_fordert_freigabe_an(haus):
    ziel = workflow(haus, "Immer", {"art": "beleg"}, person(haus, "cleo"))
    regel(haus, "anfordern", workflow_id=ziel)
    haus.frei(rechnung("PM-1"))
    haus.frei(rechnung("PM-2"))
    assert haus.beleg(haus.lade(rechnung("PM-3")))["status"] == "freigabe"
    haus.rufe("admin", "DELETE", f"/workflows/{ziel}", erwarte=409)


def test_automatik_schlaegt_nur_vor(haus):
    regel(haus, "vorschlagen")
    haus.frei(rechnung("PM-1"))
    haus.frei(rechnung("PM-2"))
    nummer = haus.lade(rechnung("PM-3"))
    b = haus.beleg(nummer)
    assert b["status"] == "neu" and b["regel"]["aktion"] == "vorschlagen"
    assert haus.rufe("anna", "GET", "/eingang").json()["automatik"] == [nummer]


def test_kaputte_automatik_verhindert_den_eingang_nicht(haus):
    ziel = workflow(haus, "Immer", {"art": "beleg"}, person(haus, "cleo"))
    regel(haus, "anfordern", workflow_id=ziel)
    haus.frei(rechnung("PM-1"))
    haus.frei(rechnung("PM-2"))
    haus.rufe("admin", "PATCH", f"/personen/{haus.p['cleo']}", erwarte=200, json={"rollen": ["mitarbeit"]})
    b = haus.beleg(haus.lade(rechnung("PM-3")))
    assert b["status"] == "neu" and "automatik_fehler" in {v["aktion"] for v in b["verlauf"]}


def test_person_mit_offenen_freigaben_bleibt(haus):
    haus.fordere(haus.kontiert(rechnung()), "ben")
    haus.rufe("admin", "DELETE", f"/personen/{haus.p['ben']}", erwarte=409)


def test_gutschrift_muss_nicht_bezahlt_werden(haus):
    nummer = haus.kontiert(rechnung("GS-1", titel="GUTSCHRIFT", ziel=None))
    haus.sofort(nummer)
    with haus.db() as db:
        assert db.get(Beleg, nummer).zahlstatus == "keine"


def test_regel_gilt_nur_wenn_aktiv(haus):
    regel(haus, "freigeben")
    with haus.db() as db:
        db.query(Automatik).one().aktiv = False
        db.commit()
    haus.frei(rechnung("PM-1"))
    haus.frei(rechnung("PM-2"))
    assert haus.beleg(haus.lade(rechnung("PM-3")))["status"] == "neu"
