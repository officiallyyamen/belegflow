from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..modelle import Anforderung, Beleg, Freigabeschritt, Partner, Verknuepfung, Wareneingang, jetzt
from ..sicherheit import Kontext
from . import erkennung, freigabe
from .fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from .protokoll import protokolliere
from .werte import als_betrag, als_zahl, kurz, normal

BESTELLT = ("freigegeben", "teilweise", "erfuellt")


def sichtfilter(k: Kontext) -> list:
    if k.sieht_alles:
        return []
    schritte = select(Freigabeschritt.objekt_id).where(
        Freigabeschritt.objekt_art == "anforderung",
        or_(freigabe.zustaendig_filter(k.db, k.mandant.id, k.id), Freigabeschritt.entschieden_von == k.id),
    )
    return [or_(Anforderung.benutzer_id == k.id, Anforderung.id.in_(schritte))]


def hole(k: Kontext, nummer: int) -> Anforderung:
    eintrag = k.db.scalar(
        select(Anforderung).where(Anforderung.id == nummer, Anforderung.mandant_id == k.mandant.id, *sichtfilter(k))
    )
    if not eintrag:
        raise NichtGefunden("Bestellanforderung nicht gefunden")
    return eintrag


def positionen_sauber(zeilen: list[dict]) -> list[dict]:
    ergebnis = []
    for zeile in zeilen[:100]:
        menge, preis = als_zahl(zeile.get("menge")), als_zahl(zeile.get("einzelpreis"))
        if not (zeile.get("text") or "").strip() or menge is None or preis is None or menge <= 0 or preis < 0:
            raise Ungueltig("Jede Position braucht Bezeichnung, Menge und Preis")
        ergebnis.append(
            {
                "nummer": (zeile.get("nummer") or "").strip()[:60] or None,
                "text": zeile["text"].strip()[:200],
                "menge": kurz(menge),
                "einzelpreis": kurz(preis),
            }
        )
    return ergebnis


def vorschlag(db: Session, mandant_id: int, lieferant: str) -> dict:
    gesucht = erkennung.partner_name(lieferant)
    partner = next(
        (
            p
            for p in db.scalars(select(Partner).where(Partner.mandant_id == mandant_id))
            if erkennung.partner_name(p.name) == gesucht
        ),
        None,
    )
    letzte = db.scalars(
        select(Anforderung).where(Anforderung.mandant_id == mandant_id).order_by(Anforderung.id.desc()).limit(200)
    )
    frueher = next((a for a in letzte if erkennung.partner_name(a.lieferant) == gesucht), None)
    return {
        "partner_id": partner.id if partner else None,
        "konto": (frueher and frueher.konto) or (partner and partner.konto),
        "kostenstelle": (frueher and frueher.kostenstelle) or (partner and partner.kostenstelle),
    }


def anlegen(k: Kontext, werte: dict, ziele: list[dict] | None) -> Anforderung:
    positionen = positionen_sauber(werte.pop("positionen", None) or [])
    netto = werte.pop("netto", None)
    if positionen:
        netto = sum(Decimal(p["menge"]) * Decimal(p["einzelpreis"]) for p in positionen)
    netto = als_betrag(netto)
    if netto is None or netto <= 0:
        raise Ungueltig("Betrag fehlt")
    hinweis = vorschlag(k.db, k.mandant.id, werte["lieferant"])
    eintrag = Anforderung(
        mandant_id=k.mandant.id,
        benutzer_id=k.id,
        status="neu",
        netto=netto,
        positionen=positionen,
        partner_id=hinweis["partner_id"],
        **werte,
    )
    eintrag.konto = eintrag.konto or hinweis["konto"]
    eintrag.kostenstelle = eintrag.kostenstelle or hinweis["kostenstelle"]
    k.db.add(eintrag)
    protokolliere(k.db, "anforderung", eintrag, k.name, "angelegt", titel=eintrag.titel, netto=netto)
    name = ""
    if not ziele:
        workflow = freigabe.workflow_finden(k.db, "anforderung", eintrag)
        if workflow:
            ziele, name = workflow.schritte, workflow.name
    if ziele:
        freigabe.anfordern(k, "anforderung", eintrag, ziele, name=name)
    k.db.commit()
    return eintrag


def aendern(k: Kontext, eintrag: Anforderung, werte: dict) -> None:
    if not (eintrag.benutzer_id == k.id or k.hat("buchhaltung", "admin")):
        raise Verboten("Dafür fehlt die Berechtigung")
    if eintrag.status != "neu":
        raise Konflikt("Bestellanforderung kann nicht mehr geändert werden")
    if "positionen" in werte:
        werte["positionen"] = positionen_sauber(werte["positionen"] or [])
        if werte["positionen"]:
            werte["netto"] = als_betrag(sum(Decimal(p["menge"]) * Decimal(p["einzelpreis"]) for p in werte["positionen"]))
    neu = {f: w for f, w in werte.items() if getattr(eintrag, f) != w}
    for feld, wert in neu.items():
        setattr(eintrag, feld, wert)
    if neu:
        if eintrag.benutzer_id != k.id:
            eintrag.bearbeitet_von = k.id
        protokolliere(k.db, "anforderung", eintrag, k.name, "geaendert", neu=neu)
    k.db.commit()


def nach_freigabe(db: Session, eintrag: Anforderung) -> None:
    jahr = jetzt().year
    vorhanden = db.scalars(
        select(Anforderung.nummer).where(
            Anforderung.mandant_id == eintrag.mandant_id, Anforderung.nummer.like(f"BA-{jahr}-%")
        )
    )
    letzte = max((int(n.rsplit("-", 1)[1]) for n in vorhanden), default=0)
    eintrag.nummer = f"BA-{jahr}-{letzte + 1:04d}"


def rechnungen(db: Session, eintrag: Anforderung) -> list[Beleg]:
    nummern = db.scalars(
        select(Verknuepfung.b_id).where(
            Verknuepfung.a_art == "anforderung", Verknuepfung.a_id == eintrag.id, Verknuepfung.b_art == "beleg"
        )
    )
    belege = [db.get(Beleg, n) for n in nummern]
    return [b for b in belege if b.art in ("rechnung", "gutschrift") and b.status not in ("papierkorb", "abgelehnt")]


def verrechnet(db: Session, eintrag: Anforderung) -> Decimal:
    return sum(((b.netto or Decimal(0)) * (-1 if b.art == "gutschrift" else 1) for b in rechnungen(db, eintrag)), Decimal(0))


def aktualisiere(db: Session, eintrag: Anforderung) -> None:
    if eintrag.status not in BESTELLT:
        return
    summe = verrechnet(db, eintrag)
    if summe >= eintrag.netto:
        eintrag.status = "erfuellt"
    elif summe > 0:
        eintrag.status = "teilweise"
    else:
        eintrag.status = "freigegeben"


def verknuepfte(db: Session, beleg: Beleg) -> list[Anforderung]:
    return [
        db.get(Anforderung, nummer) for art, nummer in erkennung.verknuepft(db, "beleg", beleg.id) if art == "anforderung"
    ]


def aktualisiere_nach_beleg(db: Session, beleg: Beleg) -> None:
    for eintrag in verknuepfte(db, beleg):
        aktualisiere(db, eintrag)


def wareneingaenge(db: Session, eintrag: Anforderung) -> list[Wareneingang]:
    return list(db.scalars(select(Wareneingang).where(Wareneingang.anforderung_id == eintrag.id).order_by(Wareneingang.id)))


def geliefert(db: Session, eintrag: Anforderung) -> list[Decimal]:
    mengen = [Decimal(0)] * len(eintrag.positionen)
    for eingang in wareneingaenge(db, eintrag):
        for stelle, menge in eingang.mengen.items():
            mengen[int(stelle)] += Decimal(menge)
    return mengen


def erfasse_wareneingang(
    k: Kontext, eintrag: Anforderung, datum: date, lieferschein: str | None, mengen: dict
) -> Wareneingang:
    if eintrag.status not in BESTELLT:
        raise Konflikt("Wareneingang geht erst nach der Freigabe")
    if not (eintrag.benutzer_id == k.id or k.hat("buchhaltung", "admin")):
        raise Verboten("Dafür fehlt die Berechtigung")
    sauber = {}
    for stelle, menge in mengen.items():
        wert = als_zahl(menge)
        if not str(stelle).isdigit() or int(stelle) >= len(eintrag.positionen) or wert is None or wert < 0:
            raise Ungueltig("Menge ist ungültig")
        if wert:
            sauber[str(int(stelle))] = kurz(wert)
    if not sauber:
        raise Ungueltig("Bitte mindestens eine Menge eintragen")
    eingang = Wareneingang(
        mandant_id=k.mandant.id, anforderung_id=eintrag.id, datum=datum, lieferschein=lieferschein, mengen=sauber, von=k.name
    )
    k.db.add(eingang)
    protokolliere(k.db, "anforderung", eintrag, k.name, "wareneingang", mengen=sauber, lieferschein=lieferschein or "")
    k.db.commit()
    return eingang


def gleiche_position(bestellt: dict, berechnet: dict) -> bool:
    if bestellt.get("nummer") and berechnet.get("nummer"):
        return normal(bestellt["nummer"]) == normal(berechnet["nummer"])
    return bool(normal(bestellt["text"])) and normal(bestellt["text"]) == normal(berechnet.get("text"))


def abgleich(db: Session, beleg: Beleg) -> list[dict]:
    ergebnis = []
    for eintrag in verknuepfte(db, beleg):
        mengen = geliefert(db, eintrag)
        eingang_da = bool(wareneingaenge(db, eintrag))
        for stelle, bestellt in enumerate(eintrag.positionen):
            zeile = next((p for p in beleg.positionen if gleiche_position(bestellt, p)), None)
            menge = als_zahl(zeile["menge"]) if zeile else None
            preis = als_zahl(zeile["einzelpreis"]) if zeile else None
            grenze = mengen[stelle] if eingang_da else Decimal(bestellt["menge"])
            ergebnis.append(
                {
                    "anforderung": eintrag.nummer,
                    "text": bestellt["text"],
                    "bestellt": bestellt["menge"],
                    "geliefert": kurz(mengen[stelle]) if eingang_da else None,
                    "berechnet": kurz(menge) if menge is not None else None,
                    "preis_bestellt": bestellt["einzelpreis"],
                    "preis_berechnet": kurz(preis) if preis is not None else None,
                    "menge_ok": menge is not None and menge <= grenze,
                    "preis_ok": preis is not None and preis <= Decimal(bestellt["einzelpreis"]),
                }
            )
    return ergebnis
