import secrets
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import func, select

from ..dienste import belege, freigabe
from ..dienste.fehler import Konflikt, NichtGefunden, Ungueltig
from ..dienste.protokoll import beim_mandanten, gueltig
from ..dienste.pruefung import iban_gueltig
from ..dienste.werte import RECHNUNGEN, als_kennung
from ..modelle import (
    Auswertung,
    Automatik,
    Beleg,
    Benutzer,
    Freigabeschritt,
    Mitglied,
    Partner,
    Protokoll,
    Sperre,
    Stammwert,
    Team,
    Workflow,
    Zugang,
)
from ..sicherheit import ALLE_ROLLEN, ZUGANGSROLLEN, Buchhaltung, Kontext, Leitung, Verwaltung, passwort_hash, token_hash
from .freigaben import Schritt
from .gemeinsam import Eingabe, Geld, auszug, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}", tags=["Einstellungen"])
Rolle = Literal[ALLE_ROLLEN]
STAMMARTEN = ("konto", "kostenstelle", "kostentraeger", "steuerschluessel", "vertragstyp")
Stammart = Literal[STAMMARTEN]


class MandantAngaben(Eingabe):
    name: zeichen(200, 2) | None = None
    strasse: zeichen(200) | None = None
    plz: zeichen(10) | None = None
    ort: zeichen(100) | None = None
    uid: zeichen(20) | None = None
    iban: zeichen(42) | None = None
    bic: zeichen(11) | None = None
    vier_augen: bool | None = None
    erstattung_konto: zeichen(20) | None = None
    rueckstellung_konto: zeichen(20) | None = None
    erinnerung_tage: Annotated[int, Field(ge=0, le=60)] | None = None


class NeuePerson(Eingabe):
    name: zeichen(80, 2)
    email: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)]
    rollen: Annotated[list[Rolle], Field(min_length=1)]
    passwort: Annotated[str, Field(min_length=12, max_length=200)] | None = None


class Rollen(Eingabe):
    rollen: Annotated[list[Rolle], Field(min_length=1)]


class TeamEingabe(Eingabe):
    name: zeichen(80, 2)
    mitglieder: Annotated[list[int], Field(max_length=50)]


class Bedingung(Eingabe):
    art: Literal["beleg", "erstattung", "anforderung"] | None = None
    ab: Geld | None = None
    bis: Geld | None = None
    kostenstelle: zeichen(20) | None = None
    partner_id: int | None = None


class WorkflowEingabe(Eingabe):
    name: zeichen(80, 2)
    rang: Annotated[int, Field(ge=1, le=999)] = 10
    bedingung: Bedingung = Bedingung()
    schritte: Annotated[list[Schritt], Field(min_length=1, max_length=6)]


class AutomatikEingabe(Eingabe):
    name: zeichen(80, 2)
    aktion: Literal["vorschlagen", "anfordern", "freigeben"]
    partner_id: int | None = None
    max_brutto: Geld
    gleiche: Annotated[int, Field(ge=1, le=10)] = 3
    workflow_id: int | None = None
    aktiv: bool = True


class StammEingabe(Eingabe):
    art: Stammart
    code: zeichen(80, 1)
    name: zeichen(200, 1)


class SperrEingabe(Eingabe):
    art: Literal["iban", "absender"]
    wert: zeichen(200, 3)
    grund: zeichen(300) = ""


class ZugangEingabe(Eingabe):
    name: zeichen(80, 2)
    rollen: Annotated[list[Literal[ZUGANGSROLLEN]], Field(min_length=1)]


class BudgetEingabe(Eingabe):
    art: Literal["kostenstelle", "konto", "partner"]
    wert: zeichen(80, 1)
    budget: Geld


def eintrag(k: Kontext, klasse, nummer: int, name: str):
    zeile = k.db.get(klasse, nummer)
    if not zeile or zeile.mandant_id != k.mandant.id:
        raise NichtGefunden(f"{name} nicht gefunden")
    return zeile


@router.get("/mandant")
def mandant_lesen(k: Leitung):
    ergebnis = auszug(k.mandant, "id", "name", "strasse", "plz", "ort", "land", "uid", "iban", "bic")
    e = k.mandant.einstellungen
    return ergebnis | {
        "vier_augen": e.get("vier_augen", True),
        "erstattung_konto": e.get("erstattung_konto", "3600"),
        "rueckstellung_konto": e.get("rueckstellung_konto", "3070"),
        "erinnerung_tage": e.get("erinnerung_tage", 3),
    }


@router.patch("/mandant")
def mandant_aendern(eingabe: MandantAngaben, k: Verwaltung):
    werte = eingabe.model_dump(exclude_unset=True)
    for name, laenge in (("iban", 40), ("uid", 20), ("bic", 11)):
        if werte.get(name):
            werte[name] = als_kennung(werte[name], laenge)
    if werte.get("iban") and not iban_gueltig(werte["iban"]):
        raise Ungueltig("IBAN ist ungültig")
    lose = {
        n: werte.pop(n) for n in ("vier_augen", "erstattung_konto", "rueckstellung_konto", "erinnerung_tage") if n in werte
    }
    for name, wert in werte.items():
        if name in ("uid", "iban", "bic"):
            setattr(k.mandant, name, wert or None)
        elif wert is not None:
            setattr(k.mandant, name, wert)
    k.mandant.einstellungen = k.mandant.einstellungen | {n: w for n, w in lose.items() if w is not None}
    beim_mandanten(k.db, k.mandant, k.name, "geaendert", neu=werte | lose)
    neu_bewerten(k)
    k.db.commit()
    return mandant_lesen(k)


def neu_bewerten(k: Kontext) -> None:
    for beleg in k.db.scalars(
        select(Beleg).where(Beleg.mandant_id == k.mandant.id, Beleg.status == "neu", Beleg.art.in_(RECHNUNGEN))
    ):
        belege.bewerte(k.db, beleg)


@router.get("/personen")
def personen(k: Leitung):
    zeilen = k.db.execute(
        select(Benutzer, Mitglied.rollen)
        .join(Mitglied, Mitglied.benutzer_id == Benutzer.id)
        .where(Mitglied.mandant_id == k.mandant.id)
        .order_by(Benutzer.name)
    )
    return [
        auszug(b, "id", "name", "email", "aktiv", "abwesend_von", "abwesend_bis", "vertretung_id")
        | {"rollen": rollen, "abwesend": freigabe.abwesend(b)}
        for b, rollen in zeilen
    ]


@router.post("/personen", status_code=201)
def person_anlegen(eingabe: NeuePerson, k: Verwaltung):
    email = eingabe.email.lower()
    benutzer = k.db.scalar(select(Benutzer).where(Benutzer.email == email))
    if benutzer and k.db.get(Mitglied, (k.mandant.id, benutzer.id)):
        raise Konflikt("Person gehört schon zu diesem Mandanten")
    if not benutzer:
        if not eingabe.passwort:
            raise Ungueltig("Für neue Personen wird ein Startpasswort mit mindestens 12 Zeichen gebraucht")
        benutzer = Benutzer(name=eingabe.name, email=email, passwort=passwort_hash(eingabe.passwort))
        k.db.add(benutzer)
        k.db.flush()
    k.db.add(Mitglied(mandant_id=k.mandant.id, benutzer_id=benutzer.id, rollen=sorted(set(eingabe.rollen))))
    beim_mandanten(k.db, k.mandant, k.name, "person_angelegt", person=benutzer.name, rollen=sorted(set(eingabe.rollen)))
    k.db.commit()
    return personen(k)


def mitglied(k: Kontext, nummer: int) -> Mitglied:
    zeile = k.db.get(Mitglied, (k.mandant.id, nummer))
    if not zeile:
        raise NichtGefunden("Person nicht gefunden")
    return zeile


def pruefe_letzte_verwaltung(k: Kontext, nummer: int) -> None:
    andere = k.db.scalars(select(Mitglied).where(Mitglied.mandant_id == k.mandant.id, Mitglied.benutzer_id != nummer))
    if not any("admin" in m.rollen for m in andere):
        raise Konflikt("Es muss mindestens eine Person mit der Rolle Verwaltung geben")


@router.patch("/personen/{nummer}")
def rollen_aendern(nummer: int, eingabe: Rollen, k: Verwaltung):
    zeile = mitglied(k, nummer)
    if "admin" not in eingabe.rollen:
        pruefe_letzte_verwaltung(k, nummer)
    alt, zeile.rollen = zeile.rollen, sorted(set(eingabe.rollen))
    name = k.db.get(Benutzer, nummer).name
    beim_mandanten(k.db, k.mandant, k.name, "rollen_geaendert", person=name, alt=alt, neu=zeile.rollen)
    k.db.commit()
    return personen(k)


@router.delete("/personen/{nummer}")
def person_entfernen(nummer: int, k: Verwaltung):
    zeile = mitglied(k, nummer)
    pruefe_letzte_verwaltung(k, nummer)
    offen = k.db.scalar(
        select(func.count())
        .select_from(Freigabeschritt)
        .where(
            Freigabeschritt.mandant_id == k.mandant.id,
            Freigabeschritt.ziel_art == "person",
            Freigabeschritt.ziel_id == nummer,
            Freigabeschritt.status.in_(("offen", "wartet")),
        )
    )
    if offen:
        raise Konflikt(f"Person hat noch {offen} offene Freigaben")
    k.db.delete(zeile)
    beim_mandanten(k.db, k.mandant, k.name, "person_entfernt", person=k.db.get(Benutzer, nummer).name)
    k.db.commit()
    return personen(k)


def pruefe_team(k: Kontext, eingabe: TeamEingabe) -> None:
    for nummer in eingabe.mitglieder:
        if not {"freigabe", "admin"} & set(mitglied(k, nummer).rollen):
            raise Ungueltig("Im Team dürfen nur Personen mit Freigaberecht sein")


@router.get("/teams")
def teams(k: Leitung):
    zeilen = k.db.scalars(select(Team).where(Team.mandant_id == k.mandant.id).order_by(Team.name))
    return [auszug(t, "id", "name", "mitglieder") for t in zeilen]


@router.post("/teams", status_code=201)
def team_anlegen(eingabe: TeamEingabe, k: Verwaltung):
    pruefe_team(k, eingabe)
    k.db.add(Team(mandant_id=k.mandant.id, name=eingabe.name, mitglieder=eingabe.mitglieder))
    beim_mandanten(k.db, k.mandant, k.name, "team_angelegt", name=eingabe.name)
    k.db.commit()
    return teams(k)


@router.put("/teams/{nummer}")
def team_aendern(nummer: int, eingabe: TeamEingabe, k: Verwaltung):
    team = eintrag(k, Team, nummer, "Team")
    pruefe_team(k, eingabe)
    team.name, team.mitglieder = eingabe.name, eingabe.mitglieder
    beim_mandanten(k.db, k.mandant, k.name, "team_geaendert", name=eingabe.name, mitglieder=eingabe.mitglieder)
    k.db.commit()
    return teams(k)


def verwendet(k: Kontext, art: str, nummer: int) -> bool:
    ziel = {"art": art, "id": nummer}
    return any(ziel in w.schritte for w in k.db.scalars(select(Workflow).where(Workflow.mandant_id == k.mandant.id)))


@router.delete("/teams/{nummer}")
def team_loeschen(nummer: int, k: Verwaltung):
    team = eintrag(k, Team, nummer, "Team")
    offen = k.db.scalar(
        select(func.count())
        .select_from(Freigabeschritt)
        .where(
            Freigabeschritt.ziel_art == "team",
            Freigabeschritt.ziel_id == nummer,
            Freigabeschritt.status.in_(("offen", "wartet")),
        )
    )
    if offen or verwendet(k, "team", nummer):
        raise Konflikt("Team wird noch in Workflows oder offenen Freigaben verwendet")
    k.db.delete(team)
    beim_mandanten(k.db, k.mandant, k.name, "team_geloescht", name=team.name)
    k.db.commit()
    return teams(k)


@router.get("/workflows")
def workflows(k: Leitung):
    zeilen = k.db.scalars(select(Workflow).where(Workflow.mandant_id == k.mandant.id).order_by(Workflow.rang, Workflow.id))
    return [auszug(w, "id", "name", "rang", "bedingung", "schritte") for w in zeilen]


def workflow_werte(k: Kontext, eingabe: WorkflowEingabe) -> dict:
    schritte = [s.model_dump() for s in eingabe.schritte]
    freigabe.pruefe_ziele(k.db, k.mandant.id, schritte)
    bedingung = {
        n: str(w) if n in ("ab", "bis") else w for n, w in eingabe.bedingung.model_dump(exclude_none=True).items() if w
    }
    if bedingung.get("partner_id"):
        eintrag(k, Partner, bedingung["partner_id"], "Geschäftspartner")
    return {"name": eingabe.name, "rang": eingabe.rang, "bedingung": bedingung, "schritte": schritte}


@router.post("/workflows", status_code=201)
def workflow_anlegen(eingabe: WorkflowEingabe, k: Verwaltung):
    werte = workflow_werte(k, eingabe)
    k.db.add(Workflow(mandant_id=k.mandant.id, **werte))
    beim_mandanten(k.db, k.mandant, k.name, "workflow_angelegt", **werte)
    k.db.commit()
    return workflows(k)


@router.put("/workflows/{nummer}")
def workflow_aendern(nummer: int, eingabe: WorkflowEingabe, k: Verwaltung):
    workflow = eintrag(k, Workflow, nummer, "Workflow")
    werte = workflow_werte(k, eingabe)
    for name, wert in werte.items():
        setattr(workflow, name, wert)
    beim_mandanten(k.db, k.mandant, k.name, "workflow_geaendert", **werte)
    k.db.commit()
    return workflows(k)


@router.delete("/workflows/{nummer}")
def workflow_loeschen(nummer: int, k: Verwaltung):
    workflow = eintrag(k, Workflow, nummer, "Workflow")
    if k.db.scalar(select(Automatik.id).where(Automatik.workflow_id == nummer).limit(1)):
        raise Konflikt("Workflow wird noch von einer Automatik verwendet")
    k.db.delete(workflow)
    beim_mandanten(k.db, k.mandant, k.name, "workflow_geloescht", name=workflow.name)
    k.db.commit()
    return workflows(k)


@router.get("/automatiken")
def automatiken(k: Leitung):
    zeilen = k.db.scalars(select(Automatik).where(Automatik.mandant_id == k.mandant.id).order_by(Automatik.id))
    return [auszug(a, "id", "name", "aktion", "partner_id", "max_brutto", "gleiche", "workflow_id", "aktiv") for a in zeilen]


def automatik_werte(k: Kontext, eingabe: AutomatikEingabe) -> dict:
    if eingabe.partner_id:
        eintrag(k, Partner, eingabe.partner_id, "Geschäftspartner")
    if eingabe.workflow_id:
        eintrag(k, Workflow, eingabe.workflow_id, "Workflow")
    return eingabe.model_dump()


@router.post("/automatiken", status_code=201)
def automatik_anlegen(eingabe: AutomatikEingabe, k: Verwaltung):
    werte = automatik_werte(k, eingabe)
    k.db.add(Automatik(mandant_id=k.mandant.id, **werte))
    beim_mandanten(k.db, k.mandant, k.name, "automatik_angelegt", **werte)
    k.db.commit()
    return automatiken(k)


@router.put("/automatiken/{nummer}")
def automatik_aendern(nummer: int, eingabe: AutomatikEingabe, k: Verwaltung):
    regel = eintrag(k, Automatik, nummer, "Automatik")
    werte = automatik_werte(k, eingabe)
    for name, wert in werte.items():
        setattr(regel, name, wert)
    beim_mandanten(k.db, k.mandant, k.name, "automatik_geaendert", **werte)
    k.db.commit()
    return automatiken(k)


@router.delete("/automatiken/{nummer}")
def automatik_loeschen(nummer: int, k: Verwaltung):
    regel = eintrag(k, Automatik, nummer, "Automatik")
    k.db.delete(regel)
    beim_mandanten(k.db, k.mandant, k.name, "automatik_geloescht", name=regel.name)
    k.db.commit()
    return automatiken(k)


@router.get("/stammwerte")
def stammwerte(k: Leitung, art: Stammart | None = None):
    bedingungen = [Stammwert.mandant_id == k.mandant.id]
    if art:
        bedingungen.append(Stammwert.art == art)
    zeilen = k.db.scalars(select(Stammwert).where(*bedingungen).order_by(Stammwert.art, Stammwert.code))
    return [auszug(s, "id", "art", "code", "name") for s in zeilen]


@router.post("/stammwerte", status_code=201)
def stammwert_setzen(eingabe: StammEingabe, k: Buchhaltung):
    vorhanden = k.db.scalar(
        select(Stammwert).where(
            Stammwert.mandant_id == k.mandant.id, Stammwert.art == eingabe.art, Stammwert.code == eingabe.code
        )
    )
    if vorhanden:
        vorhanden.name = eingabe.name
    else:
        k.db.add(Stammwert(mandant_id=k.mandant.id, **eingabe.model_dump()))
    beim_mandanten(k.db, k.mandant, k.name, "stammwert_gesetzt", **eingabe.model_dump())
    k.db.commit()
    return stammwerte(k, eingabe.art)


@router.delete("/stammwerte/{nummer}")
def stammwert_loeschen(nummer: int, k: Buchhaltung):
    wert = eintrag(k, Stammwert, nummer, "Stammwert")
    k.db.delete(wert)
    beim_mandanten(k.db, k.mandant, k.name, "stammwert_geloescht", art=wert.art, code=wert.code)
    k.db.commit()
    return stammwerte(k, wert.art)


@router.get("/sperren")
def sperren(k: Leitung):
    zeilen = k.db.scalars(select(Sperre).where(Sperre.mandant_id == k.mandant.id).order_by(Sperre.art, Sperre.wert))
    return [auszug(s, "id", "art", "wert", "grund") for s in zeilen]


@router.post("/sperren", status_code=201)
def sperre_anlegen(eingabe: SperrEingabe, k: Buchhaltung):
    wert = als_kennung(eingabe.wert, 40) if eingabe.art == "iban" else eingabe.wert.lower()
    if not wert:
        raise Ungueltig("Wert ist ungültig")
    vorhanden = k.db.scalar(
        select(Sperre).where(Sperre.mandant_id == k.mandant.id, Sperre.art == eingabe.art, Sperre.wert == wert)
    )
    if vorhanden:
        raise Konflikt("Steht schon auf der Sperrliste")
    k.db.add(Sperre(mandant_id=k.mandant.id, art=eingabe.art, wert=wert, grund=eingabe.grund))
    beim_mandanten(k.db, k.mandant, k.name, "gesperrt", art=eingabe.art, wert=wert, grund=eingabe.grund)
    neu_bewerten(k)
    k.db.commit()
    return sperren(k)


@router.delete("/sperren/{nummer}")
def sperre_aufheben(nummer: int, k: Verwaltung):
    sperre = eintrag(k, Sperre, nummer, "Sperre")
    k.db.delete(sperre)
    beim_mandanten(k.db, k.mandant, k.name, "sperre_aufgehoben", art=sperre.art, wert=sperre.wert)
    neu_bewerten(k)
    k.db.commit()
    return sperren(k)


@router.get("/zugaenge")
def zugaenge(k: Verwaltung):
    zeilen = k.db.scalars(select(Zugang).where(Zugang.mandant_id == k.mandant.id).order_by(Zugang.id))
    return [auszug(z, "id", "name", "rollen", "erstellt_am") for z in zeilen]


@router.post("/zugaenge", status_code=201)
def zugang_anlegen(eingabe: ZugangEingabe, k: Verwaltung):
    token = f"bf_{secrets.token_urlsafe(32)}"
    rollen = sorted(set(eingabe.rollen))
    k.db.add(Zugang(mandant_id=k.mandant.id, name=eingabe.name, token_hash=token_hash(token), rollen=rollen))
    beim_mandanten(k.db, k.mandant, k.name, "zugang_angelegt", name=eingabe.name, rollen=rollen)
    k.db.commit()
    return {"token": token, "zugaenge": zugaenge(k)}


@router.delete("/zugaenge/{nummer}")
def zugang_loeschen(nummer: int, k: Verwaltung):
    zugang = eintrag(k, Zugang, nummer, "Zugang")
    k.db.delete(zugang)
    beim_mandanten(k.db, k.mandant, k.name, "zugang_geloescht", name=zugang.name)
    k.db.commit()
    return zugaenge(k)


@router.post("/budgets", status_code=201)
def budget_setzen(eingabe: BudgetEingabe, k: Buchhaltung):
    vorhanden = k.db.scalar(
        select(Auswertung).where(
            Auswertung.mandant_id == k.mandant.id, Auswertung.art == eingabe.art, Auswertung.wert == eingabe.wert
        )
    )
    if vorhanden:
        vorhanden.budget = eingabe.budget
    else:
        k.db.add(Auswertung(mandant_id=k.mandant.id, **eingabe.model_dump()))
    beim_mandanten(k.db, k.mandant, k.name, "budget_gesetzt", **eingabe.model_dump())
    k.db.commit()
    return {"ok": True}


@router.delete("/budgets/{nummer}", status_code=204)
def budget_loeschen(nummer: int, k: Buchhaltung):
    k.db.delete(eintrag(k, Auswertung, nummer, "Auswertung"))
    k.db.commit()


@router.get("/protokoll")
def protokoll(
    k: Leitung,
    grenze: Annotated[int, Query(ge=1, le=500)] = 100,
    vor: Annotated[int | None, Query(ge=1)] = None,
    wer: Annotated[str | None, Query(max_length=80)] = None,
    tag: date | None = None,
):
    bedingungen = [Protokoll.mandant_id == k.mandant.id]
    if vor:
        bedingungen.append(Protokoll.id < vor)
    if wer:
        bedingungen.append(Protokoll.wer == wer)
    if tag:
        bedingungen.append(Protokoll.zeitpunkt.startswith(tag.isoformat()))
    zeilen = k.db.scalars(select(Protokoll).where(*bedingungen).order_by(Protokoll.id.desc()).limit(grenze))
    return [auszug(p, "id", "objekt_art", "objekt_id", "wer", "aktion", "details", "zeitpunkt") for p in zeilen]


@router.get("/protokoll/pruefung")
def protokoll_pruefen(k: Leitung):
    stimmt, stelle = gueltig(k.db, k.mandant.id)
    return {"gueltig": stimmt, "fehler_bei": stelle}
