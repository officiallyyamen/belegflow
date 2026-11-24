from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field
from sqlalchemy import select

from ..dienste import zahlung
from ..modelle import Zahlung
from ..sicherheit import Buchhaltung, Leitung
from .gemeinsam import KOPF, Eingabe, auszug, einfach

router = APIRouter(prefix="/api/m/{mandant_id}/zahlungen", tags=["Zahlungen"])


class Posten(Eingabe):
    art: Literal["beleg", "erstattung"]
    id: int
    skonto: bool = False


class Lauf(Eingabe):
    posten: Annotated[list[Posten], Field(min_length=1, max_length=200)]
    ausfuehrung: date


def ausgabe(lauf: Zahlung) -> dict:
    return auszug(lauf, "id", "von", "ausfuehrung", "summe", "erstellt_am", "posten")


@router.get("/offen")
def offen(k: Leitung):
    return einfach(zahlung.offene(k))


@router.get("")
def liste(k: Leitung):
    laeufe = k.db.scalars(select(Zahlung).where(Zahlung.mandant_id == k.mandant.id).order_by(Zahlung.id.desc()).limit(100))
    return [ausgabe(lauf) for lauf in laeufe]


@router.post("", status_code=201)
def anlegen(eingabe: Lauf, k: Buchhaltung):
    return ausgabe(zahlung.zahle(k, [p.model_dump() for p in eingabe.posten], eingabe.ausfuehrung))


@router.get("/{nummer}/datei")
def datei(nummer: int, k: Leitung):
    lauf = zahlung.hole(k, nummer)
    kopf = KOPF | {"Content-Disposition": f'attachment; filename="zahlung_{lauf.id}.xml"'}
    return Response(lauf.xml, media_type="application/xml", headers=kopf)
