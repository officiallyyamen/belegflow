import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import einstellungen
from .db import datenbank
from .modelle import Anmeldeversuch, Benutzer, Mandant, Mitglied, Sitzung, Zugang, jetzt

COOKIE = "belegflow_sitzung"
SICHER = ("GET", "HEAD", "OPTIONS")
ALLE_ROLLEN = ("admin", "buchhaltung", "freigabe", "mitarbeit", "einsicht")
ZUGANGSROLLEN = ("eingang", "schnittstelle")
VERSUCHE = 8
FENSTER = timedelta(minutes=15)

Db = Annotated[Session, Depends(datenbank)]


def ableiten(passwort: str, salz: bytes) -> bytes:
    return hashlib.scrypt(passwort.encode(), salt=salz, n=2**14, r=8, p=1)


def passwort_hash(passwort: str) -> str:
    salz = os.urandom(16)
    return f"scrypt${salz.hex()}${ableiten(passwort, salz).hex()}"


def passwort_stimmt(passwort: str, gespeichert: str) -> bool:
    _, salz, wert = gespeichert.split("$")
    return hmac.compare_digest(ableiten(passwort, bytes.fromhex(salz)).hex(), wert)


PLATZHALTER = passwort_hash(secrets.token_hex(16))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def anmelden(db: Session, email: str, passwort: str, adresse: str) -> tuple[Benutzer, str]:
    email = email.strip().lower()
    schluessel = f"{email}|{adresse}"[:250]
    db.execute(delete(Anmeldeversuch).where(Anmeldeversuch.zeitpunkt < jetzt() - FENSTER))
    versuche = db.scalar(select(func.count()).select_from(Anmeldeversuch).where(Anmeldeversuch.schluessel == schluessel))
    if versuche >= VERSUCHE:
        db.commit()
        raise HTTPException(429, "Zu viele Versuche. Bitte in 15 Minuten noch einmal probieren.")
    benutzer = db.scalar(select(Benutzer).where(Benutzer.email == email))
    stimmt = passwort_stimmt(passwort, benutzer.passwort if benutzer else PLATZHALTER)
    if not (benutzer and benutzer.aktiv and stimmt):
        db.add(Anmeldeversuch(schluessel=schluessel))
        db.commit()
        raise HTTPException(401, "E-Mail oder Passwort ist falsch")
    db.execute(delete(Anmeldeversuch).where(Anmeldeversuch.schluessel == schluessel))
    db.execute(delete(Sitzung).where(Sitzung.laeuft_ab < jetzt()))
    token = secrets.token_urlsafe(32)
    ablauf = jetzt() + timedelta(hours=einstellungen().sitzung_stunden)
    db.add(Sitzung(benutzer_id=benutzer.id, token_hash=token_hash(token), laeuft_ab=ablauf))
    db.commit()
    return benutzer, token


def abmelden(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(Sitzung).where(Sitzung.token_hash == token_hash(token)))
        db.commit()


def aus_cookie(anfrage: Request, db: Session) -> Benutzer | None:
    token = anfrage.cookies.get(COOKIE)
    if not token:
        return None
    sitzung = db.scalar(select(Sitzung).where(Sitzung.token_hash == token_hash(token)))
    if not sitzung or sitzung.laeuft_ab < jetzt():
        return None
    benutzer = db.get(Benutzer, sitzung.benutzer_id)
    if not benutzer.aktiv:
        return None
    if anfrage.method not in SICHER and anfrage.headers.get("x-belegflow") != "1":
        raise HTTPException(403, "Anfrage wurde nicht von der Anwendung gestellt")
    return benutzer


def angemeldet(anfrage: Request, db: Db) -> Benutzer:
    benutzer = aus_cookie(anfrage, db)
    if not benutzer:
        raise HTTPException(401, "Bitte anmelden")
    return benutzer


Ich = Annotated[Benutzer, Depends(angemeldet)]


@dataclass
class Kontext:
    db: Session
    mandant: Mandant
    name: str
    rollen: set[str] = field(default_factory=set)
    benutzer: Benutzer | None = None

    def hat(self, *rollen: str) -> bool:
        return bool(self.rollen & set(rollen))

    @property
    def sieht_alles(self) -> bool:
        return self.hat("admin", "buchhaltung", "einsicht", "schnittstelle")

    @property
    def id(self) -> int | None:
        return self.benutzer.id if self.benutzer else None


def kontext_aus(db: Session, benutzer: Benutzer, mandant_id: int) -> Kontext | None:
    mitglied = db.get(Mitglied, (mandant_id, benutzer.id))
    if not mitglied:
        return None
    return Kontext(db, db.get(Mandant, mandant_id), benutzer.name, set(mitglied.rollen), benutzer)


def kontext(*erlaubt: str):
    def pruefe(mandant_id: int, anfrage: Request, db: Db) -> Kontext:
        kopf = anfrage.headers.get("authorization", "")
        if kopf.lower().startswith("bearer "):
            zugang = db.scalar(select(Zugang).where(Zugang.token_hash == token_hash(kopf[7:].strip())))
            if not zugang:
                raise HTTPException(401, "Zugang ist ungültig")
            if zugang.mandant_id != mandant_id:
                raise HTTPException(404, "Mandant nicht gefunden")
            k = Kontext(db, db.get(Mandant, mandant_id), zugang.name, set(zugang.rollen))
        else:
            k = kontext_aus(db, angemeldet(anfrage, db), mandant_id)
            if not k:
                raise HTTPException(404, "Mandant nicht gefunden")
        if erlaubt and not k.hat(*erlaubt):
            raise HTTPException(403, "Dafür fehlt die Berechtigung")
        if not erlaubt and not k.benutzer:
            raise HTTPException(403, "Nur für angemeldete Personen")
        return k

    return pruefe


Mitglieder = Annotated[Kontext, Depends(kontext())]
Buchhaltung = Annotated[Kontext, Depends(kontext("buchhaltung", "admin"))]
Verwaltung = Annotated[Kontext, Depends(kontext("admin"))]
Leitung = Annotated[Kontext, Depends(kontext("admin", "buchhaltung", "einsicht"))]
Eingang = Annotated[Kontext, Depends(kontext("eingang"))]
Schnittstelle = Annotated[Kontext, Depends(kontext("schnittstelle"))]
