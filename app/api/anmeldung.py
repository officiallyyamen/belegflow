from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, select

from ..config import einstellungen
from ..dienste.fehler import Ungueltig
from ..dienste.pruefung import iban_gueltig
from ..dienste.werte import als_kennung
from ..modelle import Benutzer, Mandant, Mitglied, Sitzung
from ..sicherheit import COOKIE, Db, Ich, abmelden, anmelden, passwort_hash, passwort_stimmt, token_hash
from .gemeinsam import Eingabe, auszug, zeichen

router = APIRouter(prefix="/api", tags=["Anmeldung"])
PROFIL = ("id", "name", "email", "iban", "abwesend_von", "abwesend_bis", "vertretung_id")


class Anmeldung(Eingabe):
    email: zeichen(200, 3)
    passwort: Annotated[str, Field(min_length=1, max_length=200)]


class Profil(Eingabe):
    iban: zeichen(40) | None = None
    abwesend_von: date | None = None
    abwesend_bis: date | None = None
    vertretung_id: int | None = None


class Passwort(Eingabe):
    alt: Annotated[str, Field(min_length=1, max_length=200)]
    neu: Annotated[str, Field(min_length=12, max_length=200)]


def profil(db: Db, benutzer: Benutzer) -> dict:
    zeilen = db.execute(
        select(Mandant, Mitglied.rollen)
        .join(Mitglied, Mitglied.mandant_id == Mandant.id)
        .where(Mitglied.benutzer_id == benutzer.id)
        .order_by(Mandant.name)
    )
    return auszug(benutzer, *PROFIL) | {
        "mandanten": [{"id": m.id, "name": m.name, "rollen": rollen} for m, rollen in zeilen],
    }


@router.post("/anmeldung")
def anmeldung(eingabe: Anmeldung, anfrage: Request, antwort: Response, db: Db):
    if anfrage.headers.get("x-belegflow") != "1":
        raise HTTPException(403, "Anfrage wurde nicht von der Anwendung gestellt")
    adresse = anfrage.client.host if anfrage.client else ""
    benutzer, token = anmelden(db, eingabe.email, eingabe.passwort, adresse)
    antwort.set_cookie(
        COOKIE,
        token,
        max_age=einstellungen().sitzung_stunden * 3600,
        httponly=True,
        secure=einstellungen().sichere_cookies,
        samesite="strict",
    )
    return profil(db, benutzer)


@router.delete("/anmeldung", status_code=204)
def abmeldung(anfrage: Request, antwort: Response, db: Db, _: Ich):
    abmelden(db, anfrage.cookies.get(COOKIE))
    antwort.delete_cookie(COOKIE)


@router.get("/ich")
def ich(db: Db, benutzer: Ich):
    return profil(db, benutzer)


@router.patch("/ich")
def profil_aendern(eingabe: Profil, db: Db, benutzer: Ich):
    werte = eingabe.model_dump(exclude_unset=True)
    if werte.get("iban"):
        werte["iban"] = als_kennung(werte["iban"], 40)
        if not werte["iban"] or not iban_gueltig(werte["iban"]):
            raise Ungueltig("IBAN ist ungültig")
    if werte.get("vertretung_id"):
        meine = select(Mitglied.mandant_id).where(Mitglied.benutzer_id == benutzer.id)
        bekannt = db.scalar(
            select(Mitglied.benutzer_id).where(
                Mitglied.benutzer_id == werte["vertretung_id"], Mitglied.mandant_id.in_(meine)
            )
        )
        if not bekannt or werte["vertretung_id"] == benutzer.id:
            raise Ungueltig("Diese Person kann nicht vertreten")
    for feld, wert in werte.items():
        setattr(benutzer, feld, wert or None)
    von, bis = benutzer.abwesend_von, benutzer.abwesend_bis
    if von and bis and bis < von:
        db.rollback()
        raise Ungueltig("Ende der Abwesenheit liegt vor dem Beginn")
    if von and not benutzer.vertretung_id:
        db.rollback()
        raise Ungueltig("Bitte eine Vertretung wählen")
    db.commit()
    return profil(db, benutzer)


@router.post("/ich/passwort", status_code=204)
def passwort_aendern(eingabe: Passwort, anfrage: Request, db: Db, benutzer: Ich):
    if not passwort_stimmt(eingabe.alt, benutzer.passwort):
        raise HTTPException(403, "Das bisherige Passwort ist falsch")
    benutzer.passwort = passwort_hash(eingabe.neu)
    jetzige = token_hash(anfrage.cookies[COOKIE])
    db.execute(delete(Sitzung).where(Sitzung.benutzer_id == benutzer.id, Sitzung.token_hash != jetzige))
    db.commit()
