from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from ..dienste import belege, karten
from ..dienste.fehler import Verboten
from ..dienste.protokoll import verlauf
from ..modelle import Beleg, Benutzer, Karte, Transaktion
from ..sicherheit import Buchhaltung, Kontext, Mitglieder
from .gemeinsam import Begruendung, Datei, Eingabe, Geld, auszug, lies_datei, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}", tags=["Karten"])


class Neu(Eingabe):
    name: zeichen(80, 2)
    art: Literal["virtuell", "physisch", "einmalig"] = "virtuell"
    inhaber_id: int | None = None
    letzte4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None
    limit_monat: Geld
    limit_zahlung: Geld | None = None
    gueltig_bis: date | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    grund: zeichen(300) = ""


class Aenderung(Eingabe):
    name: zeichen(80, 2) | None = None
    status: Literal["aktiv", "gesperrt", "abgelehnt"] | None = None
    letzte4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None
    limit_monat: Geld | None = None
    limit_zahlung: Geld | None = None
    gueltig_bis: date | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None


class Zuordnung(Eingabe):
    beleg_id: int


def transaktion_aus(k: Kontext, t: Transaktion) -> dict:
    karte = k.db.get(Karte, t.karte_id)
    beleg = k.db.get(Beleg, t.beleg_id) if t.beleg_id else None
    ergebnis = auszug(t, "id", "datum", "haendler", "betrag", "waehrung", "status", "beleg_id") | {
        "karte": karte.name,
        "letzte4": karte.letzte4,
        "inhaber": k.db.get(Benutzer, karte.inhaber_id).name,
        "beleg": auszug(beleg, "id", "lieferant", "nummer", "status") if beleg else None,
        "hinweise": karten.hinweise(k, t),
        "vorschlaege": [],
    }
    if t.status == "fehlt":
        ergebnis["vorschlaege"] = [
            auszug(b, "id", "lieferant", "nummer", "datum", "brutto") | {"sicher": sicher}
            for b, sicher in karten.vorschlaege(k, t)[:4]
        ]
    return ergebnis


@router.get("/karten")
def liste(k: Mitglieder):
    return [karten.ausgabe(k, karte) for karte in karten.alle(k)]


@router.post("/karten", status_code=201)
def anlegen(eingabe: Neu, k: Mitglieder):
    if not k.hat("mitarbeit", "buchhaltung", "freigabe", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    return karten.ausgabe(k, karten.anlegen(k, eingabe.model_dump()))


@router.get("/karten/{nummer}")
def einzeln(nummer: int, k: Mitglieder):
    karte = karten.hole(k, nummer)
    return karten.ausgabe(k, karte) | {"verlauf": verlauf(k.db, "karte", karte.id)}


@router.patch("/karten/{nummer}")
def aendern(nummer: int, eingabe: Aenderung, k: Buchhaltung):
    karte = karten.hole(k, nummer)
    werte = eingabe.model_dump(exclude_unset=True)
    for name in ("name", "status", "limit_monat"):
        if name in werte and not werte[name]:
            del werte[name]
    karten.aendern(k, karte, werte)
    return karten.ausgabe(k, karte)


@router.get("/transaktionen")
def transaktionen(
    k: Mitglieder, status: Literal["fehlt", "zugeordnet", "ohne_beleg"] | None = None, karte: int | None = None
):
    bedingungen = [Transaktion.mandant_id == k.mandant.id, *karten.sichtfilter(k)]
    if status:
        bedingungen.append(Transaktion.status == status)
    if karte:
        bedingungen.append(Transaktion.karte_id == karte)
    zeilen = k.db.scalars(
        select(Transaktion)
        .join(Karte, Karte.id == Transaktion.karte_id)
        .where(*bedingungen)
        .order_by(Transaktion.datum.desc(), Transaktion.id.desc())
        .limit(200)
    )
    return [transaktion_aus(k, t) for t in zeilen]


@router.post("/transaktionen/import", status_code=201)
def importieren(datei: Datei, k: Buchhaltung):
    return karten.importiere(k, lies_datei(datei)[1])


@router.post("/transaktionen/{nummer}/beleg")
def zuordnen(nummer: int, eingabe: Zuordnung, k: Mitglieder):
    transaktion = karten.hole_transaktion(k, nummer)
    karten.zuordnen(k, transaktion, belege.hole(k, eingabe.beleg_id))
    return transaktion_aus(k, transaktion)


@router.post("/transaktionen/{nummer}/datei", status_code=201)
def hochladen(nummer: int, datei: Datei, k: Mitglieder):
    transaktion = karten.hole_transaktion(k, nummer)
    name, inhalt = lies_datei(datei)
    beleg = belege.nimm_auf(k, name, inhalt, "karte", "rechnung")
    karten.zuordnen(k, transaktion, beleg)
    return transaktion_aus(k, transaktion)


@router.delete("/transaktionen/{nummer}/beleg")
def loesen(nummer: int, k: Buchhaltung):
    transaktion = karten.hole_transaktion(k, nummer)
    karten.loese(k, transaktion)
    return transaktion_aus(k, transaktion)


@router.post("/transaktionen/{nummer}/ohne-beleg")
def ohne_beleg(nummer: int, eingabe: Begruendung, k: Mitglieder):
    transaktion = karten.hole_transaktion(k, nummer)
    karten.ohne_beleg(k, transaktion, eingabe.grund)
    return transaktion_aus(k, transaktion)
