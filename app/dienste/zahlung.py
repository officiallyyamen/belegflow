import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy import select

from ..modelle import Beleg, Benutzer, Erstattung, Mandant, Partner, Zahlung, jetzt
from ..sicherheit import Kontext
from . import erstattung as erstattungen
from .fehler import Konflikt, NichtGefunden, Ungueltig
from .protokoll import protokolliere
from .pruefung import iban_gueltig

NAMENSRAUM = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
ZAHLBAR = ("freigegeben", "exportiert")
UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "&": "+", "€": "EUR"})


def sepa_text(text: str | None, laenge: int) -> str:
    sauber = re.sub(r"[^A-Za-z0-9/\-?:().,'+ ]", " ", (text or "").translate(UMLAUTE))
    return " ".join(sauber.split())[:laenge] or "NOTPROVIDED"


def skontobetrag(beleg: Beleg, tag: date) -> Decimal | None:
    if not (beleg.skonto_bis and beleg.skonto_prozent and beleg.brutto) or beleg.skonto_bis < tag:
        return None
    faktor = 1 - Decimal(beleg.skonto_prozent) / 100
    return (beleg.brutto * faktor).quantize(Decimal("0.01"), ROUND_HALF_UP)


def offene(k: Kontext) -> list[dict]:
    db, heute, ergebnis = k.db, date.today(), []
    belege = db.scalars(
        select(Beleg)
        .where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.art == "rechnung",
            Beleg.status.in_(ZAHLBAR),
            Beleg.zahlstatus == "offen",
        )
        .order_by(Beleg.faellig_am.is_(None), Beleg.faellig_am, Beleg.id)
    )
    for beleg in belege:
        partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
        hindernis = None
        if not beleg.iban or not iban_gueltig(beleg.iban):
            hindernis = "IBAN fehlt oder ist ungültig"
        elif beleg.waehrung != "EUR":
            hindernis = f"Währung {beleg.waehrung} geht nicht über SEPA"
        mit_skonto = skontobetrag(beleg, heute)
        ergebnis.append(
            {
                "art": "beleg",
                "id": beleg.id,
                "name": partner.name if partner else beleg.lieferant,
                "nummer": beleg.nummer,
                "iban": beleg.iban,
                "faellig_am": beleg.faellig_am,
                "betrag": str(beleg.brutto),
                "skonto_bis": beleg.skonto_bis,
                "skonto_betrag": str(mit_skonto) if mit_skonto is not None else None,
                "status": beleg.status,
                "hindernis": hindernis,
            }
        )
    for antrag in db.scalars(
        select(Erstattung).where(
            Erstattung.mandant_id == k.mandant.id, Erstattung.status.in_(ZAHLBAR), Erstattung.zahlstatus == "offen"
        )
    ):
        person = db.get(Benutzer, antrag.benutzer_id)
        iban = antrag.iban or person.iban
        ergebnis.append(
            {
                "art": "erstattung",
                "id": antrag.id,
                "name": person.name,
                "nummer": antrag.titel,
                "iban": iban,
                "faellig_am": None,
                "betrag": str(erstattungen.summe(antrag)),
                "skonto_bis": None,
                "skonto_betrag": None,
                "status": antrag.status,
                "hindernis": None if iban and iban_gueltig(iban) else "IBAN fehlt oder ist ungültig",
            }
        )
    return ergebnis


def unter(eltern, weg: str, text: str | None = None):
    knoten = eltern
    for teil in weg.split("/"):
        knoten = SubElement(knoten, teil)
    if text is not None:
        knoten.text = text
    return knoten


def erzeuge_xml(mandant: Mandant, kennung: str, posten: list[dict], ausfuehrung: date) -> str:
    summe = str(sum(Decimal(p["betrag"]) for p in posten))
    wurzel = Element("Document", {"xmlns": NAMENSRAUM})
    auftrag = unter(wurzel, "CstmrCdtTrfInitn")
    kopf = unter(auftrag, "GrpHdr")
    unter(kopf, "MsgId", kennung)
    unter(kopf, "CreDtTm", jetzt().strftime("%Y-%m-%dT%H:%M:%SZ"))
    unter(kopf, "NbOfTxs", str(len(posten)))
    unter(kopf, "CtrlSum", summe)
    unter(kopf, "InitgPty/Nm", sepa_text(mandant.name, 70))
    block = unter(auftrag, "PmtInf")
    unter(block, "PmtInfId", f"{kennung}-1"[:35])
    unter(block, "PmtMtd", "TRF")
    unter(block, "NbOfTxs", str(len(posten)))
    unter(block, "CtrlSum", summe)
    unter(block, "PmtTpInf/SvcLvl/Cd", "SEPA")
    unter(block, "ReqdExctnDt/Dt", ausfuehrung.isoformat())
    unter(block, "Dbtr/Nm", sepa_text(mandant.name, 70))
    unter(block, "DbtrAcct/Id/IBAN", mandant.iban)
    if mandant.bic:
        unter(block, "DbtrAgt/FinInstnId/BICFI", mandant.bic)
    else:
        unter(block, "DbtrAgt/FinInstnId/Othr/Id", "NOTPROVIDED")
    unter(block, "ChrgBr", "SLEV")
    for p in posten:
        ueberweisung = unter(block, "CdtTrfTxInf")
        unter(ueberweisung, "PmtId/EndToEndId", sepa_text(p["kennung"], 35))
        unter(ueberweisung, "Amt/InstdAmt", p["betrag"]).set("Ccy", "EUR")
        unter(ueberweisung, "Cdtr/Nm", sepa_text(p["name"], 70))
        unter(ueberweisung, "CdtrAcct/Id/IBAN", p["iban"])
        unter(ueberweisung, "RmtInf/Ustrd", sepa_text(p["zweck"], 140))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(wurzel, encoding="unicode")


def zahle(k: Kontext, auswahl: list[dict], ausfuehrung: date) -> Zahlung:
    db, mandant = k.db, k.mandant
    if not mandant.iban or not iban_gueltig(mandant.iban):
        raise Konflikt("In den Einstellungen fehlt die eigene IBAN")
    if ausfuehrung < date.today():
        raise Ungueltig("Ausführung darf nicht in der Vergangenheit liegen")
    verfuegbar = {(p["art"], p["id"]): p for p in offene(k)}
    posten, objekte = [], []
    for wahl in auswahl:
        eintrag = verfuegbar.pop((wahl["art"], wahl["id"]), None)
        if not eintrag:
            raise Konflikt("Ein Vorgang ist nicht mehr offen")
        if eintrag["hindernis"]:
            raise Konflikt(f"{eintrag['name']}: {eintrag['hindernis']}")
        objekt = db.get(Beleg if wahl["art"] == "beleg" else Erstattung, wahl["id"])
        betrag = eintrag["betrag"]
        if wahl.get("skonto"):
            gekuerzt = skontobetrag(objekt, ausfuehrung) if wahl["art"] == "beleg" else None
            if gekuerzt is None:
                raise Konflikt(f"{eintrag['name']}: Skonto ist an diesem Tag nicht mehr möglich")
            betrag = str(gekuerzt)
        if Decimal(betrag) <= 0:
            raise Konflikt(f"{eintrag['name']}: Betrag ist nicht positiv")
        zweck = f"Rechnung {eintrag['nummer']}" if wahl["art"] == "beleg" else f"Erstattung {eintrag['nummer']}"
        posten.append(
            {
                "art": wahl["art"],
                "id": wahl["id"],
                "name": eintrag["name"],
                "iban": eintrag["iban"],
                "betrag": betrag,
                "zweck": zweck,
                "kennung": eintrag["nummer"] or f"{wahl['art']}-{wahl['id']}",
            }
        )
        objekte.append((wahl["art"], objekt, betrag))
    if not posten:
        raise Ungueltig("Bitte mindestens einen Vorgang auswählen")
    summe = sum(Decimal(p["betrag"]) for p in posten)
    lauf = Zahlung(mandant_id=mandant.id, von=k.name, ausfuehrung=ausfuehrung, summe=summe, posten=posten, xml="")
    db.add(lauf)
    db.flush()
    lauf.xml = erzeuge_xml(mandant, f"BF{mandant.id}-{lauf.id}-{jetzt():%Y%m%d}", posten, ausfuehrung)
    for art, objekt, betrag in objekte:
        objekt.zahlstatus = "bezahlt"
        protokolliere(db, art, objekt, k.name, "bezahlt", betrag=betrag, zahlung=lauf.id)
    db.commit()
    return lauf


def hole(k: Kontext, nummer: int) -> Zahlung:
    lauf = k.db.get(Zahlung, nummer)
    if not lauf or lauf.mandant_id != k.mandant.id:
        raise NichtGefunden("Zahlung nicht gefunden")
    return lauf


def ohne_zahlung(k: Kontext, beleg: Beleg, grund: str) -> None:
    if beleg.zahlstatus != "offen":
        raise Konflikt("Beleg ist nicht zur Zahlung offen")
    beleg.zahlstatus = "keine"
    protokolliere(k.db, "beleg", beleg, k.name, "keine_zahlung", grund=grund)
    k.db.commit()
