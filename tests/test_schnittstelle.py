from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.dienste.protokoll import gueltig
from app.modelle import Freigabeschritt, Nachricht, Protokoll, jetzt

from .conftest import pdf, rechnung

KOPF = {"kennung": "<1@x.example>", "absender": "Lift <Rechnung@Lift.example>", "betreff": "Rechnung", "inhalt": "Anbei"}


def sende(haus, vorlage=None, erwarte=201, token="bf_eingang", **mehr):
    dateien = {"datei": ("r.pdf", pdf(vorlage))} if vorlage else None
    return haus.rufe(token, "POST", "/schnittstelle/belege", erwarte=erwarte, data=KOPF | mehr, files=dateien).json()


def test_mail_mit_anhang(haus):
    antwort = sende(haus, rechnung())
    assert (antwort["status"], antwort["stufe"], antwort["brutto"]) == ("erfasst", "ok", "600.00")
    b = haus.beleg(antwort["beleg_id"])
    assert b["quelle"] == "e-mail" and b["nachricht"]["absender"] == "rechnung@lift.example"
    sende(haus, rechnung("PM-2"))
    nachrichten = haus.rufe("anna", "GET", "/nachrichten", erwarte=200).json()
    assert len(nachrichten) == 1 and len(nachrichten[0]["belege"]) == 2


def test_wiederholung_ist_unschaedlich(haus):
    vorlage = rechnung()
    sende(haus, vorlage)
    antwort = sende(haus, vorlage)
    assert antwort["status"] == "warnung" and "bereits erfasst" in antwort["hinweis"]
    assert haus.rufe("anna", "GET", "/eingang").json()["gesamt"] == 1


def test_mail_ohne_anhang(haus):
    assert sende(haus)["status"] == "ohne_beleg"


@pytest.mark.parametrize("wert", ["rechnung@lift.example", "lift.example"])
def test_gesperrter_absender(haus, wert):
    haus.rufe("anna", "POST", "/sperren", erwarte=201, json={"art": "absender", "wert": wert})
    assert sende(haus, rechnung())["status"] == "gesperrt"
    assert haus.rufe("anna", "GET", "/eingang").json()["gesamt"] == 0
    with haus.db() as db:
        assert db.scalar(select(Nachricht)).status == "gesperrt"


def test_probleme_kommen_zurueck(haus):
    antwort = sende(haus, rechnung(falsch=Decimal(10)))
    assert antwort["stufe"] == "sperre" and antwort["probleme"] == ["Netto plus Steuer ergibt nicht den Gesamtbetrag"]


def test_falsche_rolle(haus):
    sende(haus, rechnung(), erwarte=403, token="bf_schnittstelle")
    haus.rufe("bf_eingang", "GET", "/schnittstelle/mitteilungen", erwarte=403)
    haus.rufe("anna", "GET", "/schnittstelle/mitteilungen", erwarte=403)


def test_mitteilungen_abholen(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben")
    liste = haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/mitteilungen", erwarte=200).json()
    assert [(m["email"], m["ziel"]) for m in liste] == [("ben@test.example", f"beleg/{nummer}")]
    daten = {"nummern": [m["id"] for m in liste]}
    haus.rufe("bf_schnittstelle", "POST", "/schnittstelle/mitteilungen/zugestellt", erwarte=204, json=daten)
    assert haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/mitteilungen").json() == []
    assert haus.rufe("ben", "GET", "/mitteilungen").json()[0]["gelesen"] is False


def test_erinnerungen(haus):
    nummer = haus.kontiert(rechnung())
    haus.fordere(nummer, "ben")
    assert haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/erinnerungen").json() == []
    with haus.db() as db:
        db.scalar(select(Freigabeschritt)).erstellt_am = jetzt() - timedelta(days=4)
        db.commit()
    assert haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/erinnerungen").json()[0]["name"] == "Ben"


def test_buchungen_lesen(haus):
    haus.frei(rechnung())
    daten = haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/buchungen", erwarte=200).json()
    assert daten[0]["zeilen"][0]["netto"] == "500.00" and daten[0]["status"] == "freigegeben"


def test_stammdaten_importieren(haus):
    werte = {"werte": [{"art": "konto", "code": "7600", "name": "Büro"}, {"art": "konto", "code": "8888", "name": "Neu"}]}
    assert haus.rufe("bf_schnittstelle", "PUT", "/schnittstelle/stammdaten", erwarte=200, json=werte).json() == {
        "neu": 1,
        "geaendert": 1,
    }
    partner = {"partner": [{"kreditor": "330500", "name": "Papier Muster GmbH", "konto": "7600", "kostenstelle": "100"}]}
    haus.rufe("bf_schnittstelle", "PUT", "/schnittstelle/partner", erwarte=200, json=partner)
    b = haus.beleg(haus.lade(rechnung()))
    assert b["partner"]["kreditor"] == "330500" and b["konto"] == "7600"


def test_personen_importieren_ohne_verwaltungsrechte(haus):
    daten = {
        "personen": [
            {"email": "boris@test.example", "rollen": ["mitarbeit", "admin"]},
            {"email": "dora@test.example", "aktiv": False},
            {"email": "admin@test.example", "aktiv": False},
            {"email": "fehlt@test.example"},
        ]
    }
    antwort = haus.rufe("bf_schnittstelle", "PUT", "/schnittstelle/personen", erwarte=200, json=daten).json()
    assert antwort == {"aufgenommen": 1, "entfernt": 1, "unbekannt": ["fehlt@test.example"]}
    personen = {p["email"]: p["rollen"] for p in haus.rufe("admin", "GET", "/personen").json()}
    assert personen["boris@test.example"] == ["mitarbeit"] and "dora@test.example" not in personen


def test_zugang_anlegen_und_entziehen(haus):
    daten = {"name": "n8n", "rollen": ["eingang"]}
    neu = haus.rufe("admin", "POST", "/zugaenge", erwarte=201, json=daten).json()
    sende(haus, rechnung(), token=neu["token"])
    assert neu["token"] not in haus.rufe("admin", "GET", "/zugaenge").text
    nummer = next(z["id"] for z in neu["zugaenge"] if z["name"] == "n8n")
    haus.rufe("admin", "DELETE", f"/zugaenge/{nummer}", erwarte=200)
    sende(haus, rechnung("PM-2"), token=neu["token"], erwarte=401)


def test_protokoll_bleibt_pruefbar(haus):
    nummer = haus.frei(rechnung())
    assert haus.rufe("eva", "GET", "/protokoll/pruefung", erwarte=200).json() == {"gueltig": True, "fehler_bei": None}
    with haus.db() as db:
        eintrag = db.scalar(select(Protokoll).where(Protokoll.objekt_id == nummer, Protokoll.aktion == "freigegeben"))
        eintrag.wer = "Jemand anderes"
        db.commit()
        assert gueltig(db, haus.m["a"]) == (False, eintrag.id)
        assert gueltig(db, haus.m["b"])[0]
    haus.frei(rechnung("PM-2"))
    with haus.db() as db:
        db.delete(db.scalar(select(Protokoll).where(Protokoll.mandant_id == haus.m["a"]).order_by(Protokoll.id)))
        db.commit()
        assert not gueltig(db, haus.m["a"])[0]


def test_protokoll_filtern(haus):
    haus.lade(rechnung())
    daten = haus.rufe("eva", "GET", "/protokoll?wer=Anna", erwarte=200).json()
    assert daten and {e["wer"] for e in daten} == {"Anna"}
    erste = haus.rufe("eva", "GET", "/protokoll?grenze=1").json()[0]["id"]
    assert all(e["id"] < erste for e in haus.rufe("eva", "GET", f"/protokoll?vor={erste}").json())
