import csv
import hashlib
import io
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from ..modelle import Beleg, Benutzer, Karte, Mitglied, Transaktion
from ..sicherheit import Kontext
from . import belege
from .erkennung import partner_name
from .fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from .protokoll import beim_mandanten, mitteilen, protokolliere
from .werte import als_betrag, als_datum, normal

SPALTEN = ("karte", "datum", "haendler", "betrag")
STATUS = ("beantragt", "aktiv", "gesperrt", "abgelehnt")


def sichtfilter(k: Kontext) -> list:
    return [] if k.sieht_alles else [Karte.inhaber_id == k.id]


def hole(k: Kontext, nummer: int) -> Karte:
    karte = k.db.scalar(select(Karte).where(Karte.id == nummer, Karte.mandant_id == k.mandant.id, *sichtfilter(k)))
    if not karte:
        raise NichtGefunden("Karte nicht gefunden")
    return karte


def hole_transaktion(k: Kontext, nummer: int) -> Transaktion:
    transaktion = k.db.scalar(
        select(Transaktion)
        .join(Karte, Karte.id == Transaktion.karte_id)
        .where(Transaktion.id == nummer, Transaktion.mandant_id == k.mandant.id, *sichtfilter(k))
    )
    if not transaktion:
        raise NichtGefunden("Transaktion nicht gefunden")
    return transaktion


def alle(k: Kontext) -> list[Karte]:
    return list(
        k.db.scalars(select(Karte).where(Karte.mandant_id == k.mandant.id, *sichtfilter(k)).order_by(Karte.name, Karte.id))
    )


def eigene(k: Kontext) -> list[Karte]:
    return list(
        k.db.scalars(
            select(Karte).where(
                Karte.mandant_id == k.mandant.id, Karte.inhaber_id == k.id, Karte.status.in_(("aktiv", "gesperrt"))
            )
        )
    )


def ausgegeben(k: Kontext, karte: Karte, monat: date) -> Decimal:
    beginn = monat.replace(day=1)
    ende = (beginn + timedelta(days=32)).replace(day=1)
    summe = k.db.scalar(
        select(func.sum(Transaktion.betrag)).where(
            Transaktion.karte_id == karte.id, Transaktion.datum >= beginn, Transaktion.datum < ende
        )
    )
    return summe or Decimal(0)


def ausgabe(k: Kontext, karte: Karte) -> dict:
    heute = date.today()
    fehlt = k.db.scalar(
        select(func.count()).select_from(Transaktion).where(Transaktion.karte_id == karte.id, Transaktion.status == "fehlt")
    )
    return {
        "id": karte.id,
        "name": karte.name,
        "art": karte.art,
        "status": karte.status,
        "letzte4": karte.letzte4,
        "inhaber_id": karte.inhaber_id,
        "inhaber": k.db.get(Benutzer, karte.inhaber_id).name,
        "limit_monat": str(karte.limit_monat),
        "limit_zahlung": str(karte.limit_zahlung) if karte.limit_zahlung is not None else None,
        "gueltig_bis": karte.gueltig_bis.isoformat() if karte.gueltig_bis else None,
        "konto": karte.konto,
        "kostenstelle": karte.kostenstelle,
        "grund": karte.grund,
        "ausgegeben": str(ausgegeben(k, karte, heute)),
        "fehlende_belege": fehlt,
    }


def anlegen(k: Kontext, werte: dict) -> Karte:
    verwaltet = k.hat("buchhaltung", "admin")
    inhaber = werte.pop("inhaber_id", None) or k.id
    if inhaber != k.id and not verwaltet:
        raise Verboten("Karten für andere darf nur die Buchhaltung anlegen")
    if not k.db.get(Mitglied, (k.mandant.id, inhaber)):
        raise Ungueltig("Person gehört nicht zu diesem Mandanten")
    if not verwaltet:
        werte = {f: w for f, w in werte.items() if f in ("name", "art", "limit_monat", "limit_zahlung", "grund")}
    karte = Karte(mandant_id=k.mandant.id, inhaber_id=inhaber, status="aktiv" if verwaltet else "beantragt", **werte)
    k.db.add(karte)
    protokolliere(k.db, "karte", karte, k.name, "angelegt" if verwaltet else "beantragt", name=karte.name)
    if not verwaltet:
        buchhaltung = [
            m.benutzer_id
            for m in k.db.scalars(select(Mitglied).where(Mitglied.mandant_id == k.mandant.id))
            if "buchhaltung" in m.rollen
        ]
        mitteilen(k.db, k.mandant.id, buchhaltung, f"{k.name} beantragt die Karte {karte.name}", "karten", k.id)
    k.db.commit()
    return karte


def aendern(k: Kontext, karte: Karte, werte: dict) -> None:
    neu = {f: w for f, w in werte.items() if getattr(karte, f) != w}
    if neu.get("status") == "aktiv" and not (neu.get("letzte4") or karte.letzte4):
        raise Konflikt("Vor dem Aktivieren die letzten vier Stellen der Karte eintragen")
    for feld, wert in neu.items():
        setattr(karte, feld, wert)
    if not neu:
        return
    protokolliere(k.db, "karte", karte, k.name, "geaendert", neu=neu)
    if "status" in neu:
        mitteilen(k.db, k.mandant.id, [karte.inhaber_id], f"Karte {karte.name} ist jetzt {karte.status}", "karten", k.id)
    k.db.commit()


def geld(text: str) -> Decimal | None:
    text = text.strip().replace(" ", "").replace(" ", "").replace("'", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return als_betrag(text)


def lies_csv(inhalt: bytes) -> list[dict]:
    try:
        text = inhalt.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = inhalt.decode("cp1252", "replace")
    text = text.replace("\x00", "")
    trenner = ";" if ";" in text.split("\n", 1)[0] else ","
    leser = csv.DictReader(io.StringIO(text), delimiter=trenner)
    namen = {normal(n): n for n in leser.fieldnames or []}
    fehlt = [s for s in SPALTEN if s not in namen]
    if fehlt:
        raise Ungueltig(f"Spalten fehlen: {', '.join(fehlt)}")
    return [{kurzname: (zeile[name] or "").strip() for kurzname, name in namen.items()} for zeile in leser]


def importiere(k: Kontext, inhalt: bytes) -> dict:
    db = k.db
    karten = {karte.letzte4: karte for karte in alle(k) if karte.letzte4}
    ergebnis = {"neu": 0, "bekannt": 0, "zugeordnet": 0, "uebersprungen": []}
    gesehen: Counter = Counter()
    for nummer, zeile in enumerate(lies_csv(inhalt), 2):
        karte = karten.get(zeile["karte"][-4:])
        datum, betrag = als_datum(zeile["datum"]), geld(zeile["betrag"])
        if not karte or not datum or betrag is None:
            grund = "Karte unbekannt" if not karte else "Datum oder Betrag unlesbar"
            ergebnis["uebersprungen"].append(f"Zeile {nummer}: {grund}")
            continue
        schluessel = f"{zeile['karte'][-4:]}|{datum}|{zeile['haendler']}|{betrag}"
        gesehen[schluessel] += 1
        kennung = zeile.get("kennung") or hashlib.sha256(f"{schluessel}|{gesehen[schluessel]}".encode()).hexdigest()[:40]
        if db.scalar(select(Transaktion.id).where(Transaktion.mandant_id == k.mandant.id, Transaktion.kennung == kennung)):
            ergebnis["bekannt"] += 1
            continue
        transaktion = Transaktion(
            mandant_id=k.mandant.id,
            karte_id=karte.id,
            kennung=kennung[:120],
            datum=datum,
            haendler=zeile["haendler"][:200],
            betrag=betrag,
            waehrung=(zeile.get("waehrung") or "EUR").upper()[:3],
        )
        db.add(transaktion)
        db.flush()
        ergebnis["neu"] += 1
        sicher = [b for b, gleich in vorschlaege(k, transaktion) if gleich]
        if len(sicher) == 1:
            verbinde(k, transaktion, sicher[0], "Erkennung")
            ergebnis["zugeordnet"] += 1
    beim_mandanten(db, k.mandant, k.name, "transaktionen_importiert", **ergebnis)
    db.commit()
    return ergebnis


def vorschlaege(k: Kontext, transaktion: Transaktion) -> list[tuple[Beleg, bool]]:
    belegt = select(Transaktion.beleg_id).where(Transaktion.beleg_id.is_not(None))
    haendler = normal(transaktion.haendler)
    ergebnis = []
    for beleg in k.db.scalars(
        select(Beleg).where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.art == "rechnung",
            Beleg.status.not_in(("papierkorb", "abgelehnt")),
            Beleg.zahlstatus == "offen",
            Beleg.brutto == transaktion.betrag,
            Beleg.waehrung == transaktion.waehrung,
            Beleg.datum.between(transaktion.datum - timedelta(days=10), transaktion.datum + timedelta(days=10)),
            Beleg.id.not_in(belegt),
        )
    ):
        name = partner_name(beleg.lieferant)
        ergebnis.append((beleg, bool(name) and (name in haendler or haendler in name)))
    return sorted(ergebnis, key=lambda paar: not paar[1])


def verbinde(k: Kontext, transaktion: Transaktion, beleg: Beleg, wer: str) -> None:
    db = k.db
    if transaktion.beleg_id:
        raise Konflikt("Transaktion hat schon einen Beleg")
    if db.scalar(select(Transaktion.id).where(Transaktion.beleg_id == beleg.id)):
        raise Konflikt("Beleg gehört schon zu einer anderen Transaktion")
    if beleg.art != "rechnung" or beleg.zahlstatus not in ("offen", "keine"):
        raise Konflikt("Beleg ist keine offene Rechnung")
    karte = db.get(Karte, transaktion.karte_id)
    transaktion.beleg_id, transaktion.status = beleg.id, "zugeordnet"
    beleg.zahlstatus = "karte"
    if beleg.status == "neu":
        for feld in ("konto", "kostenstelle"):
            if not getattr(beleg, feld) and getattr(karte, feld):
                setattr(beleg, feld, getattr(karte, feld))
                beleg.erkannt = beleg.erkannt | {feld: "Karte"}
        belege.bewerte(db, beleg)
    protokolliere(
        db,
        "beleg",
        beleg,
        wer,
        "karte_zugeordnet",
        karte=karte.name,
        haendler=transaktion.haendler,
        betrag=transaktion.betrag,
    )


def zuordnen(k: Kontext, transaktion: Transaktion, beleg: Beleg) -> None:
    if not k.hat("buchhaltung", "admin") and beleg.hochgeladen_von != k.id:
        raise Verboten("Nur eigene Belege lassen sich zuordnen")
    verbinde(k, transaktion, beleg, k.name)
    k.db.commit()


def loese(k: Kontext, transaktion: Transaktion) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf das ändern")
    beleg = k.db.get(Beleg, transaktion.beleg_id) if transaktion.beleg_id else None
    if not beleg:
        raise Konflikt("Transaktion hat keinen Beleg")
    if beleg.status in ("freigegeben", "exportiert"):
        raise Konflikt("Beleg ist schon freigegeben")
    transaktion.beleg_id, transaktion.status = None, "fehlt"
    beleg.zahlstatus = "offen"
    protokolliere(k.db, "beleg", beleg, k.name, "karte_geloest", haendler=transaktion.haendler)
    k.db.commit()


def ohne_beleg(k: Kontext, transaktion: Transaktion, grund: str) -> None:
    if transaktion.status != "fehlt":
        raise Konflikt("Transaktion ist schon erledigt")
    transaktion.status = "ohne_beleg"
    karte = k.db.get(Karte, transaktion.karte_id)
    protokolliere(
        k.db, "karte", karte, k.name, "ohne_beleg", haendler=transaktion.haendler, betrag=transaktion.betrag, grund=grund
    )
    k.db.commit()


def hinweise(k: Kontext, transaktion: Transaktion) -> list[str]:
    karte = k.db.get(Karte, transaktion.karte_id)
    ergebnis = []
    if karte.limit_zahlung is not None and transaktion.betrag > karte.limit_zahlung:
        ergebnis.append("Über dem Limit pro Zahlung")
    if ausgegeben(k, karte, transaktion.datum) > karte.limit_monat:
        ergebnis.append("Monatslimit überschritten")
    if transaktion.beleg_id:
        beleg = k.db.get(Beleg, transaktion.beleg_id)
        if beleg.brutto is not None and beleg.brutto != transaktion.betrag:
            ergebnis.append("Betrag weicht vom Beleg ab")
    return ergebnis
