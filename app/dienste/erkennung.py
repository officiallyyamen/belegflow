import math
import re
from collections import Counter, defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..modelle import Anforderung, Beleg, Partner, Schlagwort, Verknuepfung
from .werte import RECHNUNGEN, normal

GELERNT = ("freigegeben", "exportiert")
KONTIERUNG = ("konto", "kostenstelle", "kostentraeger", "steuerschluessel")
RECHTSFORM = re.compile(r"(gmbh|ggmbh|ag|kg|og|eu|ek|co|mbh|ltd|inc|verein)$")


def partner_name(name: str | None) -> str:
    kern = normal(name)
    for _ in range(3):
        kern = RECHTSFORM.sub("", kern)
    return kern


def partner_finden(db: Session, beleg: Beleg) -> Partner | None:
    alle = list(db.scalars(select(Partner).where(Partner.mandant_id == beleg.mandant_id)))
    if beleg.lieferant_uid:
        for partner in alle:
            if partner.uid == beleg.lieferant_uid:
                return partner
    gesucht = partner_name(beleg.lieferant)
    if gesucht:
        for partner in alle:
            if partner_name(partner.name) == gesucht and (not partner.uid or not beleg.lieferant_uid):
                return partner
    if beleg.iban:
        for partner in alle:
            if beleg.iban in partner.ibans and not beleg.lieferant_uid:
                return partner
    return None


def woerter(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß]{4,}", text.lower())


def aehnlichkeit(db: Session, beleg: Beleg, feld: str) -> tuple[str, float] | None:
    gelernt = list(
        db.scalars(
            select(Beleg)
            .where(
                Beleg.mandant_id == beleg.mandant_id,
                Beleg.art.in_(RECHNUNGEN),
                Beleg.status.in_(GELERNT),
                getattr(Beleg, feld).is_not(None),
            )
            .order_by(Beleg.id.desc())
            .limit(300)
        )
    )
    if len(gelernt) < 4:
        return None
    klassen: Counter = Counter()
    zaehler: dict[str, Counter] = defaultdict(Counter)
    for alt in gelernt:
        wert = getattr(alt, feld)
        klassen[wert] += 1
        zaehler[wert].update(set(woerter(alt.text)))
    eigene = set(woerter(beleg.text))
    bekannt = {wort for z in zaehler.values() for wort in z}
    wichtig = [wort for wort in eigene & bekannt if len([1 for z in zaehler.values() if wort in z]) < len(zaehler)]
    if len(wichtig) < 2 or len(klassen) < 2:
        return None
    punkte = {
        wert: math.log(anzahl / len(gelernt)) + sum(math.log((zaehler[wert][wort] + 0.5) / (anzahl + 1)) for wort in wichtig)
        for wert, anzahl in klassen.items()
    }
    beste = max(punkte, key=punkte.get)
    sicher = 1 / sum(math.exp(p - punkte[beste]) for p in punkte.values())
    return (beste, sicher) if sicher >= 0.8 else None


def historie(db: Session, beleg: Beleg, feld: str, grenze: int = 10) -> list[str]:
    if not beleg.partner_id:
        return []
    return [
        wert
        for wert in db.scalars(
            select(getattr(Beleg, feld))
            .where(
                Beleg.mandant_id == beleg.mandant_id,
                Beleg.partner_id == beleg.partner_id,
                Beleg.status.in_(GELERNT),
                Beleg.id != beleg.id,
            )
            .order_by(Beleg.freigegeben_am.desc(), Beleg.id.desc())
            .limit(grenze)
        )
        if wert
    ]


def kontierung(db: Session, beleg: Beleg) -> dict[str, tuple[str, str]]:
    partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
    ergebnis = {}
    for feld in KONTIERUNG:
        fest = getattr(partner, feld, None) if partner else None
        alt = historie(db, beleg, feld)
        if alt:
            ergebnis[feld] = (Counter(alt).most_common(1)[0][0], "Historie")
        elif fest:
            ergebnis[feld] = (fest, "Stammdaten")
        elif feld in ("konto", "kostenstelle"):
            treffer = aehnlichkeit(db, beleg, feld)
            if treffer:
                ergebnis[feld] = (treffer[0], "Ähnliche Belege")
    if partner or beleg.lieferant:
        wofuer = next((p["text"] for p in beleg.positionen if p.get("text")), "")
        text = " - ".join(t for t in (partner.name if partner else beleg.lieferant, wofuer) if t)
        ergebnis["buchungstext"] = (text[:200], "Vorschlag")
    return ergebnis


def gleiche_buchungen(db: Session, beleg: Beleg) -> int:
    anzahl = 0
    for konto, stelle in zip(historie(db, beleg, "konto"), historie(db, beleg, "kostenstelle"), strict=False):
        if (konto, stelle) != (beleg.konto, beleg.kostenstelle):
            break
        anzahl += 1
    return anzahl


def schlagwoerter(db: Session, beleg: Beleg) -> list[str]:
    if not beleg.partner_id:
        return []
    vorhanden = set(db.scalars(select(Schlagwort.name).where(Schlagwort.beleg_id == beleg.id)))
    namen = db.scalars(
        select(Schlagwort.name)
        .join(Beleg, Beleg.id == Schlagwort.beleg_id)
        .where(Beleg.mandant_id == beleg.mandant_id, Beleg.partner_id == beleg.partner_id, Beleg.id != beleg.id)
    )
    return [name for name, _ in Counter(namen).most_common(5) if name not in vorhanden]


def verknuepft(db: Session, art: str, nummer: int) -> set[tuple[str, int]]:
    zeilen = db.scalars(
        select(Verknuepfung).where(
            or_(
                (Verknuepfung.a_art == art) & (Verknuepfung.a_id == nummer),
                (Verknuepfung.b_art == art) & (Verknuepfung.b_id == nummer),
            )
        )
    )
    return {(z.b_art, z.b_id) if (z.a_art, z.a_id) == (art, nummer) else (z.a_art, z.a_id) for z in zeilen}


def passende(db: Session, beleg: Beleg) -> list[tuple[str, int, str]]:
    schon = verknuepft(db, "beleg", beleg.id)
    ergebnis = []
    if beleg.bestellnummer:
        for anforderung in db.scalars(
            select(Anforderung).where(Anforderung.mandant_id == beleg.mandant_id, Anforderung.nummer == beleg.bestellnummer)
        ):
            ergebnis.append(("anforderung", anforderung.id, "gleiche Bestellnummer"))
    bedingungen = []
    if beleg.bestellnummer:
        bedingungen += [Beleg.bestellnummer == beleg.bestellnummer, Beleg.nummer == beleg.bestellnummer]
    if beleg.nummer and beleg.art not in RECHNUNGEN:
        bedingungen.append(Beleg.bestellnummer == beleg.nummer)
    if beleg.partner_id and beleg.brutto is not None:
        bedingungen.append(
            (Beleg.partner_id == beleg.partner_id) & (Beleg.brutto == beleg.brutto) & (Beleg.art != beleg.art)
        )
    if bedingungen:
        for anderer in db.scalars(
            select(Beleg)
            .where(
                Beleg.mandant_id == beleg.mandant_id,
                Beleg.id != beleg.id,
                Beleg.status != "papierkorb",
                or_(*bedingungen),
            )
            .order_by(Beleg.id.desc())
            .limit(6)
        ):
            gleich = beleg.bestellnummer and beleg.bestellnummer in (anderer.bestellnummer, anderer.nummer)
            ergebnis.append(("beleg", anderer.id, "gleiche Bestellnummer" if gleich else "gleicher Betrag"))
    return [e for e in ergebnis if (e[0], e[1]) not in schon]
