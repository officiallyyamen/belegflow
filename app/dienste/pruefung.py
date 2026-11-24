import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import einstellungen
from ..modelle import Beleg, Mandant, Partner, Sperre
from .werte import RECHNUNGEN, normal

CENT = Decimal("0.01")
KLEINBETRAG = Decimal("400.00")
UID_GRENZE = Decimal("10000.00")
FERTIG = ("freigegeben", "exportiert")
RANG = {"ok": 0, "warnung": 1, "fehler": 2, "sperre": 3}


def punkt(gruppe: str, code: str, stufe: str, text: str, erwartet=None, vorhanden=None) -> dict:
    eintrag = {"gruppe": gruppe, "code": code, "stufe": stufe, "text": text}
    if erwartet is not None:
        eintrag |= {"erwartet": str(erwartet), "vorhanden": str(vorhanden or "nichts gefunden")}
    return eintrag


def uid_gueltig(uid: str) -> bool:
    if not uid.startswith("AT"):
        return bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{2,12}", uid))
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


def vorhanden(gruppe: str, code: str, wert, name: str, stufe: str = "fehler") -> dict:
    if wert in (None, "", []):
        return punkt(gruppe, code, stufe, f"{name} fehlt")
    return punkt(gruppe, code, "ok", f"{name} vorhanden")


def empfaenger(beleg: Beleg, mandant: Mandant, klein: bool) -> list[dict]:
    if klein:
        return [punkt("Empfänger", "klein", "ok", "Kleinbetragsrechnung bis 400 Euro, Empfänger muss nicht angegeben sein")]
    ergebnis = []
    eigen = normal(beleg.text) + normal(beleg.empfaenger) + normal(beleg.empfaenger_adresse)
    if normal(mandant.name) in eigen:
        ergebnis.append(punkt("Empfänger", "empfaenger_name", "ok", "Name des Empfängers stimmt"))
    else:
        ergebnis.append(
            punkt(
                "Empfänger", "empfaenger_name", "fehler", "Name des Empfängers stimmt nicht", mandant.name, beleg.empfaenger
            )
        )
    anschrift = beleg.empfaenger_adresse
    for code, name, wert in (
        ("empfaenger_strasse", "Straße", mandant.strasse),
        ("empfaenger_plz", "Postleitzahl", mandant.plz),
        ("empfaenger_ort", "Ort", mandant.ort),
    ):
        if not wert:
            continue
        if normal(wert) in eigen:
            ergebnis.append(punkt("Empfänger", code, "ok", f"{name} des Empfängers stimmt"))
        else:
            ergebnis.append(punkt("Empfänger", code, "warnung", f"{name} des Empfängers stimmt nicht", wert, anschrift))
    if beleg.brutto is not None and beleg.brutto > UID_GRENZE:
        if not beleg.empfaenger_uid:
            ergebnis.append(
                punkt("Empfänger", "empfaenger_uid", "fehler", "Über 10.000 Euro muss die eigene UID angegeben sein")
            )
        elif mandant.uid and beleg.empfaenger_uid != mandant.uid:
            ergebnis.append(
                punkt("Empfänger", "empfaenger_uid", "fehler", "Eigene UID stimmt nicht", mandant.uid, beleg.empfaenger_uid)
            )
        else:
            ergebnis.append(punkt("Empfänger", "empfaenger_uid", "ok", "Eigene UID vorhanden"))
    return ergebnis


def lieferant(beleg: Beleg, klein: bool) -> list[dict]:
    ergebnis = [
        vorhanden("Lieferant", "lieferant", beleg.lieferant, "Name des Lieferanten", "sperre"),
        vorhanden("Lieferant", "lieferant_adresse", beleg.lieferant_adresse, "Anschrift des Lieferanten", "warnung"),
    ]
    if beleg.lieferant_uid:
        gut = uid_gueltig(beleg.lieferant_uid)
        ergebnis.append(
            punkt(
                "Lieferant", "uid", "ok" if gut else "fehler", "UID-Nummer ist gültig" if gut else "UID-Nummer ist ungültig"
            )
        )
        if not beleg.lieferant_uid.startswith("AT"):
            ergebnis.append(punkt("Lieferant", "uid_ausland", "warnung", "Ausländische UID, Reverse Charge prüfen"))
    elif not klein:
        ergebnis.append(punkt("Lieferant", "uid", "fehler", "UID-Nummer fehlt"))
    return ergebnis


def angaben(beleg: Beleg, klein: bool, heute: date) -> list[dict]:
    ergebnis = [vorhanden("Rechnung", "datum", beleg.datum, "Rechnungsdatum", "sperre")]
    if not klein:
        ergebnis.append(vorhanden("Rechnung", "nummer", beleg.nummer, "Rechnungsnummer"))
    ergebnis.append(
        vorhanden("Rechnung", "leistung", beleg.leistung_von, "Leistungsdatum oder Leistungszeitraum", "warnung")
    )
    ergebnis.append(
        vorhanden("Rechnung", "beschreibung", beleg.positionen or beleg.text.strip(), "Menge und Bezeichnung", "warnung")
    )
    if beleg.datum and beleg.datum > heute:
        ergebnis.append(punkt("Rechnung", "datum_zukunft", "fehler", "Rechnungsdatum liegt in der Zukunft"))
    if beleg.datum and beleg.datum < heute - timedelta(days=365):
        ergebnis.append(punkt("Rechnung", "datum_alt", "warnung", "Rechnung ist älter als ein Jahr"))
    if beleg.faellig_am and beleg.datum and beleg.faellig_am < beleg.datum:
        ergebnis.append(punkt("Rechnung", "faellig", "warnung", "Fälligkeit liegt vor dem Rechnungsdatum"))
    return ergebnis


def betraege(beleg: Beleg, klein: bool) -> list[dict]:
    ergebnis = [vorhanden("Beträge", "brutto", beleg.brutto, "Gesamtbetrag", "sperre")]
    if not klein:
        ergebnis.append(vorhanden("Beträge", "netto", beleg.netto, "Nettobetrag"))
        ergebnis.append(vorhanden("Beträge", "ust", beleg.ust, "Steuerbetrag"))
    if None not in (beleg.netto, beleg.ust, beleg.brutto):
        soll = beleg.netto + beleg.ust
        if abs(soll - beleg.brutto) > CENT:
            ergebnis.append(
                punkt("Beträge", "summe", "sperre", "Netto plus Steuer ergibt nicht den Gesamtbetrag", soll, beleg.brutto)
            )
        else:
            ergebnis.append(punkt("Beträge", "summe", "ok", "Summe stimmt"))
    erlaubt = {Decimal(satz) for satz in einstellungen().steuersaetze}
    for zeile in beleg.steuerzeilen:
        satz, netto, ust = Decimal(zeile["satz"]), Decimal(zeile["netto"]), Decimal(zeile["ust"])
        if satz not in erlaubt:
            ergebnis.append(punkt("Beträge", "steuersatz", "warnung", f"Steuersatz {zeile['satz']} % ist nicht hinterlegt"))
        soll = (netto * satz / 100).quantize(CENT, ROUND_HALF_UP)
        if abs(soll - ust) > Decimal("0.02"):
            ergebnis.append(punkt("Beträge", "steuer", "sperre", f"Steuer zu {zeile['satz']} % ist falsch", soll, ust))
        else:
            ergebnis.append(punkt("Beträge", "steuer", "ok", f"Steuer zu {zeile['satz']} % stimmt"))
    if beleg.steuerzeilen and None not in (beleg.netto, beleg.ust):
        netto = sum(Decimal(zeile["netto"]) for zeile in beleg.steuerzeilen)
        ust = sum(Decimal(zeile["ust"]) for zeile in beleg.steuerzeilen)
        if abs(netto - beleg.netto) > CENT or abs(ust - beleg.ust) > CENT:
            ergebnis.append(punkt("Beträge", "steuerzeilen", "sperre", "Steuerzeilen passen nicht zu den Summen"))
    if beleg.aufteilung:
        summe = sum(Decimal(zeile["netto"]) for zeile in beleg.aufteilung)
        if beleg.netto is None or abs(summe - beleg.netto) > CENT:
            ergebnis.append(
                punkt("Beträge", "aufteilung", "sperre", "Aufteilung ergibt nicht den Nettobetrag", beleg.netto, summe)
            )
    if beleg.waehrung != "EUR":
        ergebnis.append(punkt("Beträge", "waehrung", "warnung", f"Währung ist {beleg.waehrung}"))
    return ergebnis


def gleicher_lieferant(beleg: Beleg):
    if beleg.partner_id:
        return Beleg.partner_id == beleg.partner_id
    if beleg.lieferant_uid:
        return Beleg.lieferant_uid == beleg.lieferant_uid
    return Beleg.lieferant == beleg.lieferant


def duplikate(db: Session, beleg: Beleg) -> list[Beleg]:
    if not (beleg.partner_id or beleg.lieferant_uid or beleg.lieferant):
        return []
    gleich = []
    if beleg.nummer:
        gleich.append(Beleg.nummer == beleg.nummer)
    elif beleg.datum and beleg.brutto is not None:
        gleich.append((Beleg.datum == beleg.datum) & (Beleg.brutto == beleg.brutto))
    if not gleich:
        return []
    abfrage = select(Beleg).where(
        Beleg.mandant_id == beleg.mandant_id,
        Beleg.art == beleg.art,
        Beleg.id != beleg.id,
        Beleg.status.not_in(("papierkorb", "abgelehnt")),
        gleicher_lieferant(beleg),
        or_(*gleich),
        or_(Beleg.id < beleg.id, Beleg.status.in_(FERTIG)),
    )
    return list(db.scalars(abfrage.order_by(Beleg.id)))


def risiko(beleg: Beleg, db: Session) -> list[dict]:
    ergebnis = []
    if not beleg.iban:
        ergebnis.append(punkt("Risiko", "iban_fehlt", "warnung", "Keine IBAN gefunden"))
    elif not iban_gueltig(beleg.iban):
        ergebnis.append(punkt("Risiko", "iban", "fehler", "IBAN ist ungültig"))
    else:
        ergebnis.append(punkt("Risiko", "iban", "ok", "IBAN ist gültig"))
        gesperrt = db.scalar(
            select(Sperre).where(Sperre.mandant_id == beleg.mandant_id, Sperre.art == "iban", Sperre.wert == beleg.iban)
        )
        if gesperrt:
            grund = f": {gesperrt.grund}" if gesperrt.grund else ""
            ergebnis.append(punkt("Risiko", "iban_gesperrt", "sperre", f"IBAN steht auf der Sperrliste{grund}"))
        land = (beleg.lieferant_uid or "")[:2]
        if land and land != beleg.iban[:2]:
            ergebnis.append(
                punkt("Risiko", "iban_land", "warnung", "Land der IBAN passt nicht zur UID", land, beleg.iban[:2])
            )
        partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
        bekannt = partner.ibans if partner else []
        if not bekannt and (beleg.lieferant_uid or beleg.lieferant):
            letzte = db.scalar(
                select(Beleg.iban)
                .where(
                    Beleg.mandant_id == beleg.mandant_id,
                    gleicher_lieferant(beleg),
                    Beleg.status.in_(FERTIG),
                    Beleg.iban.is_not(None),
                    Beleg.id != beleg.id,
                )
                .order_by(Beleg.id.desc())
                .limit(1)
            )
            bekannt = [letzte] if letzte else []
        if bekannt and beleg.iban not in bekannt:
            bestaetigt = beleg.bestaetigte_iban == beleg.iban
            ergebnis.append(
                punkt(
                    "Risiko",
                    "iban_neu",
                    "warnung" if bestaetigt else "sperre",
                    "Neue IBAN wurde bestätigt" if bestaetigt else "IBAN ist für diesen Lieferanten neu",
                    bekannt[-1],
                    beleg.iban,
                )
            )
    if not beleg.kein_duplikat:
        for doppelt in duplikate(db, beleg)[:1]:
            ergebnis.append(punkt("Risiko", "duplikat", "sperre", f"Mögliches Duplikat von Beleg {doppelt.id}"))
    return ergebnis


def pruefe(beleg: Beleg, db: Session, heute: date | None = None) -> list[dict]:
    if beleg.art not in RECHNUNGEN:
        return []
    mandant = db.get(Mandant, beleg.mandant_id)
    klein = beleg.brutto is not None and beleg.brutto <= KLEINBETRAG
    return [
        *risiko(beleg, db),
        *empfaenger(beleg, mandant, klein),
        *lieferant(beleg, klein),
        *angaben(beleg, klein, heute or date.today()),
        *betraege(beleg, klein),
    ]


def hoechste(bericht: list[dict]) -> str:
    return max((eintrag["stufe"] for eintrag in bericht), key=RANG.get, default="ok")
