from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, object_session

from ..modelle import Benutzer, Erstattung, Erstattungsposten, Freigabeschritt, Mitglied
from ..sicherheit import Kontext
from . import reisekosten, waehrung
from .dateien import ablegen, erkenne_typ, pruefe_groesse
from .extraktion import ExtraktionsFehler, extraktor, pdf_text
from .fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from .protokoll import mitteilen, protokolliere
from .pruefung import iban_gueltig
from .werte import Rechnung, als_betrag, als_kennung, als_zahl, felder

ARTEN = ("auslage", "bewirtung", "taggeld", "kilometer")
OFFEN = ("entwurf", "zurueck")


def posten(db: Session, erstattung_id: int) -> list[Erstattungsposten]:
    return list(
        db.scalars(
            select(Erstattungsposten).where(Erstattungsposten.erstattung_id == erstattung_id).order_by(Erstattungsposten.id)
        )
    )


def summe(antrag: Erstattung) -> Decimal:
    return sum((p.betrag for p in posten(object_session(antrag), antrag.id) if not p.ausgeschlossen), Decimal(0))


def sichtfilter(k: Kontext) -> list:
    if k.sieht_alles:
        return []
    from .freigabe import zustaendig_filter

    schritte = select(Freigabeschritt.objekt_id).where(
        Freigabeschritt.objekt_art == "erstattung",
        or_(zustaendig_filter(k.db, k.mandant.id, k.id), Freigabeschritt.entschieden_von == k.id),
    )
    return [or_(Erstattung.benutzer_id == k.id, Erstattung.id.in_(schritte))]


def hole(k: Kontext, nummer: int) -> Erstattung:
    antrag = k.db.scalar(
        select(Erstattung).where(Erstattung.id == nummer, Erstattung.mandant_id == k.mandant.id, *sichtfilter(k))
    )
    if not antrag or (antrag.status == "entwurf" and antrag.benutzer_id != k.id):
        raise NichtGefunden("Erstattung nicht gefunden")
    return antrag


def anlegen(k: Kontext, titel: str, hinweis: str | None) -> Erstattung:
    antrag = Erstattung(
        mandant_id=k.mandant.id,
        benutzer_id=k.id,
        titel=titel.strip(),
        hinweis=hinweis,
        iban=k.benutzer.iban,
        status="entwurf",
    )
    k.db.add(antrag)
    protokolliere(k.db, "erstattung", antrag, k.name, "angelegt", titel=antrag.titel)
    k.db.commit()
    return antrag


def pruefe_eigen(k: Kontext, antrag: Erstattung) -> None:
    if antrag.benutzer_id != k.id:
        raise Verboten("Nur die antragstellende Person darf das ändern")
    if antrag.status not in OFFEN:
        raise Konflikt("Erstattung ist schon eingereicht")


def pruefe_buchhaltung(k: Kontext, antrag: Erstattung) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf das ändern")
    if antrag.status != "pruefung":
        raise Konflikt("Erstattung ist nicht in Prüfung")


def aendern(k: Kontext, antrag: Erstattung, werte: dict) -> None:
    if set(werte) - {"titel", "hinweis", "iban"}:
        pruefe_buchhaltung(k, antrag)
        antrag.bearbeitet_von = k.id
    else:
        pruefe_eigen(k, antrag)
    if werte.get("iban"):
        werte["iban"] = als_kennung(werte["iban"], 40)
        if not iban_gueltig(werte["iban"]):
            raise Ungueltig("IBAN ist ungültig")
    neu = {f: w for f, w in werte.items() if getattr(antrag, f) != w}
    for feld, wert in neu.items():
        setattr(antrag, feld, wert)
    if neu:
        protokolliere(k.db, "erstattung", antrag, k.name, "geaendert", neu=neu)
    k.db.commit()


def lies_beleg(inhalt: bytes, typ: str) -> Rechnung:
    try:
        text = pdf_text(inhalt) if typ == "application/pdf" else ""
        return extraktor().lies(inhalt, typ, text)
    except ExtraktionsFehler:
        return Rechnung()


def rechne(
    db: Session, art: str, titel: str, datum: date | None, daten: dict
) -> tuple[Decimal, Decimal, str, date | None, list]:
    if art in ("auslage", "bewirtung"):
        waehrung_name = als_kennung(daten.get("waehrung") or "EUR", 3) or "EUR"
        betrag = als_betrag(daten.get("betrag"))
        ust = als_betrag(daten.get("ust")) or Decimal(0)
        trinkgeld = als_betrag(daten.get("trinkgeld")) or Decimal(0) if art == "bewirtung" else Decimal(0)
        if betrag is None:
            return Decimal(0), Decimal(0), titel, datum, []
        if betrag < 0 or ust < 0 or trinkgeld < 0 or ust > betrag:
            raise Ungueltig("Beträge dürfen nicht negativ sein")
        if waehrung_name == "EUR":
            return betrag + trinkgeld, ust, titel, datum, []
        if not datum:
            raise Ungueltig("Für Fremdwährung wird das Datum benötigt")
        eigener = als_zahl(daten.get("kurs"))
        kurs = eigener if eigener else waehrung.kurs(db, waehrung_name, datum)
        euro = waehrung.in_euro(betrag + trinkgeld, kurs)
        return euro, Decimal(0), titel, datum, [{"kurs": str(kurs), "waehrung": waehrung_name, "euro": str(euro)}]
    if art == "taggeld":
        geld, zeilen = reisekosten.taggeld(daten.get("etappen") or [], daten.get("ende"), daten.get("mahlzeiten"))
        nacht = reisekosten.naechtigung(daten.get("naechte") or [], daten.get("etappen") or [], daten.get("ende"))
        if nacht:
            zeilen = [*zeilen, {"tag": "Nächtigung", "betrag": str(nacht)}]
        beginn = reisekosten.zeitpunkt(daten["etappen"][0]["von"]).date()
        return geld + nacht, Decimal(0), titel or "Verpflegung und Nächtigung", beginn, zeilen
    strecke = als_zahl(daten.get("km"))
    if strecke is None:
        raise Ungueltig("Bitte die Kilometer angeben")
    if daten.get("hin_zurueck"):
        strecke *= 2
    betrag = reisekosten.kilometer(strecke, daten.get("fahrzeug", "pkw"), int(daten.get("mitfahrer") or 0))
    weg = " - ".join(t for t in (daten.get("start"), *(daten.get("stopps") or []), daten.get("ziel")) if t)
    return betrag, Decimal(0), titel or weg or "Kilometergeld", datum, [{"km": str(strecke), "betrag": str(betrag)}]


def posten_anlegen(
    k: Kontext, antrag: Erstattung, art: str, titel: str, datum: date | None, daten: dict, datei: tuple[str, bytes] | None
) -> Erstattungsposten:
    pruefe_eigen(k, antrag)
    if art not in ARTEN:
        raise Ungueltig("Art gibt es nicht")
    eintrag = Erstattungsposten(erstattung_id=antrag.id, art=art, titel=titel, datum=datum, daten=daten)
    if datei:
        name, inhalt = datei
        pruefe_groesse(inhalt)
        typ = erkenne_typ(inhalt)
        if typ == "application/xml":
            raise Ungueltig("Bitte ein PDF oder Foto hochladen")
        eintrag.dateiname, eintrag.dateityp, eintrag.sha256 = name[:255], typ, ablegen(inhalt, typ)
        gelesen = felder(lies_beleg(inhalt, typ))
        erkannt = {
            "lieferant": gelesen["lieferant"],
            "nummer": gelesen["nummer"],
            "betrag": str(gelesen["brutto"]) if gelesen["brutto"] is not None else None,
            "ust": str(gelesen["ust"]) if gelesen["ust"] is not None else None,
            "waehrung": gelesen["waehrung"],
        }
        eintrag.daten = {n: w for n, w in erkannt.items() if w} | {n: w for n, w in daten.items() if w not in (None, "")}
        eintrag.daten["erkannt"] = [n for n, w in erkannt.items() if w]
        eintrag.datum = datum or gelesen["datum"]
        eintrag.titel = titel or gelesen["lieferant"] or ""
    berechne(k.db, eintrag)
    k.db.add(eintrag)
    protokolliere(k.db, "erstattung", antrag, k.name, "posten_angelegt", art=art, titel=eintrag.titel, betrag=eintrag.betrag)
    k.db.commit()
    return eintrag


def berechne(db: Session, eintrag: Erstattungsposten) -> None:
    eintrag.betrag, eintrag.ust, eintrag.titel, eintrag.datum, eintrag.rechnung = rechne(
        db, eintrag.art, eintrag.titel, eintrag.datum, eintrag.daten
    )
    eintrag.titel = (eintrag.titel or "")[:200]


def hole_posten(k: Kontext, antrag: Erstattung, nummer: int) -> Erstattungsposten:
    eintrag = k.db.get(Erstattungsposten, nummer)
    if not eintrag or eintrag.erstattung_id != antrag.id:
        raise NichtGefunden("Posten nicht gefunden")
    return eintrag


def posten_aendern(k: Kontext, antrag: Erstattung, eintrag: Erstattungsposten, werte: dict) -> None:
    nur_buchhaltung = {"konto", "kostenstelle", "ausgeschlossen"}
    if set(werte) & nur_buchhaltung:
        if set(werte) - nur_buchhaltung:
            raise Ungueltig("Angaben und Kontierung bitte getrennt ändern")
        pruefe_buchhaltung(k, antrag)
        antrag.bearbeitet_von = k.id
        for feld, wert in werte.items():
            setattr(eintrag, feld, wert)
    else:
        pruefe_eigen(k, antrag)
        if "titel" in werte:
            eintrag.titel = werte["titel"] or ""
        if "datum" in werte:
            eintrag.datum = werte["datum"]
        if "daten" in werte:
            eintrag.daten = werte["daten"]
        berechne(k.db, eintrag)
    protokolliere(k.db, "erstattung", antrag, k.name, "posten_geaendert", posten=eintrag.id, neu=werte)
    k.db.commit()


def posten_loeschen(k: Kontext, antrag: Erstattung, eintrag: Erstattungsposten) -> None:
    pruefe_eigen(k, antrag)
    protokolliere(k.db, "erstattung", antrag, k.name, "posten_geloescht", titel=eintrag.titel, betrag=eintrag.betrag)
    k.db.delete(eintrag)
    k.db.commit()


def maengel(antrag: Erstattung, eintraege: list[Erstattungsposten]) -> list[str]:
    ergebnis = []
    if not eintraege:
        ergebnis.append("Es gibt noch keine Posten")
    if not antrag.iban:
        ergebnis.append("IBAN fehlt")
    for p in eintraege:
        name = p.titel or p.art
        if p.betrag <= 0:
            ergebnis.append(f"{name}: Betrag fehlt")
        if not p.datum:
            ergebnis.append(f"{name}: Datum fehlt")
        if p.art in ("auslage", "bewirtung"):
            if not p.sha256 and not (p.daten.get("eigenbeleg") or "").strip():
                ergebnis.append(f"{name}: Beleg oder Begründung für den Eigenbeleg fehlt")
            if not (p.daten.get("grund") or "").strip():
                ergebnis.append(f"{name}: Anlass fehlt")
        if p.art == "bewirtung" and not (p.daten.get("extern") or "").strip():
            ergebnis.append(f"{name}: Bewirtete Personen fehlen")
    return ergebnis


def warnungen(db: Session, antrag: Erstattung, eintraege: list[Erstattungsposten]) -> list[str]:
    ergebnis = []
    grenzen = reisekosten.saetze()["kilometer_grenze"]
    for p in eintraege:
        if p.art != "kilometer" or not p.datum:
            continue
        fahrzeug = p.daten.get("fahrzeug", "pkw")
        alle = db.scalars(
            select(Erstattungsposten)
            .join(Erstattung, Erstattung.id == Erstattungsposten.erstattung_id)
            .where(
                Erstattung.benutzer_id == antrag.benutzer_id,
                Erstattung.status.not_in(("abgelehnt",)),
                Erstattungsposten.art == "kilometer",
                Erstattungsposten.datum >= date(p.datum.year, 1, 1),
                Erstattungsposten.datum <= date(p.datum.year, 12, 31),
            )
        )
        km = sum(Decimal(a.rechnung[0]["km"]) for a in alle if a.rechnung and a.daten.get("fahrzeug", "pkw") == fahrzeug)
        if km > grenzen[fahrzeug]:
            ergebnis.append(f"Über {grenzen[fahrzeug]} km im Jahr {p.datum.year} ist Kilometergeld nicht mehr steuerfrei")
    return list(dict.fromkeys(ergebnis))


def einreichen(k: Kontext, antrag: Erstattung) -> None:
    pruefe_eigen(k, antrag)
    fehlt = maengel(antrag, posten(k.db, antrag.id))
    if fehlt:
        raise Konflikt("Noch nicht vollständig", fehlt=fehlt)
    antrag.status = "pruefung"
    protokolliere(k.db, "erstattung", antrag, k.name, "eingereicht", summe=summe(antrag))
    buchhaltung = [
        m.benutzer_id
        for m in k.db.scalars(select(Mitglied).where(Mitglied.mandant_id == k.mandant.id))
        if "buchhaltung" in m.rollen
    ]
    mitteilen(k.db, k.mandant.id, buchhaltung, f"{k.name} hat eine Erstattung eingereicht", f"erstattung/{antrag.id}", k.id)
    k.db.commit()


def zurueckgeben(k: Kontext, antrag: Erstattung, grund: str) -> None:
    pruefe_buchhaltung(k, antrag)
    antrag.status = "zurueck"
    protokolliere(k.db, "erstattung", antrag, k.name, "zurueckgegeben", grund=grund)
    mitteilen(
        k.db,
        k.mandant.id,
        [antrag.benutzer_id],
        f"Erstattung {antrag.id} kam zurück: {grund}",
        f"erstattung/{antrag.id}",
        k.id,
    )
    k.db.commit()


def verwerfen(k: Kontext, antrag: Erstattung) -> None:
    pruefe_eigen(k, antrag)
    for eintrag in posten(k.db, antrag.id):
        k.db.delete(eintrag)
    antrag.status = "verworfen"
    protokolliere(k.db, "erstattung", antrag, k.name, "verworfen")
    k.db.commit()


def name(db: Session, antrag: Erstattung) -> str:
    return db.get(Benutzer, antrag.benutzer_id).name
