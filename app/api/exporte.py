from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import select

from ..dienste import export
from ..modelle import Export
from ..sicherheit import Buchhaltung, Leitung
from .gemeinsam import Eingabe, auszug, datei_antwort, einfach

router = APIRouter(prefix="/api/m/{mandant_id}/exporte", tags=["Export"])
Periode = Annotated[str, Field(pattern=r"^\d{4}-\d{2}$")]


class Posten(Eingabe):
    art: Literal["beleg", "erstattung"]
    id: int


class Auftrag(Eingabe):
    format: Literal["csv", "bmd", "zip"]
    posten: Annotated[list[Posten], Field(max_length=500)] | None = None


class Abgrenzung(Eingabe):
    periode: Periode


def ausgabe(eintrag: Export) -> dict:
    return auszug(eintrag, "id", "von", "format", "anzahl", "dateiname", "erstellt_am", "posten")


@router.get("/wartend")
def wartend(k: Leitung):
    namen = ("art", "id", "name", "kreditor", "nummer", "datum", "waehrung", "hindernis", "brutto", "zeilen")
    return [einfach({n: b[n] for n in namen}) for b in export.wartende(k)]


@router.get("")
def liste(k: Leitung):
    eintraege = k.db.scalars(select(Export).where(Export.mandant_id == k.mandant.id).order_by(Export.id.desc()).limit(100))
    return [ausgabe(e) for e in eintraege]


@router.post("", status_code=201)
def anlegen(eingabe: Auftrag, k: Buchhaltung):
    posten = [p.model_dump() for p in eingabe.posten] if eingabe.posten else None
    return ausgabe(export.exportiere(k, eingabe.format, posten))


@router.get("/{nummer}/datei")
def datei(nummer: int, k: Leitung):
    eintrag = export.hole(k, nummer)
    typ = "application/zip" if eintrag.format == "zip" else "text/csv"
    return datei_antwort(eintrag.sha256, typ, eintrag.dateiname, anhang=True)


@router.get("/rueckstellungen")
def rueckstellungen(k: Leitung, periode: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]):
    neu = [auszug(b, "id", "lieferant", "nummer", "datum", "netto", "status") for b in export.rueckstellungen(k, periode)]
    zurueck = [
        auszug(b, "id", "lieferant", "nummer", "status") | auszug(r, "periode", "betrag") for r, b in export.aufloesungen(k)
    ]
    return {"neu": neu, "aufloesen": zurueck}


@router.post("/rueckstellungen", status_code=201)
def rueckstellungen_exportieren(eingabe: Abgrenzung, k: Buchhaltung):
    return ausgabe(export.exportiere_rueckstellungen(k, eingabe.periode))


@router.post("/stammdaten", status_code=201)
def stammdaten(k: Buchhaltung):
    return ausgabe(export.exportiere_stammdaten(k))
