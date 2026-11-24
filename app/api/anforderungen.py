from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import func, select

from ..dienste import anforderung, belege, freigabe, pdf
from ..dienste.fehler import Verboten
from ..dienste.protokoll import verlauf
from ..modelle import Anforderung
from ..sicherheit import Kontext, Mitglieder
from .belege import kann_entscheiden
from .freigaben import Schritt
from .gemeinsam import Datei, Eingabe, Geld, Kommentar, auszug, einfach, lies_datei, pdf_antwort, person, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}/anforderungen", tags=["Bestellanforderungen"])
Zahl = Annotated[str, Field(pattern=r"^\d{1,9}([.,]\d{1,4})?$")]
KURZ = (
    "id",
    "nummer",
    "status",
    "lieferant",
    "titel",
    "netto",
    "kostenstelle",
    "konto",
    "leistung_am",
    "erstellt_am",
    "freigegeben_am",
)


class Position(Eingabe):
    nummer: zeichen(60) | None = None
    text: zeichen(200, 1)
    menge: Zahl
    einzelpreis: Zahl


class Neu(Eingabe):
    lieferant: zeichen(255, 2)
    titel: zeichen(200, 2)
    beschreibung: zeichen(2000) = ""
    notiz: zeichen(1000) | None = None
    leistung_am: date | None = None
    netto: Geld | None = None
    positionen: Annotated[list[Position], Field(max_length=100)] = []
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    ziele: Annotated[list[Schritt], Field(max_length=6)] = []


class Aenderung(Eingabe):
    lieferant: zeichen(255, 2) | None = None
    titel: zeichen(200, 2) | None = None
    beschreibung: zeichen(2000) | None = None
    notiz: zeichen(1000) | None = None
    leistung_am: date | None = None
    netto: Geld | None = None
    positionen: Annotated[list[Position], Field(max_length=100)] | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None


class Eingang(Eingabe):
    datum: date
    lieferschein: zeichen(80) | None = None
    mengen: dict[str, Zahl]


def zahlen(zeilen: list[dict]) -> list[dict]:
    return [z | {"menge": z["menge"].replace(",", "."), "einzelpreis": z["einzelpreis"].replace(",", ".")} for z in zeilen]


def zeile(k: Kontext, eintrag: Anforderung) -> dict:
    return auszug(eintrag, *KURZ) | {
        "person": person(k.db, eintrag.benutzer_id),
        "eigen": eintrag.benutzer_id == k.id,
        "verrechnet": str(anforderung.verrechnet(k.db, eintrag)),
    }


def lang(k: Kontext, eintrag: Anforderung) -> dict:
    workflow = freigabe.workflow_finden(k.db, "anforderung", eintrag) if eintrag.status == "neu" else None
    return (
        zeile(k, eintrag)
        | auszug(eintrag, "beschreibung", "notiz", "positionen", "partner_id")
        | {
            "rechnungen": [
                auszug(b, "id", "art", "nummer", "netto", "status", "datum") for b in anforderung.rechnungen(k.db, eintrag)
            ],
            "wareneingaenge": [
                auszug(w, "id", "datum", "lieferschein", "mengen", "von") for w in anforderung.wareneingaenge(k.db, eintrag)
            ],
            "geliefert": [str(m) for m in anforderung.geliefert(k.db, eintrag)],
            "freigabe": freigabe.als_liste(k.db, "anforderung", eintrag.id),
            "freigabe_moeglich": kann_entscheiden(k, "anforderung", eintrag),
            "workflow": auszug(workflow, "id", "name") if workflow else None,
            "verlauf": verlauf(k.db, "anforderung", eintrag.id),
            "darf_aendern": eintrag.status == "neu" and (eintrag.benutzer_id == k.id or k.hat("buchhaltung", "admin")),
        }
    )


@router.get("")
def liste(
    k: Mitglieder,
    sicht: Literal["meine", "alle"] = "meine",
    status: Literal["neu", "freigabe", "freigegeben", "teilweise", "erfuellt", "abgelehnt"] | None = None,
):
    basis = [Anforderung.mandant_id == k.mandant.id, *anforderung.sichtfilter(k)]
    if sicht == "meine":
        basis.append(Anforderung.benutzer_id == k.id)
    kacheln = {
        name: {"anzahl": anzahl, "summe": str(summe or Decimal(0))}
        for name, anzahl, summe in k.db.execute(
            select(Anforderung.status, func.count(), func.sum(Anforderung.netto)).where(*basis).group_by(Anforderung.status)
        )
    }
    if status:
        basis.append(Anforderung.status == status)
    eintraege = k.db.scalars(select(Anforderung).where(*basis).order_by(Anforderung.id.desc()).limit(200))
    return {"kacheln": kacheln, "eintraege": [zeile(k, e) for e in eintraege]}


@router.get("/vorschlag")
def vorschlag(k: Mitglieder, lieferant: Annotated[str, Query(min_length=2, max_length=255)]):
    return einfach(anforderung.vorschlag(k.db, k.mandant.id, lieferant))


@router.post("", status_code=201)
def anlegen(eingabe: Neu, k: Mitglieder):
    if not k.hat("mitarbeit", "buchhaltung", "freigabe", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    werte = eingabe.model_dump()
    ziele = werte.pop("ziele")
    werte["positionen"] = zahlen(werte["positionen"])
    return lang(k, anforderung.anlegen(k, werte, ziele))


@router.get("/{nummer}")
def einzeln(nummer: int, k: Mitglieder):
    return lang(k, anforderung.hole(k, nummer))


@router.patch("/{nummer}")
def aendern(nummer: int, eingabe: Aenderung, k: Mitglieder):
    eintrag = anforderung.hole(k, nummer)
    werte = eingabe.model_dump(exclude_unset=True)
    for name in ("lieferant", "titel", "netto"):
        if name in werte and not werte[name]:
            del werte[name]
    if "beschreibung" in werte:
        werte["beschreibung"] = werte["beschreibung"] or ""
    if "positionen" in werte:
        werte["positionen"] = zahlen(werte["positionen"] or [])
    anforderung.aendern(k, eintrag, werte)
    return lang(k, eintrag)


@router.post("/{nummer}/wareneingang", status_code=201)
def wareneingang(nummer: int, eingabe: Eingang, k: Mitglieder):
    eintrag = anforderung.hole(k, nummer)
    mengen = {stelle: menge.replace(",", ".") for stelle, menge in eingabe.mengen.items()}
    anforderung.erfasse_wareneingang(k, eintrag, eingabe.datum, eingabe.lieferschein, mengen)
    return lang(k, eintrag)


@router.post("/{nummer}/kommentar", status_code=201)
def kommentieren(nummer: int, eingabe: Kommentar, k: Mitglieder):
    eintrag = anforderung.hole(k, nummer)
    belege.kommentieren(k, "anforderung", eintrag, eingabe.text)
    return lang(k, eintrag)


@router.post("/{nummer}/anhaenge", status_code=201)
def anhang(nummer: int, datei: Datei, k: Mitglieder):
    eintrag = anforderung.hole(k, nummer)
    belege.anhaengen(k, "anforderung", eintrag, *lies_datei(datei))
    return lang(k, eintrag)


@router.get("/{nummer}/pdf")
def als_pdf(nummer: int, k: Mitglieder):
    eintrag = anforderung.hole(k, nummer)
    return pdf_antwort(pdf.anforderung(k, eintrag), f"anforderung_{eintrag.id}.pdf")
