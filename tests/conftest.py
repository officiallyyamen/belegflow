import json
import os

import pytest
from fastapi.testclient import TestClient

from app.config import einstellungen
from app.db import Basis, sitzungen
from demo.erzeuge_belege import beleg

BENUTZER = {
    "t-eingang": {"name": "n8n", "rollen": ["eingang"]},
    "t-anna": {"name": "Anna", "rollen": ["buchhaltung"]},
    "t-ben": {"name": "Ben", "rollen": ["freigabe"]},
    "t-chef": {"name": "Chef", "rollen": ["buchhaltung", "freigabe"]},
}
LIEFERANT = ("Papier Muster GmbH", "ATU12345675", "AT61 1904 3002 3457 3201")


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATENBANK_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("BELEGFLOW_DATENBANK_URL", url)
    monkeypatch.setenv("BELEGFLOW_SPEICHER", str(tmp_path / "belege"))
    monkeypatch.setenv("BELEGFLOW_BENUTZER", json.dumps(BENUTZER))
    monkeypatch.setenv("BELEGFLOW_EXTRAKTOR", "regeln")
    einstellungen.cache_clear()
    sitzungen.cache_clear()
    from app.main import app

    with TestClient(app) as verbindung:
        yield verbindung
    engine = sitzungen().kw["bind"]
    Basis.metadata.drop_all(engine)
    engine.dispose()
    einstellungen.cache_clear()
    sitzungen.cache_clear()


@pytest.fixture
def rufe(client):
    def anfrage(methode, pfad, token="t-anna", **argumente):
        return client.request(methode, pfad, headers={"Authorization": f"Bearer {token}"}, **argumente)

    return anfrage


@pytest.fixture
def pdf(tmp_path):
    def erzeuge(nummer="PM-1", netto=500.0, satz=20, lieferant=LIEFERANT, **argumente):
        pfad = tmp_path / f"{nummer}.pdf"
        beleg(pfad, *lieferant, nummer, [("Ware", netto, satz)], **argumente)
        return pfad.read_bytes()

    return erzeuge


@pytest.fixture
def lade(rufe):
    def hoch(inhalt, token="t-eingang", name="rechnung.pdf"):
        return rufe("POST", "/belege", token, files={"datei": (name, inhalt, "application/pdf")})

    return hoch


@pytest.fixture
def freigegeben(rufe, lade, pdf):
    def erzeuge(nummer="PM-1", **argumente):
        nummer_beleg = lade(pdf(nummer, **argumente)).json()["id"]
        rufe("PATCH", f"/belege/{nummer_beleg}", json={"konto": "7600", "kostenstelle": "100"})
        antwort = rufe("POST", f"/belege/{nummer_beleg}/freigabe", "t-ben")
        assert antwort.status_code == 200, antwort.text
        return nummer_beleg

    return erzeuge
