from datetime import date, timedelta

import pytest

from app.modelle import Benutzer, Sitzung, jetzt
from app.sicherheit import COOKIE, VERSUCHE

from .conftest import PASSWORT


def anmelden(client, email="anna@test.example", passwort=PASSWORT, kopf=None):
    kopf = {"X-Belegflow": "1"} if kopf is None else kopf
    return client.post("/api/anmeldung", json={"email": email, "passwort": passwort}, headers=kopf)


def test_anmelden_setzt_sicheres_cookie(haus):
    antwort = anmelden(haus.client, " Anna@Test.example ")
    assert antwort.status_code == 200
    assert antwort.json()["mandanten"][0]["rollen"] == ["buchhaltung"]
    cookie = antwort.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert haus.client.get("/api/ich").json()["name"] == "Anna"


def test_passwort_und_hash_stehen_nie_in_antworten(haus):
    antwort = anmelden(haus.client)
    assert "passwort" not in antwort.text and "scrypt" not in antwort.text


@pytest.mark.parametrize("email", ["anna@test.example", "niemand@test.example"])
def test_falsche_anmeldung_verraet_nichts(haus, email):
    antwort = anmelden(haus.client, email, "falsch")
    assert antwort.status_code == 401
    assert antwort.json()["detail"] == "E-Mail oder Passwort ist falsch"


def test_zu_viele_versuche_werden_gebremst(haus):
    for _ in range(VERSUCHE):
        assert anmelden(haus.client, passwort="falsch").status_code == 401
    assert anmelden(haus.client).status_code == 429


def test_abmelden_beendet_die_sitzung(haus):
    anmelden(haus.client)
    assert haus.client.delete("/api/anmeldung", headers={"X-Belegflow": "1"}).status_code == 204
    assert haus.client.get("/api/ich").status_code == 401


def test_aendernde_anfragen_brauchen_den_eigenen_kopf(haus):
    kopf = {"Cookie": f"{COOKIE}={haus.tokens['anna']}"}
    assert haus.client.patch("/api/ich", json={}, headers=kopf).status_code == 403
    assert anmelden(haus.client, kopf={}).status_code == 403


def test_abgelaufene_sitzung_gilt_nicht(haus):
    with haus.db() as db:
        for sitzung in db.query(Sitzung):
            sitzung.laeuft_ab = jetzt() - timedelta(seconds=1)
        db.commit()
    assert haus.rufe("anna", "GET", "/api/ich").status_code == 401


def test_gesperrte_person_kommt_nicht_hinein(haus):
    with haus.db() as db:
        db.get(Benutzer, haus.p["anna"]).aktiv = False
        db.commit()
    assert haus.rufe("anna", "GET", "/api/ich").status_code == 401
    assert anmelden(haus.client).status_code == 401


def test_passwort_wechsel_beendet_andere_sitzungen(haus):
    anmelden(haus.client)
    neu = {"alt": PASSWORT, "neu": "Ganz-Neues-Passwort"}
    assert haus.client.post("/api/ich/passwort", json=neu | {"alt": "x"}, headers={"X-Belegflow": "1"}).status_code == 403
    assert haus.client.post("/api/ich/passwort", json=neu, headers={"X-Belegflow": "1"}).status_code == 204
    assert haus.client.get("/api/ich").status_code == 200
    haus.client.cookies.clear()
    assert haus.rufe("anna", "GET", "/api/ich").status_code == 401


def test_profil(haus):
    morgen = (date.today() + timedelta(days=1)).isoformat()
    daten = {"abwesend_von": date.today().isoformat(), "abwesend_bis": morgen, "vertretung_id": haus.p["ben"]}
    assert haus.rufe("anna", "PATCH", "/api/ich", erwarte=200, json=daten).json()["vertretung_id"] == haus.p["ben"]
    haus.rufe("anna", "PATCH", "/api/ich", erwarte=422, json={"iban": "AT00"})
    haus.rufe("anna", "PATCH", "/api/ich", erwarte=422, json={"vertretung_id": haus.p["boris"]})
    haus.rufe("anna", "PATCH", "/api/ich", erwarte=422, json={"vertretung_id": haus.p["anna"]})
    haus.rufe("anna", "PATCH", "/api/ich", erwarte=422, json={"abwesend_bis": "2020-01-01"})


def test_ohne_anmeldung_geht_nichts(client, haus):
    offen = {"/status", "/api/anmeldung"}
    for pfad, arten in client.app.openapi()["paths"].items():
        if pfad in offen:
            continue
        for methode in arten:
            adresse = pfad.replace("{mandant_id}", str(haus.m["a"]))
            for name in ("nummer", "posten", "ziel"):
                adresse = adresse.replace(f"{{{name}}}", "1")
            adresse = adresse.replace("{art}", "beleg")
            antwort = client.request(methode, adresse)
            assert antwort.status_code == 401, f"{methode} {pfad}: {antwort.status_code}"


def test_kopfzeilen(client):
    antwort = client.get("/")
    assert "default-src 'self'" in antwort.headers["content-security-policy"]
    assert antwort.headers["cache-control"] == "no-cache"
    assert client.get("/status").headers["cache-control"] == "no-store"
    assert client.get("/status?x=%00").status_code == 422
