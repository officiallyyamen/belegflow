import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modelle import Mitteilung, Protokoll, jetzt

ANFANG = "0" * 64
FELDER = ("mandant_id", "objekt_art", "objekt_id", "wer", "aktion", "details", "zeitpunkt")


def summe(vorgaenger: str, eintrag: dict) -> str:
    text = json.dumps(eintrag, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((vorgaenger + text).encode()).hexdigest()


def inhalt(eintrag: Protokoll) -> dict:
    return {name: getattr(eintrag, name) for name in FELDER}


def protokolliere(db: Session, objekt_art: str, objekt, wer: str, aktion: str, /, **details) -> Protokoll:
    db.flush()
    letzter = db.scalar(
        select(Protokoll)
        .where(Protokoll.mandant_id == objekt.mandant_id)
        .order_by(Protokoll.id.desc())
        .limit(1)
        .with_for_update()
    )
    eintrag = Protokoll(
        mandant_id=objekt.mandant_id,
        objekt_art=objekt_art,
        objekt_id=objekt.id,
        wer=wer,
        aktion=aktion,
        details=json.loads(json.dumps(details, default=str)),
        zeitpunkt=jetzt().isoformat(),
        vorgaenger=letzter.pruefsumme if letzter else ANFANG,
    )
    eintrag.pruefsumme = summe(eintrag.vorgaenger, inhalt(eintrag))
    db.add(eintrag)
    db.flush()
    return eintrag


def beim_mandanten(db: Session, mandant, wer: str, aktion: str, /, **details) -> Protokoll:
    return protokolliere(db, "mandant", SimpleNamespace(id=mandant.id, mandant_id=mandant.id), wer, aktion, **details)


def gueltig(db: Session, mandant_id: int) -> tuple[bool, int | None]:
    vorgaenger = ANFANG
    for eintrag in db.scalars(select(Protokoll).where(Protokoll.mandant_id == mandant_id).order_by(Protokoll.id)):
        if eintrag.vorgaenger != vorgaenger or eintrag.pruefsumme != summe(vorgaenger, inhalt(eintrag)):
            return False, eintrag.id
        vorgaenger = eintrag.pruefsumme
    return True, None


def verlauf(db: Session, objekt_art: str, objekt_id: int) -> list[dict]:
    abfrage = (
        select(Protokoll)
        .where(Protokoll.objekt_art == objekt_art, Protokoll.objekt_id == objekt_id)
        .order_by(Protokoll.id.desc())
    )
    return [
        {"id": e.id, "wer": e.wer, "aktion": e.aktion, "details": e.details, "zeitpunkt": e.zeitpunkt}
        for e in db.scalars(abfrage)
    ]


def mitteilen(db: Session, mandant_id: int, empfaenger, text: str, ziel: str, ausser: int | None = None) -> None:
    for benutzer_id in dict.fromkeys(empfaenger):
        if benutzer_id and benutzer_id != ausser:
            db.add(Mitteilung(mandant_id=mandant_id, benutzer_id=benutzer_id, text=text[:300], ziel=ziel))
