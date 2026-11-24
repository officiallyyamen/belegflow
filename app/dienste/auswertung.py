from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select

from ..modelle import (
    Anforderung,
    Auswertung,
    Beleg,
    Erstattung,
    Freigabeschritt,
    Karte,
    Mitteilung,
    Partner,
    Stammwert,
    Transaktion,
    Vertrag,
    jetzt,
)
from ..sicherheit import Kontext
from . import belege, export, freigabe, zahlung
from .werte import RECHNUNGEN

GEBUCHT = ("freigegeben", "exportiert")
DIMENSIONEN = ("kostenstelle", "konto", "partner")
REITER = {
    "rechnungen": RECHNUNGEN,
    "vertraege": ("vertrag",),
    "dokumente": ("angebot", "auftragsbestaetigung", "bestellung", "lieferschein", "ausgangsrechnung", "sonstiges"),
}


def anzahl(k: Kontext, klasse, *bedingungen) -> int:
    return k.db.scalar(select(func.count()).select_from(klasse).where(klasse.mandant_id == k.mandant.id, *bedingungen))


def meine_schritte(k: Kontext) -> list[Freigabeschritt]:
    return list(
        k.db.scalars(
            select(Freigabeschritt).where(
                Freigabeschritt.mandant_id == k.mandant.id,
                Freigabeschritt.status == "offen",
                freigabe.zustaendig_filter(k.db, k.mandant.id, k.id),
            )
        )
    )


def faellige_vertraege(k: Kontext, tage: int = 30):
    heute = date.today()
    bedingungen = [
        Beleg.mandant_id == k.mandant.id,
        Beleg.status != "papierkorb",
        or_(Vertrag.erinnerung_am <= heute, Vertrag.kuendigen_bis.between(heute, heute + timedelta(days=tage))),
        *belege.sichtfilter(k),
    ]
    if not k.sieht_alles:
        bedingungen.append(Vertrag.verantwortlich_id == k.id)
    return list(k.db.execute(select(Vertrag, Beleg).join(Beleg, Beleg.id == Vertrag.beleg_id).where(*bedingungen)))


def fehlende_belege(k: Kontext, nur_eigene: bool) -> int:
    abfrage = (
        select(func.count())
        .select_from(Transaktion)
        .join(Karte, Karte.id == Transaktion.karte_id)
        .where(Transaktion.mandant_id == k.mandant.id, Transaktion.status == "fehlt")
    )
    return k.db.scalar(abfrage.where(Karte.inhaber_id == k.id) if nur_eigene else abfrage)


def eingang(k: Kontext) -> dict:
    heute = date.today()
    offen = k.db.execute(
        select(Beleg.art, Beleg.klaerung, Beleg.faellig_am).where(
            Beleg.mandant_id == k.mandant.id, Beleg.status == "neu", *belege.sichtfilter(k)
        )
    ).all()
    ergebnis = {
        name: sum(1 for art, klaerung, _ in offen if art in arten and not klaerung) for name, arten in REITER.items()
    }
    ergebnis["klaerung"] = sum(1 for _, klaerung, _ in offen if klaerung)
    ergebnis["ueberfaellig"] = sum(1 for art, _, tag in offen if art in RECHNUNGEN and tag and tag < heute)
    ergebnis["erstattungen"] = anzahl(k, Erstattung, Erstattung.status == "pruefung")
    ergebnis["transaktionen"] = fehlende_belege(k, False)
    return ergebnis


def freigaben(k: Kontext) -> dict:
    heute, schritte = date.today(), meine_schritte(k)
    ergebnis = {art: sum(1 for s in schritte if s.objekt_art == art) for art in freigabe.KLASSEN}
    nummern = [s.objekt_id for s in schritte if s.objekt_art == "beleg"]
    ergebnis["ueberfaellig"] = anzahl(k, Beleg, Beleg.id.in_(nummern or [-1]), Beleg.faellig_am < heute)
    return ergebnis


def beobachten(k: Kontext) -> dict:
    angefragt = k.db.execute(
        select(Freigabeschritt.objekt_art, Freigabeschritt.objekt_id)
        .where(
            Freigabeschritt.mandant_id == k.mandant.id,
            Freigabeschritt.angefragt_von == k.id,
            Freigabeschritt.status == "offen",
        )
        .distinct()
    ).all()
    abgelehnt = k.db.execute(
        select(Freigabeschritt.objekt_art, Freigabeschritt.objekt_id)
        .where(
            Freigabeschritt.mandant_id == k.mandant.id,
            Freigabeschritt.angefragt_von == k.id,
            Freigabeschritt.status == "abgelehnt",
            Freigabeschritt.entschieden_am >= jetzt() - timedelta(days=30),
        )
        .distinct()
    ).all()
    return {
        "angefragt": len(angefragt),
        "abgelehnt": len(abgelehnt),
        "erwaehnt": k.db.scalar(
            select(func.count())
            .select_from(Mitteilung)
            .where(
                Mitteilung.mandant_id == k.mandant.id,
                Mitteilung.benutzer_id == k.id,
                Mitteilung.gelesen.is_(False),
                Mitteilung.text.contains("erwähnt"),
            )
        ),
        "erstattungen": anzahl(
            k,
            Erstattung,
            Erstattung.benutzer_id == k.id,
            Erstattung.status.in_(("entwurf", "zurueck", "pruefung", "freigabe")),
        ),
        "anforderungen": anzahl(
            k, Anforderung, Anforderung.benutzer_id == k.id, Anforderung.status.in_(("freigabe", "freigegeben", "teilweise"))
        ),
        "belege_fehlen": fehlende_belege(k, True),
    }


def zaehler(k: Kontext) -> dict:
    ergebnis = {
        "freigaben": freigaben(k),
        "vertraege": len(faellige_vertraege(k)),
        "mitteilungen": k.db.scalar(
            select(func.count())
            .select_from(Mitteilung)
            .where(Mitteilung.mandant_id == k.mandant.id, Mitteilung.benutzer_id == k.id, Mitteilung.gelesen.is_(False))
        ),
    }
    if k.sieht_alles:
        bereit = export.wartende(k)
        offene = zahlung.offene(k)
        heute = date.today()
        ergebnis["eingang"] = eingang(k)
        ergebnis["export"] = {
            "bereit": sum(1 for b in bereit if not b["hindernis"]),
            "nicht_bereit": sum(1 for b in bereit if b["hindernis"]),
        }
        ergebnis["zahlungen"] = {
            "offen": len(offene),
            "ueberfaellig": sum(1 for p in offene if p["faellig_am"] and p["faellig_am"] < heute),
        }
    return ergebnis


def buchungen(k: Kontext, jahr: int) -> list[dict]:
    zeilen = []
    for beleg in k.db.scalars(
        select(Beleg).where(
            Beleg.mandant_id == k.mandant.id,
            Beleg.art.in_(RECHNUNGEN),
            Beleg.status.in_(GEBUCHT),
            Beleg.datum >= date(jahr, 1, 1),
            Beleg.datum <= date(jahr, 12, 31),
        )
    ):
        zeichen = belege.vorzeichen(beleg)
        for z in export.zeilen_von(beleg):
            zeilen.append(
                {
                    "monat": beleg.datum.month,
                    "partner": str(beleg.partner_id or ""),
                    "konto": z["konto"] or "",
                    "kostenstelle": z["kostenstelle"] or "",
                    "netto": zeichen * z["netto"],
                    "brutto": zeichen * (z["netto"] + z["ust"]),
                }
            )
    return zeilen


def namen(k: Kontext, art: str) -> dict[str, str]:
    if art == "partner":
        return {
            str(nummer): name
            for nummer, name in k.db.execute(select(Partner.id, Partner.name).where(Partner.mandant_id == k.mandant.id))
        }
    return {
        code: f"{code} {name}"
        for code, name in k.db.execute(
            select(Stammwert.code, Stammwert.name).where(Stammwert.mandant_id == k.mandant.id, Stammwert.art == art)
        )
    }


def je_monat(zeilen: list[dict], basis: str) -> list[str]:
    summen = [Decimal(0)] * 12
    for z in zeilen:
        summen[z["monat"] - 1] += z[basis]
    return [str(s) for s in summen]


def budgets(k: Kontext, zeilen: list[dict], basis: str) -> list[dict]:
    ergebnis = []
    for eintrag in k.db.scalars(
        select(Auswertung).where(Auswertung.mandant_id == k.mandant.id).order_by(Auswertung.art, Auswertung.wert)
    ):
        passend = [z for z in zeilen if z[eintrag.art] == eintrag.wert]
        ergebnis.append(
            {
                "id": eintrag.id,
                "art": eintrag.art,
                "wert": eintrag.wert,
                "name": namen(k, eintrag.art).get(eintrag.wert, eintrag.wert),
                "budget": str(eintrag.budget),
                "verbraucht": str(sum((z[basis] for z in passend), Decimal(0))),
                "monate": je_monat(passend, basis),
            }
        )
    return ergebnis


def verteilung(k: Kontext, zeilen: list[dict], nach: str, basis: str, grenze: int = 7) -> list[dict]:
    summen: dict[str, Decimal] = defaultdict(Decimal)
    for z in zeilen:
        summen[z[nach]] += z[basis]
    bezeichnung = namen(k, nach)
    sortiert = sorted(summen.items(), key=lambda paar: -paar[1])
    ergebnis = [
        {"wert": wert, "name": bezeichnung.get(wert, wert or "ohne Angabe"), "summe": str(summe)}
        for wert, summe in sortiert[:grenze]
    ]
    rest = sum((summe for _, summe in sortiert[grenze:]), Decimal(0))
    if rest:
        ergebnis.append({"wert": None, "name": "Weitere", "summe": str(rest)})
    return ergebnis


def kennzahlen(k: Kontext) -> dict:
    seit = jetzt() - timedelta(days=90)
    fertig = list(
        k.db.scalars(
            select(Beleg).where(
                Beleg.mandant_id == k.mandant.id,
                Beleg.art.in_(RECHNUNGEN),
                Beleg.status.in_(GEBUCHT),
                Beleg.freigegeben_am >= seit,
            )
        )
    )
    tage = [(b.freigegeben_am - b.erstellt_am).total_seconds() / 86400 for b in fertig]
    richtig = sum(1 for b in fertig if b.automatisch)
    return {
        "belege": len(fertig),
        "gelesen_prozent": round(100 * richtig / len(fertig)) if fertig else None,
        "automatik_prozent": round(100 * sum(1 for b in fertig if b.automatik) / len(fertig)) if fertig else None,
        "durchlauf_tage": round(sum(tage) / len(tage), 1) if tage else None,
    }


def karten(k: Kontext) -> list[dict]:
    from .karten import ausgabe, eigene

    return [ausgabe(k, karte) for karte in eigene(k)]


def uebersicht(k: Kontext, jahr: int, basis: str, nach: str) -> dict:
    ergebnis = {"zaehler": zaehler(k), "beobachten": beobachten(k), "karten": karten(k)}
    if k.sieht_alles:
        zeilen = buchungen(k, jahr)
        ergebnis |= {
            "budgets": budgets(k, zeilen, basis),
            "monate": je_monat(zeilen, basis),
            "verteilung": verteilung(k, zeilen, nach, basis),
            "kennzahlen": kennzahlen(k),
        }
    return ergebnis
