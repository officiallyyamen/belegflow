from datetime import date

from sqlalchemy import String, and_, case, cast, func, literal, or_, select

from ..modelle import (
    Anforderung,
    Anhang,
    Beleg,
    Erstattung,
    Freigabeschritt,
    Partner,
    Protokoll,
    Schlagwort,
    Verknuepfung,
    Vertrag,
)
from ..sicherheit import Kontext
from . import anforderung, belege, erstattung, freigabe
from .auswertung import REITER
from .fehler import Ungueltig
from .werte import als_betrag

ARCHIV = ("freigabe", "freigegeben", "exportiert", "abgelehnt", "abgelegt")
SORTIERUNG = {
    "neu": Beleg.id.desc(),
    "alt": Beleg.id.asc(),
    "faellig": case((Beleg.faellig_am.is_(None), 1), else_=0),
    "betrag": case((Beleg.brutto.is_(None), 1), else_=0),
    "lieferant": func.lower(func.coalesce(Beleg.lieferant, "")),
}
ZWEITE = {"faellig": Beleg.faellig_am.asc(), "betrag": Beleg.brutto.desc()}


def suchfilter(suche: str, modus: str):
    suche = suche.strip().lower()
    kurz = [
        Beleg.lieferant,
        Beleg.nummer,
        Beleg.bestellnummer,
        Beleg.buchungstext,
        Beleg.notiz,
        Beleg.dateiname,
        Beleg.konto,
    ]
    felder = [func.lower(func.coalesce(f, "")) for f in kurz]
    schlag = select(Schlagwort.beleg_id).where(func.lower(Schlagwort.name).contains(suche, autoescape=True))
    text = func.lower(func.replace(func.replace(Beleg.text, "\n", " "), "\r", " "))
    if modus == "exakt":
        return or_(
            *(f == suche for f in felder), (literal(" ") + text + literal(" ")).contains(f" {suche} ", autoescape=True)
        )
    if modus == "beginnt":
        return or_(
            *(f.startswith(suche, autoescape=True) for f in felder),
            (literal(" ") + text).contains(f" {suche}", autoescape=True),
        )
    return or_(
        *(f.contains(suche, autoescape=True) for f in felder), text.contains(suche, autoescape=True), Beleg.id.in_(schlag)
    )


def gemeinsame(filter_: dict) -> list:
    bedingungen = []
    if filter_.get("suche"):
        bedingungen.append(suchfilter(filter_["suche"], filter_.get("modus") or "enthaelt"))
    for name in ("art", "partner_id", "konto", "kostenstelle", "kostentraeger", "stufe", "quelle", "zahlstatus"):
        if filter_.get(name):
            bedingungen.append(getattr(Beleg, name) == filter_[name])
    if filter_.get("von"):
        bedingungen.append(Beleg.datum >= filter_["von"])
    if filter_.get("bis"):
        bedingungen.append(Beleg.datum <= filter_["bis"])
    for name, vergleich in (("betrag_ab", "__ge__"), ("betrag_bis", "__le__")):
        if filter_.get(name):
            wert = als_betrag(filter_[name])
            if wert is None:
                raise Ungueltig("Betrag ist ungültig")
            bedingungen.append(getattr(Beleg.brutto, vergleich)(wert))
    if filter_.get("schlagwort"):
        bedingungen.append(Beleg.id.in_(select(Schlagwort.beleg_id).where(Schlagwort.name == filter_["schlagwort"])))
    if filter_.get("merkmal"):
        bedingungen.append(merkmal(filter_["merkmal"]))
    return bedingungen


def merkmal(name: str):
    if name == "ueberfaellig":
        return and_(Beleg.faellig_am < date.today(), Beleg.zahlstatus == "offen")
    if name == "e_rechnung":
        return Beleg.e_rechnung.is_not(None)
    if name == "duplikat":
        return cast(Beleg.pruefbericht, String).contains('"code": "duplikat"')
    if name == "automatik":
        return Beleg.automatik.is_not(None)
    if name == "eingeschraenkt":
        return Beleg.eingeschraenkt.is_(True)
    raise Ungueltig("Merkmal gibt es nicht")


def seite(k: Kontext, bedingungen: list, sortierung: str, grenze: int, ab: int) -> dict:
    basis = [Beleg.mandant_id == k.mandant.id, *belege.sichtfilter(k), *bedingungen]
    ordnung = [SORTIERUNG.get(sortierung, SORTIERUNG["neu"])]
    if sortierung in ZWEITE:
        ordnung.append(ZWEITE[sortierung])
    gesamt, summe = k.db.execute(
        select(func.count(), func.sum(case((Beleg.art == "gutschrift", -Beleg.brutto), else_=Beleg.brutto))).where(*basis)
    ).one()
    eintraege = list(k.db.scalars(select(Beleg).where(*basis).order_by(*ordnung, Beleg.id.desc()).limit(grenze).offset(ab)))
    return {"gesamt": gesamt, "summe": str(summe) if summe is not None else None, "belege": eintraege}


def eingang(k: Kontext, reiter: str, klaerung: bool, filter_: dict, sortierung: str, grenze: int, ab: int) -> dict:
    if reiter not in REITER:
        raise Ungueltig("Reiter gibt es nicht")
    bedingungen = [Beleg.status == "neu", Beleg.art.in_(REITER[reiter]), Beleg.klaerung.is_(klaerung)]
    return seite(k, [*bedingungen, *gemeinsame(filter_)], sortierung, grenze, ab)


def archiv(k: Kontext, status: str | None, filter_: dict, sortierung: str, grenze: int, ab: int) -> dict:
    bedingungen = [Beleg.status == status] if status else [Beleg.status.in_(ARCHIV)]
    return seite(k, [*bedingungen, *gemeinsame(filter_)], sortierung, grenze, ab)


def vertraege(k: Kontext, sortierung: str) -> list[tuple[Beleg, Vertrag]]:
    reihe = {
        "frist": [case((Vertrag.kuendigen_bis.is_(None), 1), else_=0), Vertrag.kuendigen_bis],
        "erinnerung": [case((Vertrag.erinnerung_am.is_(None), 1), else_=0), Vertrag.erinnerung_am],
        "ende": [case((Vertrag.ende.is_(None), 1), else_=0), Vertrag.ende],
    }.get(sortierung, [Beleg.id.desc()])
    zeilen = k.db.execute(
        select(Beleg, Vertrag)
        .join(Vertrag, Vertrag.beleg_id == Beleg.id)
        .where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.art == "vertrag",
            Beleg.status.not_in(("papierkorb", "neu")),
            *belege.sichtfilter(k),
        )
        .order_by(*reihe, Beleg.id.desc())
    )
    return [(b, v) for b, v in zeilen]


def anmerkungen(k: Kontext, nummern: list[int]) -> dict[int, dict]:
    if not nummern:
        return {}
    ergebnis = {n: {"kommentare": 0, "anhaenge": 0, "verknuepfungen": 0} for n in nummern}
    for nummer, zahl in k.db.execute(
        select(Protokoll.objekt_id, func.count())
        .where(Protokoll.objekt_art == "beleg", Protokoll.aktion == "kommentar", Protokoll.objekt_id.in_(nummern))
        .group_by(Protokoll.objekt_id)
    ):
        ergebnis[nummer]["kommentare"] = zahl
    for nummer, zahl in k.db.execute(
        select(Anhang.objekt_id, func.count())
        .where(Anhang.objekt_art == "beleg", Anhang.objekt_id.in_(nummern))
        .group_by(Anhang.objekt_id)
    ):
        ergebnis[nummer]["anhaenge"] = zahl
    for a_art, a_id, b_art, b_id in k.db.execute(
        select(Verknuepfung.a_art, Verknuepfung.a_id, Verknuepfung.b_art, Verknuepfung.b_id).where(
            or_(
                and_(Verknuepfung.a_art == "beleg", Verknuepfung.a_id.in_(nummern)),
                and_(Verknuepfung.b_art == "beleg", Verknuepfung.b_id.in_(nummern)),
            )
        )
    ):
        for art, nummer in ((a_art, a_id), (b_art, b_id)):
            if art == "beleg" and nummer in ergebnis:
                ergebnis[nummer]["verknuepfungen"] += 1
    return ergebnis


def freigaben(k: Kontext, art: str, sicht: str) -> list[tuple[object, list[Freigabeschritt]]]:
    klasse = freigabe.KLASSEN[art]
    basis = [Freigabeschritt.mandant_id == k.mandant.id, Freigabeschritt.objekt_art == art]
    if sicht == "meine":
        basis += [Freigabeschritt.status == "offen", freigabe.zustaendig_filter(k.db, k.mandant.id, k.id)]
    elif sicht == "angefragt":
        basis += [Freigabeschritt.angefragt_von == k.id]
    nummern = set(k.db.scalars(select(Freigabeschritt.objekt_id).where(*basis)))
    sicher = {"beleg": belege, "erstattung": erstattung, "anforderung": anforderung}[art].sichtfilter(k)
    bedingungen = [klasse.mandant_id == k.mandant.id, klasse.id.in_(nummern or [-1]), *sicher]
    if sicht != "angefragt":
        bedingungen.append(klasse.status == "freigabe")
    objekte = k.db.scalars(select(klasse).where(*bedingungen).order_by(klasse.id.desc()).limit(200))
    return [(o, freigabe.schritte(k.db, art, o.id)) for o in objekte]


def suche(k: Kontext, text: str, grenze: int = 6) -> dict:
    muster = text.strip()
    eintraege = {
        "belege": list(
            k.db.scalars(
                select(Beleg)
                .where(
                    Beleg.mandant_id == k.mandant.id,
                    Beleg.status != "papierkorb",
                    *belege.sichtfilter(k),
                    suchfilter(muster, "enthaelt"),
                )
                .order_by(Beleg.id.desc())
                .limit(grenze)
            )
        ),
        "partner": [],
        "anforderungen": list(
            k.db.scalars(
                select(Anforderung)
                .where(
                    Anforderung.mandant_id == k.mandant.id,
                    *anforderung.sichtfilter(k),
                    or_(
                        *(
                            f.icontains(muster, autoescape=True)
                            for f in (Anforderung.titel, Anforderung.lieferant, Anforderung.nummer)
                        )
                    ),
                )
                .order_by(Anforderung.id.desc())
                .limit(grenze)
            )
        ),
        "erstattungen": list(
            k.db.scalars(
                select(Erstattung)
                .where(
                    Erstattung.mandant_id == k.mandant.id,
                    *erstattung.sichtfilter(k),
                    Erstattung.titel.icontains(muster, autoescape=True),
                    or_(Erstattung.status != "entwurf", Erstattung.benutzer_id == k.id),
                )
                .order_by(Erstattung.id.desc())
                .limit(grenze)
            )
        ),
    }
    if k.sieht_alles:
        eintraege["partner"] = list(
            k.db.scalars(
                select(Partner)
                .where(
                    Partner.mandant_id == k.mandant.id,
                    or_(*(f.icontains(muster, autoescape=True) for f in (Partner.name, Partner.uid, Partner.kreditor))),
                )
                .order_by(Partner.name)
                .limit(grenze)
            )
        )
    return eintraege
