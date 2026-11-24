import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

ARTEN = (
    "rechnung",
    "gutschrift",
    "angebot",
    "auftragsbestaetigung",
    "bestellung",
    "lieferschein",
    "vertrag",
    "ausgangsrechnung",
    "sonstiges",
)
RECHNUNGEN = ("rechnung", "gutschrift")
HOECHSTBETRAG = Decimal("20000000")


class Steuerzeile(BaseModel):
    satz: str
    netto: str
    ust: str


class Position(BaseModel):
    nummer: str | None = None
    text: str | None = None
    menge: str | None = None
    einheit: str | None = None
    einzelpreis: str | None = None
    netto: str | None = None
    satz: str | None = None


class Rechnung(BaseModel):
    art: str | None = None
    lieferant: str | None = None
    lieferant_adresse: str | None = None
    lieferant_uid: str | None = None
    empfaenger: str | None = None
    empfaenger_adresse: str | None = None
    empfaenger_uid: str | None = None
    nummer: str | None = None
    datum: str | None = None
    leistung_von: str | None = None
    leistung_bis: str | None = None
    faellig_am: str | None = None
    skonto_bis: str | None = None
    skonto_prozent: str | None = None
    bestellnummer: str | None = None
    iban: str | None = None
    bic: str | None = None
    waehrung: str | None = None
    steuerzeilen: list[Steuerzeile] = []
    netto: str | None = None
    ust: str | None = None
    brutto: str | None = None
    positionen: list[Position] = []


def als_zahl(wert) -> Decimal | None:
    try:
        zahl = Decimal(str(wert)) if wert not in (None, "") else None
    except InvalidOperation:
        return None
    if zahl is None or not zahl.is_finite() or abs(zahl) > HOECHSTBETRAG:
        return None
    return zahl


def als_betrag(wert) -> Decimal | None:
    zahl = als_zahl(wert)
    return None if zahl is None else zahl.quantize(Decimal("0.01"))


def als_datum(wert) -> date | None:
    if isinstance(wert, date):
        return wert
    for muster in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime((wert or "")[:10].strip(), muster).date()
        except ValueError:
            continue
    return None


def als_kennung(wert: str | None, laenge: int) -> str | None:
    return re.sub(r"[^A-Z0-9]", "", wert.upper())[:laenge] or None if wert else None


def als_text(wert: str | None, laenge: int) -> str | None:
    return " ".join(wert.split())[:laenge] or None if wert else None


def kurz(zahl: Decimal) -> str:
    return format(zahl.normalize(), "f")


def steuer(zeilen) -> list[dict]:
    ergebnis = []
    for zeile in zeilen[:10]:
        satz, netto, ust = als_zahl(zeile.satz), als_betrag(zeile.netto), als_betrag(zeile.ust)
        if None not in (satz, netto, ust):
            ergebnis.append({"satz": kurz(satz), "netto": str(netto), "ust": str(ust)})
    return ergebnis


def posten(zeilen) -> list[dict]:
    ergebnis = []
    for zeile in zeilen[:200]:
        menge, einzel, netto, satz = (als_zahl(getattr(zeile, n)) for n in ("menge", "einzelpreis", "netto", "satz"))
        ergebnis.append(
            {
                "nummer": als_text(zeile.nummer, 60),
                "text": als_text(zeile.text, 200) or "",
                "menge": kurz(menge) if menge is not None else None,
                "einheit": als_text(zeile.einheit, 12),
                "einzelpreis": kurz(einzel) if einzel is not None else None,
                "netto": str(als_betrag(netto)) if netto is not None else None,
                "satz": kurz(satz) if satz is not None else None,
            }
        )
    return ergebnis


def felder(r: Rechnung) -> dict:
    waehrung = als_kennung(r.waehrung, 3)
    prozent = als_zahl(r.skonto_prozent)
    return {
        "lieferant": als_text(r.lieferant, 255),
        "lieferant_adresse": als_text(r.lieferant_adresse, 300),
        "lieferant_uid": als_kennung(r.lieferant_uid, 20),
        "empfaenger": als_text(r.empfaenger, 255),
        "empfaenger_adresse": als_text(r.empfaenger_adresse, 300),
        "empfaenger_uid": als_kennung(r.empfaenger_uid, 20),
        "nummer": als_text(r.nummer, 80),
        "datum": als_datum(r.datum),
        "leistung_von": als_datum(r.leistung_von),
        "leistung_bis": als_datum(r.leistung_bis) or als_datum(r.leistung_von),
        "faellig_am": als_datum(r.faellig_am),
        "skonto_bis": als_datum(r.skonto_bis),
        "skonto_prozent": kurz(prozent)[:6] if prozent and 0 < prozent < 100 else None,
        "bestellnummer": als_text(r.bestellnummer, 80),
        "iban": als_kennung(r.iban, 40),
        "bic": als_kennung(r.bic, 11),
        "waehrung": waehrung if waehrung and len(waehrung) == 3 else "EUR",
        "steuerzeilen": steuer(r.steuerzeilen),
        "positionen": posten(r.positionen),
        "netto": als_betrag(r.netto),
        "ust": als_betrag(r.ust),
        "brutto": als_betrag(r.brutto),
    }


def normal(text: str | None) -> str:
    text = (text or "").lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("strasse", "str"), ("str.", "str")):
        text = text.replace(alt, neu)
    return re.sub(r"[^a-z0-9]", "", text)
