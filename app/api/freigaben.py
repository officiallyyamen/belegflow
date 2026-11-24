from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field

from ..dienste import anforderung, belege, erstattung, freigabe, listen
from ..dienste.fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from ..modelle import Anforderung, Erstattung
from ..sicherheit import Kontext, Mitglieder
from . import belege as beleg_api
from .gemeinsam import Eingabe, Grund, MitGrund, auszug, person, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}/freigaben", tags=["Freigaben"])
ObjektArt = Literal["beleg", "erstattung", "anforderung"]
HOLEN = {"beleg": belege.hole, "erstattung": erstattung.hole, "anforderung": anforderung.hole}


class Schritt(Eingabe):
    art: Literal["person", "team"]
    id: int


class Anfrage(Eingabe):
    ziele: Annotated[list[Schritt], Field(max_length=6)] = []
    workflow_id: int | None = None
    grund: zeichen(500) | None = None


class Entscheidung(Eingabe):
    ja: bool
    grund: zeichen(500) | None = None


class Eintrag(Eingabe):
    art: ObjektArt
    id: int


class SammelEntscheidung(Eingabe):
    eintraege: Annotated[list[Eintrag], Field(min_length=1, max_length=50)]


def zeile(k: Kontext, art: str, objekt, schritte) -> dict:
    ergebnis = {
        "objekt_art": art,
        "id": objekt.id,
        "status": objekt.status,
        "erstellt_am": objekt.erstellt_am.isoformat(),
        "kann": beleg_api.kann_entscheiden(k, art, objekt),
        "angefragt_von": person(k.db, schritte[0].angefragt_von) if schritte else None,
        "angefragt_am": schritte[0].erstellt_am.isoformat() if schritte else None,
        "freigabe": freigabe.als_liste(k.db, art, objekt.id),
    }
    if art == "beleg":
        return ergebnis | {"beleg": beleg_api.kurz(k, objekt, listen.anmerkungen(k, [objekt.id]))}
    if isinstance(objekt, Erstattung):
        daten = {"titel": objekt.titel, "person": person(k.db, objekt.benutzer_id), "summe": str(erstattung.summe(objekt))}
        return ergebnis | daten | auszug(objekt, "kostenstelle", "hinweis")
    if isinstance(objekt, Anforderung):
        daten = {"person": person(k.db, objekt.benutzer_id), "summe": str(objekt.netto)}
        return (
            ergebnis | daten | auszug(objekt, "titel", "lieferant", "kostenstelle", "leistung_am", "nummer", "beschreibung")
        )
    return ergebnis


@router.get("")
def liste(k: Mitglieder, art: ObjektArt = "beleg", sicht: Literal["meine", "angefragt", "alle"] = "meine"):
    if sicht == "alle" and not k.sieht_alles:
        raise Verboten("Dafür fehlt die Berechtigung")
    return [zeile(k, art, objekt, schritte) for objekt, schritte in listen.freigaben(k, art, sicht)]


def darf_anfordern(k: Kontext, art: str, objekt) -> None:
    eigene = art == "anforderung" and objekt.benutzer_id == k.id
    if not eigene and not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf eine Freigabe anfordern")


@router.post("/{art}/{nummer}/anfordern", status_code=204)
def anfordern(art: ObjektArt, nummer: int, eingabe: Anfrage, k: Mitglieder):
    objekt = HOLEN[art](k, nummer)
    darf_anfordern(k, art, objekt)
    if eingabe.ziele:
        freigabe.anfordern(k, art, objekt, [z.model_dump() for z in eingabe.ziele], eingabe.grund)
    else:
        workflow = freigabe.waehle_workflow(k, art, objekt, eingabe.workflow_id)
        freigabe.anfordern(k, art, objekt, workflow.schritte, eingabe.grund, workflow.name)
    k.db.commit()


@router.post("/{art}/{nummer}/sofort", status_code=204)
def sofort(art: ObjektArt, nummer: int, eingabe: MitGrund, k: Mitglieder):
    freigabe.sofort(k, art, HOLEN[art](k, nummer), eingabe.grund)
    k.db.commit()


@router.post("/{art}/{nummer}/entscheidung", status_code=204)
def entscheiden(art: ObjektArt, nummer: int, eingabe: Entscheidung, k: Mitglieder):
    freigabe.entscheiden(k, art, HOLEN[art](k, nummer), eingabe.ja, eingabe.grund)
    k.db.commit()


@router.post("/sammel")
def sammel(eingabe: SammelEntscheidung, k: Mitglieder):
    fertig, fehler = [], []
    for eintrag in eingabe.eintraege:
        try:
            freigabe.entscheiden(k, eintrag.art, HOLEN[eintrag.art](k, eintrag.id), True)
            k.db.commit()
            fertig.append(eintrag.id)
        except (Konflikt, Ungueltig, Verboten, NichtGefunden) as grund:
            k.db.rollback()
            fehler.append({"id": eintrag.id, "grund": str(grund)})
    return {"fertig": fertig, "fehler": fehler}


@router.post("/{art}/{nummer}/zurueckziehen", status_code=204)
def zurueckziehen(art: ObjektArt, nummer: int, k: Mitglieder):
    freigabe.zurueckziehen(k, art, HOLEN[art](k, nummer))
    k.db.commit()


@router.post("/{art}/{nummer}/oeffnen", status_code=204)
def oeffnen(art: ObjektArt, nummer: int, k: Mitglieder):
    objekt = HOLEN[art](k, nummer)
    darf_anfordern(k, art, objekt)
    freigabe.wieder_oeffnen(k, art, objekt)
    k.db.commit()


class Weiterleitung(Eingabe):
    ziel: Schritt
    grund: Grund


@router.post("/{art}/{nummer}/weiterleiten", status_code=204)
def weiterleiten(art: ObjektArt, nummer: int, eingabe: Weiterleitung, k: Mitglieder):
    freigabe.weiterleiten(k, art, HOLEN[art](k, nummer), eingabe.ziel.model_dump(), eingabe.grund)
    k.db.commit()
