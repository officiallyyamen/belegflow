from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import httpx2
from defusedxml.ElementTree import fromstring
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import einstellungen
from ..modelle import Kurs
from .fehler import Ungueltig

EZB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
TAGE = 90


def lade() -> bytes:
    antwort = httpx2.get(EZB, timeout=15)
    antwort.raise_for_status()
    return antwort.content


def uebernimm(db: Session, inhalt: bytes) -> None:
    for tag in fromstring(inhalt, forbid_dtd=True).iter():
        if "time" not in tag.attrib:
            continue
        datum = date.fromisoformat(tag.attrib["time"])
        for eintrag in tag:
            if not db.get(Kurs, (eintrag.attrib["currency"], datum)):
                db.add(Kurs(waehrung=eintrag.attrib["currency"], datum=datum, kurs=eintrag.attrib["rate"]))
    db.flush()


def suche(db: Session, waehrung: str, tag: date) -> Kurs | None:
    return db.scalar(
        select(Kurs)
        .where(Kurs.waehrung == waehrung, Kurs.datum <= tag, Kurs.datum >= tag - timedelta(days=7))
        .order_by(Kurs.datum.desc())
        .limit(1)
    )


def kurs(db: Session, waehrung: str, tag: date) -> Decimal:
    if waehrung == "EUR":
        return Decimal(1)
    gefunden = suche(db, waehrung, tag)
    if not gefunden and einstellungen().wechselkurse and tag >= date.today() - timedelta(days=TAGE):
        try:
            uebernimm(db, lade())
        except (httpx2.HTTPError, ValueError) as fehler:
            raise Ungueltig("Wechselkurs ist nicht abrufbar, bitte selbst eintragen") from fehler
        gefunden = suche(db, waehrung, tag)
    if not gefunden:
        raise Ungueltig("Für dieses Datum gibt es keinen Wechselkurs, bitte selbst eintragen")
    return Decimal(gefunden.kurs)


def in_euro(betrag: Decimal, kurswert: Decimal) -> Decimal:
    if kurswert <= 0:
        raise Ungueltig("Wechselkurs muss größer als null sein")
    return (betrag / kurswert).quantize(Decimal("0.01"), ROUND_HALF_UP)
