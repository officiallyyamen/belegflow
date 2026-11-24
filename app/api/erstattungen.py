import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import select

from ..dienste import belege, erstattung, freigabe, pdf, reisekosten
from ..dienste.fehler import Ungueltig, Verboten
from ..dienste.protokoll import verlauf
from ..modelle import Erstattung, Erstattungsposten
from ..sicherheit import Kontext, Mitglieder
from .belege import kann_entscheiden
from .gemeinsam import (
    Begruendung,
    Eingabe,
    Kommentar,
    auszug,
    bild_antwort,
    datei_antwort,
    einfach,
    lies_datei,
    pdf_antwort,
    person,
    zeichen,
)

router = APIRouter(prefix="/api/m/{mandant_id}/erstattungen", tags=["Erstattungen"])
POSTEN = (
    "id",
    "art",
    "titel",
    "datum",
    "daten",
    "rechnung",
    "betrag",
    "ust",
    "konto",
    "kostenstelle",
    "ausgeschlossen",
    "dateiname",
    "dateityp",
)
Zeitpunkt = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")]
Zahl = Annotated[str, Field(pattern=r"^\d{1,7}([.,]\d{1,6})?$")]


class Neu(Eingabe):
    titel: zeichen(120, 2)
    hinweis: zeichen(500) | None = None


class Aenderung(Eingabe):
    titel: zeichen(120, 2) | None = None
    hinweis: zeichen(500) | None = None
    iban: zeichen(40) | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None


class Etappe(Eingabe):
    land: zeichen(80, 1)
    von: Zeitpunkt


class Nacht(Eingabe):
    land: zeichen(80, 1)
    anzahl: Annotated[int, Field(ge=0, le=180)]


class Angaben(Eingabe):
    lieferant: zeichen(200) | None = None
    nummer: zeichen(80) | None = None
    betrag: Zahl | None = None
    ust: Zahl | None = None
    trinkgeld: Zahl | None = None
    waehrung: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    kurs: Zahl | None = None
    grund: zeichen(300) | None = None
    eigenbeleg: zeichen(300) | None = None
    intern: zeichen(500) | None = None
    extern: zeichen(500) | None = None
    ort: zeichen(200) | None = None
    etappen: Annotated[list[Etappe], Field(max_length=40)] | None = None
    ende: Zeitpunkt | None = None
    mahlzeiten: dict[str, Annotated[list[Literal["fruehstueck", "mittag", "abend"]], Field(max_length=3)]] | None = None
    naechte: Annotated[list[Nacht], Field(max_length=40)] | None = None
    start: zeichen(200) | None = None
    ziel: zeichen(200) | None = None
    stopps: Annotated[list[zeichen(200)], Field(max_length=10)] | None = None
    km: Zahl | None = None
    hin_zurueck: bool | None = None
    fahrzeug: Literal["pkw", "motorrad", "fahrrad"] | None = None
    mitfahrer: Annotated[int, Field(ge=0, le=8)] | None = None
    erkannt: list[zeichen(40)] | None = None

    def sauber(self) -> dict:
        werte = self.model_dump(exclude_none=True)
        for name in ("betrag", "ust", "trinkgeld", "kurs", "km"):
            if name in werte:
                werte[name] = werte[name].replace(",", ".")
        return werte


class PostenAenderung(Eingabe):
    titel: zeichen(200) | None = None
    datum: date | None = None
    daten: Angaben | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    ausgeschlossen: bool | None = None


class Probe(Eingabe):
    art: Literal["auslage", "bewirtung", "taggeld", "kilometer"]
    datum: date | None = None
    daten: Angaben


def zeile(k: Kontext, antrag: Erstattung) -> dict:
    return auszug(antrag, "id", "titel", "hinweis", "status", "zahlstatus", "erstellt_am", "freigegeben_am") | {
        "person": person(k.db, antrag.benutzer_id),
        "eigen": antrag.benutzer_id == k.id,
        "summe": str(erstattung.summe(antrag)),
        "posten": len(erstattung.posten(k.db, antrag.id)),
    }


def lang(k: Kontext, antrag: Erstattung) -> dict:
    eintraege = erstattung.posten(k.db, antrag.id)
    workflow = freigabe.workflow_finden(k.db, "erstattung", antrag) if antrag.status == "pruefung" else None
    return (
        zeile(k, antrag)
        | auszug(antrag, "iban", "konto", "kostenstelle", "bearbeitet_von")
        | {
            "eintraege": [auszug(p, *POSTEN) for p in eintraege],
            "maengel": erstattung.maengel(antrag, eintraege),
            "warnungen": erstattung.warnungen(k.db, antrag, eintraege),
            "freigabe": freigabe.als_liste(k.db, "erstattung", antrag.id),
            "freigabe_moeglich": kann_entscheiden(k, "erstattung", antrag),
            "workflow": auszug(workflow, "id", "name") if workflow else None,
            "verlauf": verlauf(k.db, "erstattung", antrag.id),
            "darf_aendern": antrag.benutzer_id == k.id and antrag.status in erstattung.OFFEN,
            "darf_pruefen": k.hat("buchhaltung", "admin") and antrag.status == "pruefung",
        }
    )


@router.get("")
def liste(k: Mitglieder, sicht: Literal["meine", "pruefen", "alle"] = "meine"):
    bedingungen = [Erstattung.mandant_id == k.mandant.id, Erstattung.status != "verworfen"]
    if sicht == "meine":
        bedingungen.append(Erstattung.benutzer_id == k.id)
    elif not k.sieht_alles:
        raise Verboten("Dafür fehlt die Berechtigung")
    elif sicht == "pruefen":
        bedingungen.append(Erstattung.status == "pruefung")
    else:
        bedingungen.append(Erstattung.status != "entwurf")
    antraege = k.db.scalars(select(Erstattung).where(*bedingungen).order_by(Erstattung.id.desc()).limit(200))
    return [zeile(k, a) for a in antraege]


@router.post("", status_code=201)
def anlegen(eingabe: Neu, k: Mitglieder):
    if not k.hat("mitarbeit", "buchhaltung", "freigabe", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    return lang(k, erstattung.anlegen(k, eingabe.titel, eingabe.hinweis))


@router.get("/laender")
def laender(_: Mitglieder):
    saetze = reisekosten.saetze()
    return {
        "laender": reisekosten.laender(),
        "kilometer": saetze["kilometer"],
        "quelle": saetze["quelle"],
        "abgerufen": saetze["abgerufen"],
    }


@router.post("/rechnen")
def rechnen(eingabe: Probe, k: Mitglieder):
    betrag, ust, titel, _, zeilen = erstattung.rechne(k.db, eingabe.art, "", eingabe.datum, eingabe.daten.sauber())
    k.db.commit()
    return einfach({"betrag": betrag, "ust": ust, "titel": titel, "zeilen": zeilen})


@router.get("/{nummer}")
def einzeln(nummer: int, k: Mitglieder):
    return lang(k, erstattung.hole(k, nummer))


@router.patch("/{nummer}")
def aendern(nummer: int, eingabe: Aenderung, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    erstattung.aendern(k, antrag, eingabe.model_dump(exclude_unset=True))
    return lang(k, antrag)


@router.delete("/{nummer}", status_code=204)
def verwerfen(nummer: int, k: Mitglieder):
    erstattung.verwerfen(k, erstattung.hole(k, nummer))


@router.post("/{nummer}/posten", status_code=201)
def posten_anlegen(
    nummer: int,
    k: Mitglieder,
    art: Annotated[Literal["auslage", "bewirtung", "taggeld", "kilometer"], Form()],
    angaben: Annotated[str, Form(max_length=20000)] = "{}",
    titel: Annotated[str, Form(max_length=200)] = "",
    datum: Annotated[date | None, Form()] = None,
    datei: Annotated[UploadFile | None, File()] = None,
):
    antrag = erstattung.hole(k, nummer)
    try:
        daten = TypeAdapter(Angaben).validate_python(json.loads(angaben))
    except (ValidationError, ValueError) as fehler:
        raise Ungueltig("Angaben sind ungültig") from fehler
    inhalt = lies_datei(datei) if datei else None
    sauberer_titel = titel.replace("\x00", "").strip()
    erstattung.posten_anlegen(k, antrag, art, sauberer_titel, datum, daten.sauber(), inhalt)
    return lang(k, antrag)


@router.patch("/{nummer}/posten/{posten}")
def posten_aendern(nummer: int, posten: int, eingabe: PostenAenderung, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    werte = eingabe.model_dump(exclude_unset=True)
    if eingabe.daten:
        werte["daten"] = eingabe.daten.sauber()
    erstattung.posten_aendern(k, antrag, erstattung.hole_posten(k, antrag, posten), werte)
    return lang(k, antrag)


@router.delete("/{nummer}/posten/{posten}")
def posten_loeschen(nummer: int, posten: int, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    erstattung.posten_loeschen(k, antrag, erstattung.hole_posten(k, antrag, posten))
    return lang(k, antrag)


def mit_datei(k: Kontext, nummer: int, posten: int) -> Erstattungsposten:
    eintrag = erstattung.hole_posten(k, erstattung.hole(k, nummer), posten)
    if not eintrag.sha256:
        raise Ungueltig("Zu diesem Posten gibt es keine Datei")
    return eintrag


@router.get("/{nummer}/posten/{posten}/datei")
def posten_datei(nummer: int, posten: int, k: Mitglieder):
    eintrag = mit_datei(k, nummer, posten)
    return datei_antwort(eintrag.sha256, eintrag.dateityp, eintrag.dateiname)


@router.get("/{nummer}/posten/{posten}/bild")
def posten_bild(nummer: int, posten: int, k: Mitglieder, seite: Annotated[int, Query(ge=1, le=500)] = 1):
    eintrag = mit_datei(k, nummer, posten)
    return bild_antwort(eintrag.sha256, eintrag.dateityp, seite)


@router.post("/{nummer}/einreichen")
def einreichen(nummer: int, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    erstattung.einreichen(k, antrag)
    return lang(k, antrag)


@router.post("/{nummer}/zurueckgeben")
def zurueckgeben(nummer: int, eingabe: Begruendung, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    erstattung.zurueckgeben(k, antrag, eingabe.grund)
    return lang(k, antrag)


@router.post("/{nummer}/kommentar", status_code=201)
def kommentieren(nummer: int, eingabe: Kommentar, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    belege.kommentieren(k, "erstattung", antrag, eingabe.text)
    return lang(k, antrag)


@router.get("/{nummer}/pdf")
def als_pdf(nummer: int, k: Mitglieder):
    antrag = erstattung.hole(k, nummer)
    return pdf_antwort(pdf.spesen(k, antrag), f"erstattung_{antrag.id}.pdf")
