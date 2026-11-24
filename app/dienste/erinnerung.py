from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_, select

from ..modelle import Beleg, Benutzer, Freigabeschritt, Karte, Transaktion, Vertrag, jetzt
from ..sicherheit import Kontext
from . import freigabe


def offene_freigaben(k: Kontext) -> dict[int, list[str]]:
    tage = k.mandant.einstellungen.get("erinnerung_tage", 3)
    ergebnis = defaultdict(list)
    for schritt in k.db.scalars(
        select(Freigabeschritt).where(
            Freigabeschritt.mandant_id == k.mandant.id,
            Freigabeschritt.status == "offen",
            Freigabeschritt.erstellt_am <= jetzt() - timedelta(days=tage),
        )
    ):
        text = f"{freigabe.NAMEN[schritt.objekt_art]} {schritt.objekt_id} wartet seit {schritt.erstellt_am:%d.%m.%Y}"
        for person in freigabe.empfaenger(k.db, schritt):
            ergebnis[person].append(text)
    return ergebnis


def vertragsfristen(k: Kontext, heute: date) -> dict[int, list[str]]:
    ergebnis = defaultdict(list)
    zeilen = k.db.execute(
        select(Vertrag, Beleg)
        .join(Beleg, Beleg.id == Vertrag.beleg_id)
        .where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.status != "papierkorb",
            or_(Vertrag.erinnerung_am == heute, Vertrag.kuendigen_bis == heute + timedelta(days=7)),
        )
    )
    for vertrag, beleg in zeilen:
        name = beleg.lieferant or beleg.dateiname
        if vertrag.kuendigen_bis:
            text = f"Vertrag {name}: kündbar bis {vertrag.kuendigen_bis:%d.%m.%Y}"
        else:
            text = f"Vertrag {name}: Wiedervorlage heute"
        for person in dict.fromkeys([vertrag.verantwortlich_id, *vertrag.informieren]):
            if person:
                ergebnis[person].append(text)
    return ergebnis


def fehlende_belege(k: Kontext) -> dict[int, list[str]]:
    ergebnis = defaultdict(list)
    zeilen = k.db.execute(
        select(Transaktion, Karte)
        .join(Karte, Karte.id == Transaktion.karte_id)
        .where(
            Transaktion.mandant_id == k.mandant.id,
            Transaktion.status == "fehlt",
            Transaktion.datum <= date.today() - timedelta(days=3),
        )
    )
    for transaktion, karte in zeilen:
        wann = f"{transaktion.datum:%d.%m.%Y}"
        text = f"Beleg fehlt: {transaktion.haendler} vom {wann}, {transaktion.betrag} {transaktion.waehrung}"
        ergebnis[karte.inhaber_id].append(text)
    return ergebnis


def faellige(k: Kontext) -> list[dict]:
    gesammelt = defaultdict(list)
    for quelle in (offene_freigaben(k), vertragsfristen(k, date.today()), fehlende_belege(k)):
        for person, texte in quelle.items():
            gesammelt[person] += texte
    ergebnis = []
    for nummer, texte in sorted(gesammelt.items()):
        benutzer = k.db.get(Benutzer, nummer)
        if benutzer and benutzer.aktiv:
            ergebnis.append({"name": benutzer.name, "email": benutzer.email, "texte": texte})
    return ergebnis
