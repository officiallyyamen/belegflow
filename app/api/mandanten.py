from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import select, update

from ..config import einstellungen
from ..dienste import auswertung, freigabe, listen, reisekosten
from ..dienste.fehler import Konflikt
from ..modelle import Beleg as BelegZeile
from ..modelle import Benutzer, Mandant, Mitglied, Mitteilung, Partner, Schlagwort, Stammwert, Team, Workflow
from ..sicherheit import Db, Ich, Kontext, Mitglieder, kontext_aus
from . import belege as beleg_api
from .gemeinsam import Eingabe, auszug, einfach, zeichen

router = APIRouter(prefix="/api", tags=["Mandanten"])


@router.get("/mandanten")
def mandanten(db: Db, benutzer: Ich):
    ergebnis = []
    for nummer in db.scalars(select(Mitglied.mandant_id).where(Mitglied.benutzer_id == benutzer.id)):
        k = kontext_aus(db, benutzer, nummer)
        ergebnis.append({"id": nummer, "name": k.mandant.name, "rollen": sorted(k.rollen), "zaehler": auswertung.zaehler(k)})
    return sorted(ergebnis, key=lambda m: m["name"].lower())


class NeuerMandant(Eingabe):
    name: zeichen(200, 2)


@router.post("/mandanten", status_code=201)
def anlegen(eingabe: NeuerMandant, db: Db, benutzer: Ich):
    verwaltet = any("admin" in m.rollen for m in db.scalars(select(Mitglied).where(Mitglied.benutzer_id == benutzer.id)))
    if not verwaltet:
        raise Konflikt("Neue Mandanten darf nur die Verwaltung anlegen")
    mandant = Mandant(name=eingabe.name, einstellungen={"vier_augen": True})
    db.add(mandant)
    db.flush()
    db.add(Mitglied(mandant_id=mandant.id, benutzer_id=benutzer.id, rollen=["admin", "buchhaltung"]))
    db.commit()
    return {"id": mandant.id, "name": mandant.name}


@router.get("/m/{mandant_id}/zaehler")
def zaehler(k: Mitglieder):
    return auswertung.zaehler(k)


@router.get("/m/{mandant_id}/uebersicht")
def uebersicht(
    k: Mitglieder,
    jahr: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    basis: Literal["brutto", "netto"] = "brutto",
    nach: Literal["kostenstelle", "konto", "partner"] = "kostenstelle",
):
    return einfach(auswertung.uebersicht(k, jahr or date.today().year, basis, nach))


def personen(k: Kontext) -> list[dict]:
    zeilen = k.db.execute(
        select(Benutzer, Mitglied.rollen)
        .join(Mitglied, Mitglied.benutzer_id == Benutzer.id)
        .where(Mitglied.mandant_id == k.mandant.id, Benutzer.aktiv.is_(True))
        .order_by(Benutzer.name)
    )
    return [{"id": b.id, "name": b.name, "rollen": rollen, "abwesend": freigabe.abwesend(b)} for b, rollen in zeilen]


@router.get("/m/{mandant_id}/stammdaten")
def stammdaten(k: Mitglieder):
    db, mandant = k.db, k.mandant
    werte: dict[str, list] = {}
    for eintrag in db.scalars(
        select(Stammwert).where(Stammwert.mandant_id == mandant.id).order_by(Stammwert.art, Stammwert.code)
    ):
        werte.setdefault(eintrag.art, []).append(auszug(eintrag, "code", "name"))
    ergebnis = {
        "mandant": auszug(mandant, "id", "name", "strasse", "plz", "ort", "land", "uid"),
        "rollen": sorted(k.rollen),
        "vier_augen": mandant.einstellungen.get("vier_augen", True),
        "personen": personen(k),
        "teams": [
            auszug(t, "id", "name", "mitglieder")
            for t in db.scalars(select(Team).where(Team.mandant_id == mandant.id).order_by(Team.name))
        ],
        "workflows": [
            auszug(w, "id", "name")
            for w in db.scalars(select(Workflow).where(Workflow.mandant_id == mandant.id).order_by(Workflow.rang))
        ],
        "werte": werte,
        "steuersaetze": einstellungen().steuersaetze,
        "laender": reisekosten.laender(),
    }
    if k.sieht_alles:
        ergebnis["partner"] = [
            auszug(p, "id", "name", "uid", "konto", "kostenstelle")
            for p in db.scalars(select(Partner).where(Partner.mandant_id == mandant.id).order_by(Partner.name))
        ]
        ergebnis["schlagwoerter"] = sorted(
            set(
                db.scalars(
                    select(Schlagwort.name)
                    .join(BelegZeile, BelegZeile.id == Schlagwort.beleg_id)
                    .where(BelegZeile.mandant_id == mandant.id)
                )
            )
        )
    return ergebnis


@router.get("/m/{mandant_id}/suche")
def suche(k: Mitglieder, q: Annotated[str, Query(min_length=2, max_length=80)]):
    treffer = listen.suche(k, q)
    return {
        "belege": [beleg_api.kurz(k, b) for b in treffer["belege"]],
        "partner": [auszug(p, "id", "name", "uid", "kreditor") for p in treffer["partner"]],
        "anforderungen": [auszug(a, "id", "nummer", "titel", "lieferant", "status") for a in treffer["anforderungen"]],
        "erstattungen": [auszug(e, "id", "titel", "status") for e in treffer["erstattungen"]],
    }


@router.get("/m/{mandant_id}/mitteilungen")
def mitteilungen(k: Mitglieder):
    zeilen = k.db.scalars(
        select(Mitteilung)
        .where(Mitteilung.mandant_id == k.mandant.id, Mitteilung.benutzer_id == k.id)
        .order_by(Mitteilung.id.desc())
        .limit(50)
    )
    return [auszug(m, "id", "text", "ziel", "gelesen", "erstellt_am") for m in zeilen]


class Gelesen(Eingabe):
    nummern: Annotated[list[int], Field(max_length=100)] = []


@router.post("/m/{mandant_id}/mitteilungen/gelesen", status_code=204)
def gelesen(eingabe: Gelesen, k: Mitglieder):
    bedingungen = [Mitteilung.mandant_id == k.mandant.id, Mitteilung.benutzer_id == k.id]
    if eingabe.nummern:
        bedingungen.append(Mitteilung.id.in_(eingabe.nummern))
    k.db.execute(update(Mitteilung).where(*bedingungen).values(gelesen=True))
    k.db.commit()
