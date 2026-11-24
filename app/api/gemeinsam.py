from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, model_validator
from sqlalchemy.orm import Session

from ..config import einstellungen
from ..dienste import dateien
from ..dienste.werte import als_betrag
from ..modelle import Benutzer, Partner


def enthaelt_null(wert) -> bool:
    if isinstance(wert, str):
        return "\x00" in wert
    if isinstance(wert, dict):
        return any(enthaelt_null(k) or enthaelt_null(v) for k, v in wert.items())
    if isinstance(wert, list):
        return any(enthaelt_null(v) for v in wert)
    return False


def betrag(wert) -> Decimal:
    zahl = als_betrag(str(wert).replace(" ", "").replace(",", "."))
    if zahl is None:
        raise ValueError("Betrag ist ungültig")
    return zahl


class Eingabe(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def ohne_nullzeichen(cls, werte):
        if enthaelt_null(werte):
            raise ValueError("Zeichen ist nicht erlaubt")
        return werte


def zeichen(hoechstens: int, mindestens: int = 0):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=mindestens, max_length=hoechstens)]


Geld = Annotated[Decimal, BeforeValidator(betrag)]
Grund = zeichen(500, 3)
Nummer = Annotated[int, Query(ge=1)]
Grenze = Annotated[int, Query(ge=1, le=200)]
Ab = Annotated[int, Query(ge=0)]


class Begruendung(Eingabe):
    grund: Grund


class MitGrund(Eingabe):
    grund: zeichen(500) | None = None


class Kommentar(Eingabe):
    text: zeichen(1000, 1)


def wert(w):
    if isinstance(w, Decimal):
        return str(w)
    if isinstance(w, datetime | date):
        return w.isoformat()
    return w


def auszug(objekt, *namen: str) -> dict:
    return {name: wert(getattr(objekt, name)) for name in namen}


def einfach(daten):
    if isinstance(daten, dict):
        return {k: einfach(v) for k, v in daten.items()}
    if isinstance(daten, list | tuple | set):
        return [einfach(v) for v in daten]
    return wert(daten)


def person(db: Session, nummer: int | None) -> str | None:
    benutzer = db.get(Benutzer, nummer) if nummer else None
    return benutzer.name if benutzer else None


def partnername(db: Session, nummer: int | None) -> str | None:
    partner = db.get(Partner, nummer) if nummer else None
    return partner.name if partner else None


def lies_datei(datei: UploadFile) -> tuple[str, bytes]:
    inhalt = datei.file.read(einstellungen().max_mb * 1024 * 1024 + 1)
    name = (datei.filename or "datei").replace("\x00", "").replace("\\", "/").rsplit("/", 1)[-1]
    return name[:255] or "datei", inhalt


Datei = Annotated[UploadFile, File()]
KOPF = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"}


def datei_antwort(sha256: str, typ: str, name: str, anhang: bool = False):
    pfad = dateien.pfad(sha256, typ)
    if not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    art = "attachment" if anhang or typ == "application/xml" else "inline"
    return FileResponse(pfad, media_type=typ, filename=name, content_disposition_type=art, headers=KOPF)


def bild_antwort(sha256: str, typ: str, seite: int):
    pfad = dateien.pfad(sha256, typ)
    if not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    if typ == "application/pdf":
        inhalt, seiten = dateien.seite_als_png(pfad, seite)
        return Response(inhalt, media_type="image/png", headers=KOPF | {"X-Seiten": str(seiten)})
    if typ == "application/xml":
        raise HTTPException(415, "Für XML gibt es kein Bild")
    return FileResponse(pfad, media_type=typ, headers=KOPF | {"X-Seiten": "1"})


def pdf_antwort(inhalt: bytes, name: str):
    kopf = KOPF | {"Content-Disposition": f'inline; filename="{name}"'}
    return Response(inhalt, media_type="application/pdf", headers=kopf)
