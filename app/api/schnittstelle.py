from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import Field
from sqlalchemy import select, update

from ..dienste import erinnerung, export, post
from ..dienste.protokoll import beim_mandanten
from ..dienste.werte import als_kennung
from ..modelle import Beleg, Benutzer, Mitglied, Mitteilung, Partner, Stammwert
from ..sicherheit import Eingang, Schnittstelle
from .einstellungen import Rolle, Stammart
from .gemeinsam import Eingabe, Grenze, auszug, einfach, lies_datei, zeichen

router = APIRouter(prefix="/api/m/{mandant_id}/schnittstelle", tags=["Schnittstelle"])


class Zugestellt(Eingabe):
    nummern: Annotated[list[int], Field(min_length=1, max_length=200)]


class Stammzeile(Eingabe):
    art: Stammart
    code: zeichen(80, 1)
    name: zeichen(200, 1)


class Stammliste(Eingabe):
    werte: Annotated[list[Stammzeile], Field(min_length=1, max_length=2000)]


class PartnerZeile(Eingabe):
    kreditor: zeichen(20, 1)
    name: zeichen(255, 2)
    uid: zeichen(20) | None = None
    strasse: zeichen(200) | None = None
    plz: zeichen(10) | None = None
    ort: zeichen(100) | None = None
    zahlungsziel: Annotated[int, Field(ge=0, le=365)] | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None


class PartnerListe(Eingabe):
    partner: Annotated[list[PartnerZeile], Field(min_length=1, max_length=2000)]


class PersonZeile(Eingabe):
    email: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)]
    rollen: list[Rolle] = ["mitarbeit"]
    aktiv: bool = True


class PersonListe(Eingabe):
    personen: Annotated[list[PersonZeile], Field(min_length=1, max_length=500)]


@router.post("/belege", status_code=201)
def beleg_einreichen(
    k: Eingang,
    kennung: Annotated[str, Form(max_length=300)] = "",
    absender: Annotated[str, Form(max_length=300)] = "",
    betreff: Annotated[str, Form(max_length=500)] = "",
    inhalt: Annotated[str, Form(max_length=20000)] = "",
    datei: Annotated[UploadFile | None, File()] = None,
):
    gelesen = lies_datei(datei) if datei else None
    kopf = {"kennung": kennung, "absender": absender, "betreff": betreff, "text": inhalt}
    return einfach(post.nimm_an(k, {n: w.replace("\x00", "") for n, w in kopf.items()}, gelesen))


@router.get("/mitteilungen")
def mitteilungen(k: Schnittstelle, grenze: Grenze = 100):
    zeilen = k.db.execute(
        select(Mitteilung, Benutzer.name, Benutzer.email)
        .join(Benutzer, Benutzer.id == Mitteilung.benutzer_id)
        .where(Mitteilung.mandant_id == k.mandant.id, Mitteilung.zugestellt.is_(False), Benutzer.aktiv.is_(True))
        .order_by(Mitteilung.id)
        .limit(grenze)
    )
    return [auszug(m, "id", "text", "ziel", "erstellt_am") | {"name": name, "email": email} for m, name, email in zeilen]


@router.post("/mitteilungen/zugestellt", status_code=204)
def zugestellt(eingabe: Zugestellt, k: Schnittstelle):
    k.db.execute(
        update(Mitteilung)
        .where(Mitteilung.mandant_id == k.mandant.id, Mitteilung.id.in_(eingabe.nummern))
        .values(zugestellt=True)
    )
    k.db.commit()


@router.get("/erinnerungen")
def erinnerungen(k: Schnittstelle):
    return einfach(erinnerung.faellige(k))


@router.get("/buchungen")
def buchungen(k: Schnittstelle, seit: date | None = None, grenze: Annotated[int, Query(ge=1, le=500)] = 200):
    bedingungen = [
        Beleg.mandant_id == k.mandant.id,
        Beleg.status.in_(("freigegeben", "exportiert")),
        Beleg.art.in_(("rechnung", "gutschrift")),
    ]
    if seit:
        bedingungen.append(Beleg.datum >= seit)
    zeilen = k.db.scalars(select(Beleg).where(*bedingungen).order_by(Beleg.id).limit(grenze))
    return einfach([export.buchung_beleg(k.db, b) | {"status": b.status} for b in zeilen])


@router.put("/stammdaten")
def stammdaten(eingabe: Stammliste, k: Schnittstelle):
    vorhanden = {(s.art, s.code): s for s in k.db.scalars(select(Stammwert).where(Stammwert.mandant_id == k.mandant.id))}
    neu = 0
    for zeile in eingabe.werte:
        schluessel = (zeile.art, zeile.code)
        if schluessel in vorhanden:
            vorhanden[schluessel].name = zeile.name
        else:
            vorhanden[schluessel] = Stammwert(mandant_id=k.mandant.id, **zeile.model_dump())
            k.db.add(vorhanden[schluessel])
            neu += 1
    beim_mandanten(k.db, k.mandant, k.name, "stammdaten_importiert", neu=neu, gesamt=len(eingabe.werte))
    k.db.commit()
    return {"neu": neu, "geaendert": len(eingabe.werte) - neu}


@router.put("/partner")
def partner(eingabe: PartnerListe, k: Schnittstelle):
    vorhanden = {
        p.kreditor: p for p in k.db.scalars(select(Partner).where(Partner.mandant_id == k.mandant.id)) if p.kreditor
    }
    neu = 0
    for zeile in eingabe.partner:
        werte = zeile.model_dump(exclude_unset=True) | {"uid": als_kennung(zeile.uid, 20)}
        if zeile.kreditor in vorhanden:
            for name, wert in werte.items():
                if wert is not None:
                    setattr(vorhanden[zeile.kreditor], name, wert)
        else:
            vorhanden[zeile.kreditor] = Partner(mandant_id=k.mandant.id, **werte)
            k.db.add(vorhanden[zeile.kreditor])
            neu += 1
    beim_mandanten(k.db, k.mandant, k.name, "partner_importiert", neu=neu, gesamt=len(eingabe.partner))
    k.db.commit()
    return {"neu": neu, "geaendert": len(eingabe.partner) - neu}


@router.put("/personen")
def personen(eingabe: PersonListe, k: Schnittstelle):
    ergebnis = {"aufgenommen": 0, "entfernt": 0, "unbekannt": []}
    for zeile in eingabe.personen:
        benutzer = k.db.scalar(select(Benutzer).where(Benutzer.email == zeile.email.lower()))
        if not benutzer:
            ergebnis["unbekannt"].append(zeile.email)
            continue
        mitglied = k.db.get(Mitglied, (k.mandant.id, benutzer.id))
        erlaubt = sorted(set(zeile.rollen) - {"admin"})
        if zeile.aktiv and not mitglied and erlaubt:
            k.db.add(Mitglied(mandant_id=k.mandant.id, benutzer_id=benutzer.id, rollen=erlaubt))
            ergebnis["aufgenommen"] += 1
        elif not zeile.aktiv and mitglied and "admin" not in mitglied.rollen:
            k.db.delete(mitglied)
            ergebnis["entfernt"] += 1
    beim_mandanten(k.db, k.mandant, k.name, "personen_importiert", **ergebnis)
    k.db.commit()
    return ergebnis
