from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import func, select

from ..dienste import belege
from ..dienste.fehler import NichtGefunden, Ungueltig
from ..dienste.protokoll import protokolliere, verlauf
from ..dienste.pruefung import iban_gueltig
from ..dienste.werte import RECHNUNGEN, als_kennung
from ..modelle import Beleg, Nachricht, Partner, Sperre
from ..sicherheit import Buchhaltung, Kontext, Leitung
from .gemeinsam import Ab, Eingabe, Grenze, auszug, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}", tags=["Geschäftspartner"])
FELDER = (
    "id",
    "name",
    "kreditor",
    "uid",
    "strasse",
    "plz",
    "ort",
    "email",
    "ibans",
    "zahlungsziel",
    "skonto_prozent",
    "skonto_tage",
    "konto",
    "kostenstelle",
    "steuerschluessel",
)


class Angaben(Eingabe):
    name: zeichen(255, 2) | None = None
    kreditor: zeichen(20) | None = None
    uid: zeichen(20) | None = None
    strasse: zeichen(200) | None = None
    plz: zeichen(10) | None = None
    ort: zeichen(100) | None = None
    email: zeichen(200) | None = None
    ibans: Annotated[list[zeichen(42)], Field(max_length=10)] | None = None
    zahlungsziel: Annotated[int, Field(ge=0, le=365)] | None = None
    skonto_prozent: Annotated[str, Field(pattern=r"^\d{1,2}(\.\d{1,2})?$")] | None = None
    skonto_tage: Annotated[int, Field(ge=0, le=180)] | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    steuerschluessel: zeichen(20) | None = None


class Neu(Angaben):
    name: zeichen(255, 2)


def hole(k: Kontext, nummer: int) -> Partner:
    partner = k.db.get(Partner, nummer)
    if not partner or partner.mandant_id != k.mandant.id:
        raise NichtGefunden("Geschäftspartner nicht gefunden")
    return partner


def pruefe(werte: dict) -> dict:
    if "uid" in werte:
        werte["uid"] = als_kennung(werte["uid"], 20)
    if "ibans" in werte:
        werte["ibans"] = list(dict.fromkeys(als_kennung(i, 40) or "" for i in werte["ibans"] or []))
        if not all(iban_gueltig(i) for i in werte["ibans"]):
            raise Ungueltig("IBAN ist ungültig")
    if "name" in werte and not werte["name"]:
        del werte["name"]
    return werte


@router.get("/partner")
def liste(
    k: Leitung,
    suche: Annotated[str | None, Query(max_length=80)] = None,
    grenze: Grenze = 100,
    ab: Ab = 0,
):
    bedingungen = [Partner.mandant_id == k.mandant.id]
    if suche:
        bedingungen.append(Partner.name.icontains(suche, autoescape=True) | Partner.uid.icontains(suche, autoescape=True))
    partner = list(k.db.scalars(select(Partner).where(*bedingungen).order_by(Partner.name).limit(grenze).offset(ab)))
    jahr = date.today().year
    umsatz = {
        nummer: (anzahl, summe)
        for nummer, anzahl, summe in k.db.execute(
            select(Beleg.partner_id, func.count(), func.sum(Beleg.brutto))
            .where(
                Beleg.mandant_id == k.mandant.id,
                Beleg.art == "rechnung",
                Beleg.status.in_(("freigegeben", "exportiert")),
                Beleg.datum >= date(jahr, 1, 1),
            )
            .group_by(Beleg.partner_id)
        )
    }
    ergebnis = []
    for p in partner:
        anzahl, summe = umsatz.get(p.id, (0, Decimal(0)))
        ergebnis.append(auszug(p, *FELDER) | {"belege": anzahl, "umsatz": str(summe or Decimal(0))})
    return ergebnis


@router.post("/partner", status_code=201)
def anlegen(eingabe: Neu, k: Buchhaltung):
    werte = pruefe(eingabe.model_dump(exclude_unset=True))
    werte["kreditor"] = werte.get("kreditor") or belege.naechster_kreditor(k.db, k.mandant.id)
    partner = Partner(mandant_id=k.mandant.id, **werte)
    k.db.add(partner)
    protokolliere(k.db, "partner", partner, k.name, "angelegt", name=partner.name)
    k.db.commit()
    return auszug(partner, *FELDER)


@router.get("/partner/{nummer}")
def einzeln(nummer: int, k: Leitung):
    partner = hole(k, nummer)
    zeilen = k.db.scalars(
        select(Beleg)
        .where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.partner_id == partner.id,
            Beleg.status != "papierkorb",
            *belege.sichtfilter(k),
        )
        .order_by(Beleg.id.desc())
        .limit(30)
    )
    return auszug(partner, *FELDER) | {
        "belege": [auszug(b, "id", "art", "status", "nummer", "datum", "brutto", "waehrung") for b in zeilen],
        "verlauf": verlauf(k.db, "partner", partner.id),
    }


@router.patch("/partner/{nummer}")
def aendern(nummer: int, eingabe: Angaben, k: Buchhaltung):
    partner = hole(k, nummer)
    werte = pruefe(eingabe.model_dump(exclude_unset=True))
    neu = {f: w for f, w in werte.items() if getattr(partner, f) != w}
    alt = {f: getattr(partner, f) for f in neu}
    for feld, wert in neu.items():
        setattr(partner, feld, wert)
    if neu:
        protokolliere(k.db, "partner", partner, k.name, "geaendert", alt=alt, neu=neu)
        for beleg in k.db.scalars(
            select(Beleg).where(Beleg.partner_id == partner.id, Beleg.status == "neu", Beleg.art.in_(RECHNUNGEN))
        ):
            belege.bewerte(k.db, beleg)
        k.db.commit()
    return auszug(partner, *FELDER)


@router.get("/nachrichten")
def nachrichten(k: Leitung, grenze: Grenze = 100, ab: Ab = 0):
    zeilen = list(
        k.db.scalars(
            select(Nachricht)
            .where(Nachricht.mandant_id == k.mandant.id)
            .order_by(Nachricht.id.desc())
            .limit(grenze)
            .offset(ab)
        )
    )
    gesperrt = {
        s.wert for s in k.db.scalars(select(Sperre).where(Sperre.mandant_id == k.mandant.id, Sperre.art == "absender"))
    }
    dazu: dict[int, list] = {}
    for b in k.db.scalars(
        select(Beleg).where(Beleg.nachricht_id.in_([z.id for z in zeilen] or [-1]), *belege.sichtfilter(k))
    ):
        dazu.setdefault(b.nachricht_id, []).append(auszug(b, "id", "art", "status", "dateiname"))
    return [
        auszug(z, "id", "absender", "betreff", "text", "status", "empfangen_am")
        | {"belege": dazu.get(z.id, []), "gesperrt": z.absender in gesperrt}
        for z in zeilen
    ]
