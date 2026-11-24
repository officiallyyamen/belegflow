import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import einstellungen
from app.db import Basis, sitzungen
from app.demo.dateien import Firma, Posten, Vorlage, iban, pdf, uid
from app.modelle import Benutzer, Mandant, Mitglied, Partner, Sitzung, Stammwert, Zugang, jetzt
from app.sicherheit import COOKIE, kontext_aus, passwort_hash, token_hash

PASSWORT = "Testpasswort-2026"
HASH = passwort_hash(PASSWORT)
EIGEN = Firma("Muster Holding GmbH", "Beispielgasse 5", "1030", "Wien", uid("2222222"), iban(900))
FREMD = Firma("Fremde Firma GmbH", "Anderswo 1", "4020", "Linz", uid("3333333"), iban(901))
PAPIER = Firma("Papier Muster GmbH", "Lagerstraße 1", "1010", "Wien", uid("1234567"), iban(1))
PUTZ = Firma("Reinigung Beispiel KG", "Putzgasse 3", "1120", "Wien", uid("5555555"), iban(2))
PERSONEN = {
    "anna": {"a": ["buchhaltung"]},
    "ben": {"a": ["freigabe"]},
    "cleo": {"a": ["freigabe"]},
    "dora": {"a": ["mitarbeit"]},
    "eva": {"a": ["einsicht"]},
    "admin": {"a": ["admin"]},
    "chef": {"a": ["buchhaltung", "freigabe"]},
    "lea": {"a": ["einsicht", "freigabe"]},
    "boris": {"b": ["admin", "buchhaltung", "freigabe"]},
}


def rechnung(nummer="PM-1", netto="500", satz=20, wer=PAPIER, an=EIGEN, tage=10, posten=None, **mehr) -> Vorlage:
    tag = date.today() - timedelta(days=tage)
    zeilen = posten or [Posten("A-1", "Ware", Decimal(1), "Stk", Decimal(netto), satz)]
    return Vorlage(wer, an, nummer, tag, zeilen, leistung=(tag, tag), **mehr)


class Haus:
    def __init__(self, client):
        self.client = client
        self.m, self.p, self.tokens = {}, {}, {}
        with self.db() as db:
            for kurz, firma in (("a", EIGEN), ("b", FREMD)):
                mandant = Mandant(
                    name=firma.name, strasse=firma.strasse, plz=firma.plz, ort=firma.ort, uid=firma.uid, iban=firma.iban
                )
                mandant.einstellungen = {"vier_augen": True}
                db.add(mandant)
                db.flush()
                self.m[kurz] = mandant.id
                for art, code in (("konto", "7600"), ("konto", "7200"), ("kostenstelle", "100"), ("kostenstelle", "200")):
                    db.add(Stammwert(mandant_id=mandant.id, art=art, code=code, name=f"Name {code}"))
            for kurz, mitglied in PERSONEN.items():
                person = Benutzer(name=kurz.capitalize(), email=f"{kurz}@test.example", passwort=HASH, iban=iban(700))
                db.add(person)
                db.flush()
                self.p[kurz] = person.id
                self.tokens[kurz] = f"sitzung-{kurz}"
                db.add(
                    Sitzung(
                        benutzer_id=person.id,
                        token_hash=token_hash(f"sitzung-{kurz}"),
                        laeuft_ab=jetzt() + timedelta(hours=1),
                    )
                )
                for mandant, rollen in mitglied.items():
                    db.add(Mitglied(mandant_id=self.m[mandant], benutzer_id=person.id, rollen=rollen))
            for rolle in ("eingang", "schnittstelle"):
                db.add(Zugang(mandant_id=self.m["a"], name=rolle, token_hash=token_hash(f"bf_{rolle}"), rollen=[rolle]))
            db.commit()

    def db(self):
        return sitzungen()()

    def k(self, db, wer, mandant="a"):
        return kontext_aus(db, db.get(Benutzer, self.p[wer]), self.m[mandant])

    def rufe(self, wer, methode, pfad, mandant="a", erwarte=None, **mehr):
        kopf = {"X-Belegflow": "1"} | mehr.pop("headers", {})
        if wer in self.tokens:
            kopf["Cookie"] = f"{COOKIE}={self.tokens[wer]}"
        elif wer:
            kopf["Authorization"] = f"Bearer {wer}"
        adresse = pfad if pfad.startswith("/api") else f"/api/m/{self.m[mandant]}{pfad}"
        antwort = self.client.request(methode, adresse, headers=kopf, **mehr)
        if erwarte:
            assert antwort.status_code == erwarte, antwort.text
        return antwort

    def lade(self, inhalt, wer="anna", name="beleg.pdf", mandant="a", **mehr):
        if isinstance(inhalt, Vorlage):
            inhalt = pdf(inhalt)
        antwort = self.rufe(wer, "POST", "/belege", mandant, 201, files=[("dateien", (name, inhalt))], **mehr)
        eintrag = antwort.json()[0]
        assert "fehler" not in eintrag, eintrag
        return eintrag["id"]

    def beleg(self, nummer, wer="anna", mandant="a"):
        return self.rufe(wer, "GET", f"/belege/{nummer}", mandant, 200).json()

    def aendere(self, beleg, wer="anna", erwarte=200, mandant="a", **werte):
        return self.rufe(wer, "PATCH", f"/belege/{beleg}", mandant, erwarte, json=werte).json()

    def kontiert(self, vorlage, wer="anna", konto="7600", kostenstelle="100", mandant="a"):
        nummer = self.lade(vorlage, wer, mandant=mandant)
        self.aendere(nummer, wer, konto=konto, kostenstelle=kostenstelle, mandant=mandant)
        return nummer

    def sofort(self, nummer, wer="lea", art="beleg", erwarte=204, grund=None, mandant="a"):
        return self.rufe(wer, "POST", f"/freigaben/{art}/{nummer}/sofort", mandant, erwarte, json={"grund": grund})

    def frei(self, vorlage, **mehr):
        nummer = self.kontiert(vorlage, **mehr)
        self.sofort(nummer)
        return nummer

    def fordere(self, nummer, *ziele, wer="anna", art="beleg", erwarte=204, **mehr):
        daten = {"ziele": [{"art": "person", "id": self.p[z]} if isinstance(z, str) else z for z in ziele]} | mehr
        return self.rufe(wer, "POST", f"/freigaben/{art}/{nummer}/anfordern", erwarte=erwarte, json=daten)

    def entscheide(self, wer, nummer, ja=True, grund=None, art="beleg", erwarte=204):
        daten = {"ja": ja, "grund": grund}
        return self.rufe(wer, "POST", f"/freigaben/{art}/{nummer}/entscheidung", erwarte=erwarte, json=daten)

    def partner(self, firma=PAPIER, mandant="a", **mehr):
        with self.db() as db:
            neu = Partner(
                mandant_id=self.m[mandant], name=firma.name, uid=firma.uid, ibans=[firma.iban], kreditor="330001", **mehr
            )
            db.add(neu)
            db.commit()
            return neu.id


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = os.environ.get("TEST_DATENBANK_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("BELEGFLOW_DATENBANK_URL", url)
    monkeypatch.setenv("BELEGFLOW_SPEICHER", str(tmp_path / "belege"))
    monkeypatch.setenv("BELEGFLOW_EXTRAKTOR", "regeln")
    monkeypatch.setenv("BELEGFLOW_WECHSELKURSE", "false")
    einstellungen.cache_clear()
    sitzungen.cache_clear()
    engine = sitzungen().kw["bind"]
    Basis.metadata.create_all(engine)
    from app.main import app

    with TestClient(app, base_url="https://testserver") as verbindung:
        yield verbindung
    Basis.metadata.drop_all(engine)
    engine.dispose()
    einstellungen.cache_clear()
    sitzungen.cache_clear()


@pytest.fixture
def haus(client):
    return Haus(client)
