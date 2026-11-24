import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Benutzer, einstellungen
from .db import Beleg, Protokoll
from .extraktion import ExtraktionsFehler, als_kennung, extraktor, felder, leere_rechnung
from .pruefung import gleicher_lieferant, hinweis, pruefe

SIGNATUREN = {
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
}
OFFEN = ("pruefen", "bereit")


class Konflikt(Exception):
    def __init__(self, text: str, beleg_id: int | None = None):
        super().__init__(text)
        self.beleg_id = beleg_id


class Ungueltig(Exception):
    pass


def erkenne_typ(inhalt: bytes) -> tuple[str, str]:
    for signatur, typ in SIGNATUREN.items():
        if inhalt.startswith(signatur):
            return typ
    raise Ungueltig("Nur PDF, PNG und JPEG sind erlaubt")


def summe(vorgaenger: str, eintrag: dict) -> str:
    inhalt = json.dumps(eintrag, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((vorgaenger + inhalt).encode()).hexdigest()


def eintrag_daten(eintrag: Protokoll) -> dict:
    return {
        "beleg_id": eintrag.beleg_id,
        "benutzer": eintrag.benutzer,
        "aktion": eintrag.aktion,
        "details": eintrag.details,
        "zeitpunkt": eintrag.zeitpunkt,
    }


def protokolliere(db: Session, beleg: Beleg, benutzer: str, aktion: str, **details) -> None:
    letzter = db.scalar(select(Protokoll).order_by(Protokoll.id.desc()).limit(1).with_for_update())
    eintrag = Protokoll(
        beleg_id=beleg.id,
        benutzer=benutzer,
        aktion=aktion,
        details=json.loads(json.dumps(details, default=str)),
        zeitpunkt=datetime.now(UTC).isoformat(),
        vorgaenger=letzter.pruefsumme if letzter else "0" * 64,
    )
    eintrag.pruefsumme = summe(eintrag.vorgaenger, eintrag_daten(eintrag))
    db.add(eintrag)
    db.flush()


def protokoll_gueltig(db: Session) -> tuple[bool, int | None]:
    vorgaenger = "0" * 64
    for eintrag in db.scalars(select(Protokoll).order_by(Protokoll.id)):
        if eintrag.vorgaenger != vorgaenger or eintrag.pruefsumme != summe(vorgaenger, eintrag_daten(eintrag)):
            return False, eintrag.id
        vorgaenger = eintrag.pruefsumme
    return True, None


def bewerte(beleg: Beleg, db: Session, zusatz: list[dict] | None = None) -> None:
    beleg.hinweise = [*(zusatz or []), *pruefe(beleg, db)]
    beleg.status = "pruefen" if any(eintrag["stufe"] == "fehler" for eintrag in beleg.hinweise) else "bereit"


def konto_vorschlag(beleg: Beleg, db: Session) -> None:
    if not (beleg.lieferant_uid or beleg.lieferant):
        return
    letzter = db.scalar(
        select(Beleg)
        .where(gleicher_lieferant(beleg), Beleg.status.in_(("freigegeben", "exportiert")), Beleg.id != beleg.id)
        .order_by(Beleg.id.desc())
        .limit(1)
    )
    if letzter:
        beleg.konto, beleg.kostenstelle = letzter.konto, letzter.kostenstelle


def nimm_auf(db: Session, dateiname: str, inhalt: bytes, benutzer: Benutzer) -> Beleg:
    if not inhalt:
        raise Ungueltig("Datei ist leer")
    if len(inhalt) > einstellungen().max_mb * 1024 * 1024:
        raise Ungueltig(f"Datei ist größer als {einstellungen().max_mb} MB")
    typ, endung = erkenne_typ(inhalt)
    pruefwert = hashlib.sha256(inhalt).hexdigest()
    vorhanden = db.scalar(select(Beleg.id).where(Beleg.sha256 == pruefwert))
    if vorhanden:
        raise Konflikt("Diese Datei wurde bereits erfasst", vorhanden)

    leser = extraktor()
    zusatz = []
    try:
        rechnung = leser.lies(inhalt, typ)
    except ExtraktionsFehler as fehler:
        rechnung = leere_rechnung()
        zusatz = [hinweis("extraktion", "fehler", str(fehler))]

    ordner = einstellungen().speicher
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{pruefwert}{endung}").write_bytes(inhalt)

    beleg = Beleg(
        dateiname=dateiname[:255],
        dateityp=typ,
        sha256=pruefwert,
        status="pruefen",
        extraktor=leser.name,
        hinweise=[],
        **felder(rechnung),
    )
    db.add(beleg)
    try:
        db.flush()
    except IntegrityError as fehler:
        db.rollback()
        raise Konflikt("Diese Datei wurde bereits erfasst") from fehler
    konto_vorschlag(beleg, db)
    bewerte(beleg, db, zusatz)
    protokolliere(db, beleg, benutzer.name, "erfasst", extraktor=leser.name, status=beleg.status)
    db.commit()
    return beleg


def korrigiere(db: Session, beleg: Beleg, werte: dict, benutzer: Benutzer) -> Beleg:
    if beleg.status not in OFFEN:
        raise Konflikt("Beleg ist nicht mehr offen")
    alt, neu = {}, {}
    for feld, wert in werte.items():
        if feld == "steuerzeilen":
            wert = wert or []
        if feld in ("iban", "lieferant_uid"):
            wert = als_kennung(wert, 40 if feld == "iban" else 20)
        if getattr(beleg, feld) != wert:
            alt[feld], neu[feld] = getattr(beleg, feld), wert
            setattr(beleg, feld, wert)
    if neu:
        beleg.bearbeitet_von = benutzer.name
        bewerte(beleg, db)
        protokolliere(db, beleg, benutzer.name, "korrigiert", alt=alt, neu=neu, status=beleg.status)
        db.commit()
    return beleg


def gib_frei(db: Session, beleg: Beleg, benutzer: Benutzer) -> Beleg:
    if beleg.status not in OFFEN:
        raise Konflikt("Beleg ist nicht mehr offen")
    bewerte(beleg, db, [eintrag for eintrag in beleg.hinweise if eintrag["code"] == "extraktion"])
    if beleg.status != "bereit":
        db.commit()
        raise Konflikt("Beleg hat offene Fehler")
    if beleg.bearbeitet_von == benutzer.name:
        raise Konflikt("Wer korrigiert hat, darf nicht selbst freigeben")
    if not (beleg.konto and beleg.kostenstelle):
        raise Konflikt("Konto und Kostenstelle fehlen")
    beleg.status = "freigegeben"
    beleg.freigegeben_von = benutzer.name
    protokolliere(db, beleg, benutzer.name, "freigegeben", brutto=beleg.brutto or Decimal(0))
    db.commit()
    return beleg


def bestaetige_iban(db: Session, beleg: Beleg, grund: str, benutzer: Benutzer) -> Beleg:
    if beleg.status not in OFFEN:
        raise Konflikt("Beleg ist nicht mehr offen")
    if not any(eintrag["code"] == "iban_neu" for eintrag in beleg.hinweise):
        raise Konflikt("Bei diesem Beleg gibt es keine neue IBAN")
    if beleg.bearbeitet_von == benutzer.name:
        raise Konflikt("Wer korrigiert hat, darf die IBAN nicht bestätigen")
    beleg.bestaetigte_iban = beleg.iban
    bewerte(beleg, db, [eintrag for eintrag in beleg.hinweise if eintrag["code"] == "extraktion"])
    protokolliere(db, beleg, benutzer.name, "iban_bestaetigt", iban=beleg.iban, grund=grund)
    db.commit()
    return beleg


def lehne_ab(db: Session, beleg: Beleg, grund: str, benutzer: Benutzer) -> Beleg:
    if beleg.status not in OFFEN:
        raise Konflikt("Beleg ist nicht mehr offen")
    beleg.status = "abgelehnt"
    protokolliere(db, beleg, benutzer.name, "abgelehnt", grund=grund)
    db.commit()
    return beleg
