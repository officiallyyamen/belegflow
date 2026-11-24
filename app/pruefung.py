import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import einstellungen
from .db import Beleg

CENT = Decimal("0.01")
KLEINBETRAG = Decimal("400.00")


def hinweis(code: str, stufe: str, text: str) -> dict:
    return {"code": code, "stufe": stufe, "text": text}


def uid_gueltig(uid: str) -> bool:
    if not re.fullmatch(r"ATU\d{8}", uid):
        return False
    ziffern = [int(zeichen) for zeichen in uid[3:]]
    summe = 0
    for stelle, ziffer in enumerate(ziffern[:7]):
        summe += ziffer if stelle % 2 == 0 else ziffer // 5 + (ziffer * 2) % 10
    return (10 - (summe + 4) % 10) % 10 == ziffern[7]


def iban_gueltig(iban: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    if iban.startswith("AT") and len(iban) != 20:
        return False
    umgestellt = iban[4:] + iban[:4]
    return int("".join(str(int(zeichen, 36)) for zeichen in umgestellt)) % 97 == 1


def pflichtfelder(beleg: Beleg) -> list[dict]:
    noetig = {
        "lieferant": "Lieferant",
        "rechnungsdatum": "Rechnungsdatum",
        "brutto": "Gesamtbetrag",
    }
    if beleg.brutto is None or beleg.brutto > KLEINBETRAG:
        noetig |= {
            "lieferant_uid": "UID des Lieferanten",
            "empfaenger": "Empfänger",
            "rechnungsnummer": "Rechnungsnummer",
            "netto": "Nettobetrag",
            "ust": "Umsatzsteuer",
        }
    return [
        hinweis("pflichtfeld", "fehler", f"{name} fehlt") for feld, name in noetig.items() if getattr(beleg, feld) is None
    ]


def betraege(beleg: Beleg) -> list[dict]:
    ergebnis = []
    if None not in (beleg.netto, beleg.ust, beleg.brutto) and abs(beleg.netto + beleg.ust - beleg.brutto) > CENT:
        ergebnis.append(hinweis("summe", "fehler", "Netto plus Umsatzsteuer ergibt nicht den Gesamtbetrag"))
    erlaubt = {Decimal(satz) for satz in einstellungen().steuersaetze}
    for zeile in beleg.steuerzeilen:
        satz, netto, ust = Decimal(zeile["satz"]), Decimal(zeile["netto"]), Decimal(zeile["ust"])
        if satz not in erlaubt:
            ergebnis.append(hinweis("steuersatz", "warnung", f"Steuersatz {zeile['satz']} % ist nicht hinterlegt"))
        soll = (netto * satz / 100).quantize(CENT, ROUND_HALF_UP)
        if abs(soll - ust) > Decimal("0.02"):
            ergebnis.append(hinweis("steuer", "fehler", f"Umsatzsteuer zu {zeile['satz']} % ist falsch berechnet"))
    if beleg.steuerzeilen and beleg.netto is not None and beleg.ust is not None:
        netto = sum(Decimal(zeile["netto"]) for zeile in beleg.steuerzeilen)
        ust = sum(Decimal(zeile["ust"]) for zeile in beleg.steuerzeilen)
        if abs(netto - beleg.netto) > CENT or abs(ust - beleg.ust) > CENT:
            ergebnis.append(hinweis("steuerzeilen", "fehler", "Steuerzeilen passen nicht zu den Summen"))
    if beleg.waehrung != "EUR":
        ergebnis.append(hinweis("waehrung", "warnung", f"Währung ist {beleg.waehrung}"))
    return ergebnis


def kennungen(beleg: Beleg) -> list[dict]:
    ergebnis = []
    if beleg.lieferant_uid:
        if beleg.lieferant_uid.startswith("AT"):
            if not uid_gueltig(beleg.lieferant_uid):
                ergebnis.append(hinweis("uid", "fehler", "UID-Nummer ist ungültig"))
        else:
            ergebnis.append(hinweis("uid_ausland", "warnung", "Ausländische UID, Reverse Charge prüfen"))
    if beleg.iban and not iban_gueltig(beleg.iban):
        ergebnis.append(hinweis("iban", "fehler", "IBAN ist ungültig"))
    if not beleg.iban:
        ergebnis.append(hinweis("iban_fehlt", "warnung", "Keine IBAN gefunden"))
    return ergebnis


def termine(beleg: Beleg, heute: date) -> list[dict]:
    ergebnis = []
    if beleg.rechnungsdatum and beleg.rechnungsdatum > heute:
        ergebnis.append(hinweis("datum_zukunft", "fehler", "Rechnungsdatum liegt in der Zukunft"))
    if beleg.rechnungsdatum and beleg.rechnungsdatum < heute - timedelta(days=365):
        ergebnis.append(hinweis("datum_alt", "warnung", "Rechnung ist älter als ein Jahr"))
    if beleg.faellig_am and beleg.rechnungsdatum and beleg.faellig_am < beleg.rechnungsdatum:
        ergebnis.append(hinweis("faellig", "warnung", "Fälligkeit liegt vor dem Rechnungsdatum"))
    return ergebnis


def gleicher_lieferant(beleg: Beleg):
    if beleg.lieferant_uid:
        return Beleg.lieferant_uid == beleg.lieferant_uid
    return Beleg.lieferant == beleg.lieferant


def historie(beleg: Beleg, db: Session) -> list[dict]:
    ergebnis = []
    if not (beleg.lieferant_uid or beleg.lieferant):
        return ergebnis
    if beleg.rechnungsnummer:
        doppelt = db.scalar(
            select(Beleg.id).where(
                gleicher_lieferant(beleg),
                Beleg.rechnungsnummer == beleg.rechnungsnummer,
                Beleg.status != "abgelehnt",
                Beleg.id != beleg.id,
                or_(Beleg.id < beleg.id, Beleg.status.in_(("freigegeben", "exportiert"))),
            )
        )
        if doppelt:
            ergebnis.append(hinweis("duplikat", "fehler", f"Rechnungsnummer existiert schon bei Beleg {doppelt}"))
    if beleg.iban:
        bekannt = db.scalar(
            select(Beleg.iban)
            .where(
                gleicher_lieferant(beleg),
                Beleg.status.in_(("freigegeben", "exportiert")),
                Beleg.iban.is_not(None),
                Beleg.id != beleg.id,
            )
            .order_by(Beleg.id.desc())
            .limit(1)
        )
        if bekannt and bekannt != beleg.iban:
            stufe = "warnung" if beleg.bestaetigte_iban == beleg.iban else "fehler"
            ergebnis.append(hinweis("iban_neu", stufe, "IBAN weicht von der letzten freigegebenen Rechnung ab"))
    return ergebnis


def pruefe(beleg: Beleg, db: Session, heute: date | None = None) -> list[dict]:
    return [
        *pflichtfelder(beleg),
        *betraege(beleg),
        *kennungen(beleg),
        *termine(beleg, heute or date.today()),
        *historie(beleg, db),
    ]
