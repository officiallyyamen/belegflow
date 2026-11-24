import calendar
import csv
import io
import re
import zipfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modelle import Anhang, Beleg, Benutzer, Erstattung, Erstattungsposten, Export, Partner, Rueckstellung, jetzt
from ..sicherheit import Kontext
from . import dateien
from .fehler import Konflikt, NichtGefunden, Ungueltig
from .protokoll import protokolliere
from .werte import RECHNUNGEN, als_betrag

CENT = Decimal("0.01")
FORMATE = {"csv": "Buchungen als CSV", "bmd": "BMD-Format", "zip": "ZIP mit Belegen"}
SPALTEN = (
    "Art",
    "Beleg",
    "Lieferant",
    "Kreditor",
    "UID",
    "Rechnungsnummer",
    "Rechnungsdatum",
    "Faellig",
    "Konto",
    "Kostenstelle",
    "Kostentraeger",
    "Steuersatz",
    "Netto",
    "USt",
    "Brutto",
    "Waehrung",
    "Buchungstext",
)
BMD_SPALTEN = (
    "satzart",
    "konto",
    "gkonto",
    "buchcode",
    "belegnr",
    "belegdatum",
    "buchdatum",
    "steuercode",
    "betrag",
    "prozent",
    "steuer",
    "buchsymbol",
    "extbelegnr",
    "gegenbuchkz",
    "verbuchkz",
    "kost",
    "zziel",
    "skontopz",
    "skontotage",
    "waehrung",
    "uidnr",
    "text",
    "document",
)


def zeilen_von(beleg: Beleg) -> list[dict]:
    if beleg.aufteilung:
        return [
            {
                "konto": z.get("konto") or beleg.konto,
                "kostenstelle": z.get("kostenstelle") or beleg.kostenstelle,
                "netto": als_betrag(z["netto"]),
                "satz": z.get("satz") or "0",
                "ust": (als_betrag(z["netto"]) * Decimal(z.get("satz") or "0") / 100).quantize(CENT, ROUND_HALF_UP),
                "text": z.get("text") or beleg.buchungstext,
            }
            for z in beleg.aufteilung
        ]
    if beleg.steuerzeilen:
        return [
            {
                "konto": beleg.konto,
                "kostenstelle": beleg.kostenstelle,
                "netto": als_betrag(z["netto"]),
                "satz": z["satz"],
                "ust": als_betrag(z["ust"]),
                "text": beleg.buchungstext,
            }
            for z in beleg.steuerzeilen
        ]
    ust = beleg.ust or Decimal(0)
    netto = beleg.netto if beleg.netto is not None else (beleg.brutto or Decimal(0)) - ust
    satz = str((ust * 100 / netto).quantize(Decimal(1), ROUND_HALF_UP)) if netto else "0"
    return [
        {
            "konto": beleg.konto,
            "kostenstelle": beleg.kostenstelle,
            "netto": netto,
            "satz": satz,
            "ust": ust,
            "text": beleg.buchungstext,
        }
    ]


def ausgleichen(zeilen: list[dict], brutto: Decimal | None) -> None:
    if brutto is None or not zeilen:
        return
    rest = brutto - sum(z["netto"] + z["ust"] for z in zeilen)
    if rest and abs(rest) <= Decimal("0.05"):
        zeilen[-1]["ust"] += rest


def buchung_beleg(db: Session, beleg: Beleg) -> dict:
    partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
    zeilen = zeilen_von(beleg)
    ausgleichen(zeilen, beleg.brutto)
    vorzeichen = -1 if beleg.art == "gutschrift" else 1
    for zeile in zeilen:
        zeile["netto"] *= vorzeichen
        zeile["ust"] *= vorzeichen
    return {
        "art": "beleg",
        "id": beleg.id,
        "name": partner.name if partner else beleg.lieferant,
        "kreditor": partner.kreditor if partner else None,
        "uid": beleg.lieferant_uid,
        "nummer": beleg.nummer,
        "datum": beleg.datum,
        "faellig_am": beleg.faellig_am,
        "skonto_prozent": beleg.skonto_prozent,
        "skonto_bis": beleg.skonto_bis,
        "kostentraeger": beleg.kostentraeger,
        "waehrung": beleg.waehrung,
        "datei": f"{beleg.id}{dateien.ENDUNGEN[beleg.dateityp]}",
        "zeilen": zeilen,
    }


def buchung_erstattung(db: Session, antrag: Erstattung, konto: str) -> dict:
    person = db.get(Benutzer, antrag.benutzer_id)
    posten = db.scalars(
        select(Erstattungsposten).where(
            Erstattungsposten.erstattung_id == antrag.id, Erstattungsposten.ausgeschlossen.is_(False)
        )
    )
    zeilen = []
    for p in posten:
        netto = p.betrag - p.ust
        zeilen.append(
            {
                "konto": p.konto or antrag.konto,
                "kostenstelle": p.kostenstelle or antrag.kostenstelle,
                "netto": netto,
                "satz": str((p.ust * 100 / netto).quantize(Decimal(1), ROUND_HALF_UP)) if netto and p.ust else "0",
                "ust": p.ust,
                "text": f"{person.name}: {p.titel}",
            }
        )
    return {
        "art": "erstattung",
        "id": antrag.id,
        "name": person.name,
        "kreditor": konto,
        "uid": None,
        "nummer": f"ERST-{antrag.id}",
        "datum": (antrag.freigegeben_am or antrag.erstellt_am).date(),
        "faellig_am": None,
        "skonto_prozent": None,
        "skonto_bis": None,
        "kostentraeger": None,
        "waehrung": "EUR",
        "datei": "",
        "zeilen": zeilen,
    }


def hindernis(buchung: dict) -> str | None:
    if not buchung["kreditor"]:
        return "Kreditorenkonto fehlt"
    if not buchung["datum"]:
        return "Rechnungsdatum fehlt"
    if not buchung["zeilen"]:
        return "Keine Positionen"
    if any(not z["konto"] for z in buchung["zeilen"]):
        return "Konto fehlt"
    if any(not z["kostenstelle"] for z in buchung["zeilen"]):
        return "Kostenstelle fehlt"
    return None


def wartende(k: Kontext) -> list[dict]:
    db = k.db
    ergebnis = [
        buchung_beleg(db, b)
        for b in db.scalars(
            select(Beleg)
            .where(Beleg.mandant_id == k.mandant.id, Beleg.status == "freigegeben", Beleg.art.in_(RECHNUNGEN))
            .order_by(Beleg.datum, Beleg.id)
        )
    ]
    konto = k.mandant.einstellungen.get("erstattung_konto", "3600")
    ergebnis += [
        buchung_erstattung(db, e, konto)
        for e in db.scalars(
            select(Erstattung).where(Erstattung.mandant_id == k.mandant.id, Erstattung.status == "freigegeben")
        )
    ]
    for buchung in ergebnis:
        buchung["hindernis"] = hindernis(buchung)
        buchung["brutto"] = sum((z["netto"] + z["ust"] for z in buchung["zeilen"]), Decimal(0))
    return ergebnis


def monatsende(periode: str) -> date:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periode):
        raise Ungueltig("Periode muss das Format JJJJ-MM haben")
    jahr, monat = (int(teil) for teil in periode.split("-"))
    return date(jahr, monat, calendar.monthrange(jahr, monat)[1])


def rueckstellungen(k: Kontext, periode: str) -> list[Beleg]:
    ende = monatsende(periode)
    schon = set(
        k.db.scalars(
            select(Rueckstellung.beleg_id).where(Rueckstellung.mandant_id == k.mandant.id, Rueckstellung.status == "gebucht")
        )
    )
    offen = k.db.scalars(
        select(Beleg)
        .where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.art == "rechnung",
            Beleg.status.in_(("neu", "freigabe")),
            Beleg.netto.is_not(None),
        )
        .order_by(Beleg.id)
    )
    ergebnis = []
    for beleg in offen:
        tag = beleg.leistung_bis or beleg.leistung_von or beleg.datum
        if tag and tag <= ende and beleg.id not in schon:
            ergebnis.append(beleg)
    return ergebnis


def aufloesungen(k: Kontext) -> list[tuple[Rueckstellung, Beleg]]:
    zeilen = k.db.execute(
        select(Rueckstellung, Beleg)
        .join(Beleg, Beleg.id == Rueckstellung.beleg_id)
        .where(
            Rueckstellung.mandant_id == k.mandant.id,
            Rueckstellung.status == "gebucht",
            Beleg.status.in_(("freigegeben", "exportiert", "abgelehnt", "papierkorb")),
        )
        .order_by(Rueckstellung.id)
    )
    return [(r, b) for r, b in zeilen]


def text(wert) -> str:
    inhalt = "" if wert is None else str(wert)
    return "'" + inhalt if inhalt[:1] in ("=", "+", "-", "@", "\t", "\r") else inhalt


def geld(wert) -> str:
    return "" if wert is None else str(Decimal(wert).quantize(CENT)).replace(".", ",")


def tag(wert) -> str:
    return wert.strftime("%d.%m.%Y") if wert else ""


def schreibe(spalten, zeilen) -> bytes:
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(spalten)
    schreiber.writerows(zeilen)
    return puffer.getvalue().encode()


def als_csv(buchungen: list[dict]) -> bytes:
    zeilen = []
    for b in buchungen:
        for z in b["zeilen"]:
            zeilen.append(
                [
                    b["art"],
                    b["id"],
                    text(b["name"]),
                    text(b["kreditor"]),
                    text(b["uid"]),
                    text(b["nummer"]),
                    tag(b["datum"]),
                    tag(b["faellig_am"]),
                    text(z["konto"]),
                    text(z["kostenstelle"]),
                    text(b["kostentraeger"]),
                    str(z["satz"]).replace(".", ","),
                    geld(z["netto"]),
                    geld(z["ust"]),
                    geld(z["netto"] + z["ust"]),
                    b["waehrung"],
                    text(z["text"]),
                ]
            )
    return b"\xef\xbb\xbf" + schreibe(SPALTEN, zeilen)


def feld(wert, laenge: int) -> str:
    return re.sub(r"[;\r\n\"]", " ", str(wert or ""))[:laenge].strip()


def bmd_zeile(**werte) -> list[str]:
    return [str(werte.get(name, "")) for name in BMD_SPALTEN]


def als_bmd(buchungen: list[dict]) -> bytes:
    zeilen = []
    for nummer, b in enumerate(buchungen, 1):
        summe = sum(z["netto"] + z["ust"] for z in b["zeilen"])
        gemeinsam = {
            "satzart": "0",
            "belegnr": str(b.get("belegnr") or nummer),
            "belegdatum": tag(b["datum"]),
            "buchdatum": tag(b["datum"]),
            "buchsymbol": b.get("symbol", "ER"),
            "extbelegnr": feld(b["nummer"], 35),
            "gegenbuchkz": "O",
            "verbuchkz": "A",
            "waehrung": b["waehrung"],
            "document": b["datei"],
        }
        bedingungen = {}
        if b["faellig_am"] and b["datum"]:
            bedingungen["zziel"] = max((b["faellig_am"] - b["datum"]).days, 0)
        if b["skonto_bis"] and b["skonto_prozent"] and b["datum"]:
            bedingungen |= {
                "skontopz": b["skonto_prozent"].replace(".", ","),
                "skontotage": max((b["skonto_bis"] - b["datum"]).days, 0),
            }
        zeilen.append(
            bmd_zeile(
                **gemeinsam,
                **bedingungen,
                konto=feld(b["kreditor"], 12),
                gkonto="0",
                buchcode="2" if summe >= 0 else "1",
                betrag=geld(-summe),
                uidnr=feld(b["uid"], 20),
                text=feld(b["name"], 40),
            )
        )
        for z in b["zeilen"]:
            steuer = bool(z["ust"])
            zeilen.append(
                bmd_zeile(
                    **gemeinsam,
                    konto=feld(z["konto"], 12),
                    gkonto=feld(b["kreditor"], 12),
                    buchcode="1" if z["netto"] >= 0 else "2",
                    steuercode="2" if steuer else "",
                    betrag=geld(z["netto"]),
                    prozent=str(z["satz"]).split(".")[0] if steuer else "",
                    steuer=geld(z["ust"]) if steuer else "",
                    kost=feld(z["kostenstelle"], 12),
                    text=feld(z["text"] or b["name"], 40),
                )
            )
    return "".join(line for line in schreibe(BMD_SPALTEN, zeilen).decode()).encode("cp1252", "replace")


def als_zip(db: Session, buchungen: list[dict]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("buchungen.csv", als_csv(buchungen))
        archiv.writestr("bmd.csv", als_bmd(buchungen))
        for b in buchungen:
            if b["art"] == "beleg":
                beleg = db.get(Beleg, b["id"])
                archiv.writestr(f"belege/{b['datei']}", dateien.pfad(beleg.sha256, beleg.dateityp).read_bytes())
                anhaenge = db.scalars(
                    select(Anhang).where(Anhang.objekt_art == "beleg", Anhang.objekt_id == beleg.id).order_by(Anhang.id)
                )
                for anhang in anhaenge:
                    name = f"belege/{beleg.id}_anhang{anhang.id}{dateien.ENDUNGEN[anhang.dateityp]}"
                    archiv.writestr(name, dateien.pfad(anhang.sha256, anhang.dateityp).read_bytes())
            else:
                for p in db.scalars(select(Erstattungsposten).where(Erstattungsposten.erstattung_id == b["id"])):
                    if p.sha256 and not p.ausgeschlossen:
                        name = f"erstattungen/{b['id']}_{p.id}{dateien.ENDUNGEN[p.dateityp]}"
                        archiv.writestr(name, dateien.pfad(p.sha256, p.dateityp).read_bytes())
    return puffer.getvalue()


def speichere(k: Kontext, format_name: str, inhalt: bytes, posten: list[dict], name: str) -> Export:
    typ = "application/zip" if format_name == "zip" else "text/csv"
    eintrag = Export(
        mandant_id=k.mandant.id,
        von=k.name,
        format=format_name,
        anzahl=len(posten),
        posten=posten,
        dateiname=name,
        sha256=dateien.ablegen(inhalt, typ),
    )
    k.db.add(eintrag)
    k.db.flush()
    return eintrag


def exportiere(k: Kontext, format_name: str, auswahl: list[dict] | None = None) -> Export:
    if format_name not in FORMATE:
        raise Ungueltig("Format gibt es nicht")
    gewaehlt = {(a["art"], a["id"]) for a in auswahl} if auswahl else None
    buchungen = [b for b in wartende(k) if not b["hindernis"] and (gewaehlt is None or (b["art"], b["id"]) in gewaehlt)]
    if not buchungen:
        raise Konflikt("Nichts bereit zum Export")
    for b in buchungen:
        b["belegnr"] = b["id"] if b["art"] == "beleg" else 800000 + b["id"]
    if format_name == "csv":
        inhalt = als_csv(buchungen)
    elif format_name == "bmd":
        inhalt = als_bmd(buchungen)
    else:
        inhalt = als_zip(k.db, buchungen)
    endung = "zip" if format_name == "zip" else "csv"
    name = f"belegflow_{format_name}_{jetzt():%Y%m%d_%H%M%S}.{endung}"
    eintrag = speichere(k, format_name, inhalt, [{"art": b["art"], "id": b["id"]} for b in buchungen], name)
    for b in buchungen:
        objekt = k.db.get(Beleg if b["art"] == "beleg" else Erstattung, b["id"])
        objekt.status = "exportiert"
        protokolliere(k.db, b["art"], objekt, k.name, "exportiert", export=eintrag.id, format=format_name)
    k.db.commit()
    return eintrag


def exportiere_rueckstellungen(k: Kontext, periode: str) -> Export:
    ende = monatsende(periode)
    konto = k.mandant.einstellungen.get("rueckstellung_konto", "3070")
    neu, zurueck, buchungen = rueckstellungen(k, periode), aufloesungen(k), []
    if not neu and not zurueck:
        raise Konflikt("Keine Rückstellungen und keine Auflösungen")

    def buchung(beleg: Beleg, betrag: Decimal, aufwand: str | None, tag_: date, name: str, symbol: str) -> dict:
        return {
            "art": "rueckstellung",
            "id": beleg.id,
            "name": name,
            "kreditor": konto,
            "uid": None,
            "nummer": beleg.nummer or f"B{beleg.id}",
            "datum": tag_,
            "faellig_am": None,
            "skonto_prozent": None,
            "skonto_bis": None,
            "kostentraeger": None,
            "waehrung": beleg.waehrung,
            "datei": "",
            "symbol": symbol,
            "belegnr": 900000 + beleg.id,
            "zeilen": [
                {
                    "konto": aufwand or beleg.konto or "7900",
                    "kostenstelle": beleg.kostenstelle or "",
                    "netto": betrag,
                    "satz": "0",
                    "ust": Decimal(0),
                    "text": name,
                }
            ],
        }

    posten = []
    for beleg in neu:
        name = f"Rückstellung {beleg.lieferant or ''}".strip()
        buchungen.append(buchung(beleg, beleg.netto, None, ende, name, "SO"))
        posten.append({"art": "rueckstellung", "id": beleg.id})
        k.db.add(
            Rueckstellung(
                mandant_id=k.mandant.id, beleg_id=beleg.id, periode=periode, betrag=beleg.netto, konto=beleg.konto or "7900"
            )
        )
        protokolliere(k.db, "beleg", beleg, k.name, "rueckgestellt", periode=periode, betrag=beleg.netto)
    for eintrag, beleg in zurueck:
        name = f"Auflösung {beleg.lieferant or ''}".strip()
        buchungen.append(buchung(beleg, -eintrag.betrag, eintrag.konto, date.today(), name, "SO"))
        posten.append({"art": "aufloesung", "id": beleg.id})
        eintrag.status = "aufgeloest"
        protokolliere(k.db, "beleg", beleg, k.name, "aufgeloest", periode=eintrag.periode, betrag=eintrag.betrag)
    eintrag = speichere(k, "bmd", als_bmd(buchungen), posten, f"belegflow_rueckstellungen_{periode}.csv")
    k.db.commit()
    return eintrag


def exportiere_stammdaten(k: Kontext) -> Export:
    partner = list(k.db.scalars(select(Partner).where(Partner.mandant_id == k.mandant.id).order_by(Partner.kreditor)))
    if not partner:
        raise Konflikt("Keine Geschäftspartner vorhanden")
    spalten = ("Konto", "Name", "Strasse", "PLZ", "Ort", "UID", "IBAN", "Zahlungsziel", "SkontoProzent", "SkontoTage")
    zeilen = [
        [
            text(p.kreditor),
            text(p.name),
            text(p.strasse),
            text(p.plz),
            text(p.ort),
            text(p.uid),
            text(p.ibans[-1] if p.ibans else ""),
            p.zahlungsziel if p.zahlungsziel is not None else "",
            text((p.skonto_prozent or "").replace(".", ",")),
            p.skonto_tage if p.skonto_tage is not None else "",
        ]
        for p in partner
    ]
    inhalt = b"\xef\xbb\xbf" + schreibe(spalten, zeilen)
    posten = [{"art": "partner", "id": p.id} for p in partner]
    eintrag = speichere(k, "stammdaten", inhalt, posten, f"belegflow_stammdaten_{jetzt():%Y%m%d_%H%M%S}.csv")
    k.db.commit()
    return eintrag


def hole(k: Kontext, nummer: int) -> Export:
    eintrag = k.db.get(Export, nummer)
    if not eintrag or eintrag.mandant_id != k.mandant.id:
        raise NichtGefunden("Export nicht gefunden")
    return eintrag
