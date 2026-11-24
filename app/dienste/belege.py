import re
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..modelle import (
    Anforderung,
    Anhang,
    Beleg,
    Benutzer,
    Freigabeschritt,
    Mitglied,
    Mitteilung,
    Nachricht,
    Partner,
    Protokoll,
    Schlagwort,
    Verknuepfung,
    Vertrag,
)
from ..sicherheit import Kontext
from . import erechnung, erkennung, freigabe
from .dateien import ablegen, erkenne_typ, pruefe_groesse, pruefwert
from .extraktion import ExtraktionsFehler, art_aus_text, extraktor, pdf_text
from .fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from .protokoll import mitteilen, protokolliere
from .pruefung import RANG, hoechste, iban_gueltig, pruefe, punkt
from .werte import ARTEN, RECHNUNGEN, Rechnung, als_kennung, felder

BEARBEITBAR = ("neu", "abgelegt")
KONTIERUNG = ("konto", "kostenstelle", "kostentraeger", "steuerschluessel", "buchungstext", "notiz")


def sichtfilter(k: Kontext) -> list:
    if k.sieht_alles:
        if k.hat("admin") or not k.benutzer:
            return []
        eigene = select(Freigabeschritt.objekt_id).where(
            Freigabeschritt.objekt_art == "beleg", freigabe.zustaendig_filter(k.db, k.mandant.id, k.id)
        )
        return [
            or_(
                Beleg.eingeschraenkt.is_(False),
                Beleg.hochgeladen_von == k.id,
                Beleg.id.in_(eigene),
                Beleg.id.in_(freigeschaltet(k)),
            )
        ]
    schritte = select(Freigabeschritt.objekt_id).where(
        Freigabeschritt.objekt_art == "beleg",
        Freigabeschritt.mandant_id == k.mandant.id,
        or_(freigabe.zustaendig_filter(k.db, k.mandant.id, k.id), Freigabeschritt.entschieden_von == k.id),
    )
    erwaehnt = select(Mitteilung.ziel).where(Mitteilung.benutzer_id == k.id, Mitteilung.mandant_id == k.mandant.id)
    nummern = [int(z.split("/")[1]) for z in k.db.scalars(erwaehnt) if z.startswith("beleg/")]
    return [
        or_(
            Beleg.hochgeladen_von == k.id,
            Beleg.id.in_(schritte),
            Beleg.id.in_(nummern or [-1]),
            Beleg.id.in_(freigeschaltet(k)),
        )
    ]


def freigeschaltet(k: Kontext) -> list[int]:
    zeilen = k.db.execute(
        select(Beleg.id, Beleg.sichtbar).where(Beleg.mandant_id == k.mandant.id, Beleg.eingeschraenkt.is_(True))
    )
    return [nummer for nummer, personen in zeilen if k.id in (personen or [])] or [-1]


def hole(k: Kontext, nummer: int) -> Beleg:
    beleg = k.db.scalar(select(Beleg).where(Beleg.id == nummer, Beleg.mandant_id == k.mandant.id, *sichtfilter(k)))
    if not beleg:
        raise NichtGefunden("Beleg nicht gefunden")
    return beleg


def bewerte(db: Session, beleg: Beleg, zusatz: list[dict] | None = None) -> None:
    db.flush()
    beleg.pruefbericht = [*(zusatz or []), *pruefe(beleg, db)]
    beleg.stufe = hoechste(beleg.pruefbericht)


def auslesen(inhalt: bytes, typ: str) -> tuple[Rechnung, str, str, str | None, list[dict]]:
    if typ == "application/xml":
        treffer = erechnung.lies(inhalt)
        if not treffer:
            raise Ungueltig("XML ist keine bekannte E-Rechnung")
        rechnung, art = treffer
        return rechnung, text_aus(rechnung), "E-Rechnung", art, []
    text = ""
    if typ == "application/pdf":
        try:
            text = pdf_text(inhalt)
        except ExtraktionsFehler:
            text = ""
        xml = erechnung.aus_pdf(inhalt)
        treffer = erechnung.lies(xml) if xml else None
        if treffer:
            return treffer[0], text or text_aus(treffer[0]), "E-Rechnung", treffer[1], []
    leser = extraktor()
    try:
        rechnung = leser.lies(inhalt, typ, text)
    except ExtraktionsFehler as fehler:
        return (
            Rechnung(art=art_aus_text(text) if text else "rechnung"),
            text,
            leser.name,
            None,
            [punkt("Erfassung", "extraktion", "fehler", str(fehler))],
        )
    return rechnung, text or text_aus(rechnung), leser.name, None, []


def text_aus(rechnung: Rechnung) -> str:
    werte = rechnung.model_dump()
    teile = [str(w) for n, w in werte.items() if w and n not in ("steuerzeilen", "positionen")]
    teile += [p["text"] for p in werte["positionen"] if p["text"]]
    return "\n".join(teile)


def nimm_auf(
    k: Kontext,
    dateiname: str,
    inhalt: bytes,
    quelle: str = "upload",
    art: str | None = None,
    nachricht: Nachricht | None = None,
) -> Beleg:
    db = k.db
    pruefe_groesse(inhalt)
    typ = erkenne_typ(inhalt)
    wert = pruefwert(inhalt)
    vorhanden = db.scalar(select(Beleg).where(Beleg.mandant_id == k.mandant.id, Beleg.sha256 == wert))
    if vorhanden:
        raise Konflikt("Diese Datei wurde bereits erfasst", beleg_id=vorhanden.id)
    rechnung, text, leser, format_name, zusatz = auslesen(inhalt, typ)
    ablegen(inhalt, typ)
    erkannte_art = rechnung.art if rechnung.art in ARTEN else "sonstiges"
    werte = felder(rechnung)
    beleg = Beleg(
        mandant_id=k.mandant.id,
        art=art if art in ARTEN else erkannte_art,
        status="neu",
        dateiname=dateiname[:255],
        dateityp=typ,
        sha256=wert,
        quelle=quelle,
        nachricht_id=nachricht.id if nachricht else None,
        hochgeladen_von=k.id,
        hochgeladen_name=k.name,
        text=text[:60000],
        e_rechnung=format_name,
        erkannt={name: leser for name, w in werte.items() if w not in (None, [], "") and name != "waehrung"},
        **werte,
    )
    db.add(beleg)
    try:
        db.flush()
    except IntegrityError as fehler:
        db.rollback()
        raise Konflikt("Diese Datei wurde bereits erfasst") from fehler
    protokolliere(db, "beleg", beleg, k.name, "hochgeladen", datei=beleg.dateiname, quelle=quelle)
    anzahl = len(beleg.erkannt)
    protokolliere(
        db, "beleg", beleg, leser, "erkannt", art=beleg.art, felder=anzahl, format=format_name or "", werte=uebersicht(beleg)
    )
    zuordnen(db, beleg)
    if beleg.art == "vertrag":
        db.add(Vertrag(beleg_id=beleg.id))
    bewerte(db, beleg, zusatz)
    if beleg.art in RECHNUNGEN:
        melde_pruefung(db, beleg)
    beleg.automatisch = beleg.art in RECHNUNGEN and RANG[beleg.stufe] < RANG["fehler"]
    regel = freigabe.regel_fuer(db, beleg) if beleg.art in RECHNUNGEN else None
    if regel:
        freigabe.automatik_anwenden(k, beleg, regel)
    db.commit()
    return beleg


def uebersicht(beleg: Beleg) -> dict:
    namen = ("lieferant", "nummer", "datum", "leistung_von", "faellig_am", "netto", "ust", "brutto", "iban", "bestellnummer")
    return {name: str(getattr(beleg, name)) for name in namen if getattr(beleg, name) is not None}


def melde_pruefung(db: Session, beleg: Beleg) -> None:
    probleme = [e["text"] for e in beleg.pruefbericht if RANG[e["stufe"]] >= RANG["fehler"]]
    protokolliere(db, "beleg", beleg, "Prüfung", "geprueft", ergebnis=beleg.stufe, probleme=probleme[:8])


def zuordnen(db: Session, beleg: Beleg) -> None:
    partner = erkennung.partner_finden(db, beleg)
    erkannt = dict(beleg.erkannt)
    if partner:
        beleg.partner_id = partner.id
        erkannt["partner_id"] = "Stammdaten"
        if not beleg.faellig_am and beleg.datum and partner.zahlungsziel is not None:
            from datetime import timedelta

            beleg.faellig_am = beleg.datum + timedelta(days=partner.zahlungsziel)
            erkannt["faellig_am"] = "Stammdaten"
        protokolliere(db, "beleg", beleg, "Erkennung", "partner_erkannt", partner=partner.name)
    if beleg.art in RECHNUNGEN:
        for feld, (wert, quelle) in erkennung.kontierung(db, beleg).items():
            setattr(beleg, feld, wert)
            erkannt[feld] = quelle
    beleg.erkannt = erkannt


def pruefe_bearbeitbar(k: Kontext, beleg: Beleg) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf Belege ändern")
    if beleg.status not in BEARBEITBAR:
        raise Konflikt("Beleg kann in diesem Status nicht geändert werden")


def korrigiere(k: Kontext, beleg: Beleg, werte: dict) -> Beleg:
    pruefe_bearbeitbar(k, beleg)
    db = k.db
    if werte.get("art") and werte["art"] not in ARTEN:
        raise Ungueltig("Belegart gibt es nicht")
    if werte.get("partner_id"):
        partner = db.get(Partner, werte["partner_id"])
        if not partner or partner.mandant_id != k.mandant.id:
            raise Ungueltig("Geschäftspartner gibt es nicht")
    alt, neu, erkannt = {}, {}, dict(beleg.erkannt)
    for feld, wert in werte.items():
        if feld in ("iban", "lieferant_uid", "empfaenger_uid", "bic"):
            wert = als_kennung(wert, {"iban": 40, "bic": 11}.get(feld, 20))
        if feld in ("steuerzeilen", "positionen", "aufteilung"):
            wert = wert or []
        if getattr(beleg, feld) != wert:
            alt[feld], neu[feld] = getattr(beleg, feld), wert
            setattr(beleg, feld, wert)
            erkannt.pop(feld, None)
    if not neu:
        return beleg
    beleg.erkannt = erkannt
    if set(neu) - set(KONTIERUNG) - {"partner_id", "art", "aufteilung"}:
        beleg.automatisch = False
    if "partner_id" in neu and beleg.art in RECHNUNGEN:
        for feld, (wert, quelle) in erkennung.kontierung(db, beleg).items():
            if not getattr(beleg, feld) or feld in alt:
                setattr(beleg, feld, wert)
                beleg.erkannt = beleg.erkannt | {feld: quelle}
    if beleg.art == "vertrag" and not db.get(Vertrag, beleg.id):
        db.add(Vertrag(beleg_id=beleg.id))
    beleg.bearbeitet_von = k.id
    bewerte(db, beleg)
    protokolliere(db, "beleg", beleg, k.name, "geaendert", alt=alt, neu=neu, stufe=beleg.stufe)
    db.commit()
    return beleg


def vertrag_aendern(k: Kontext, beleg: Beleg, werte: dict) -> None:
    pruefe_bearbeitbar(k, beleg)
    vertrag = k.db.get(Vertrag, beleg.id)
    if not vertrag:
        raise Konflikt("Beleg ist kein Vertrag")
    for person in [werte.get("verantwortlich_id"), *(werte.get("informieren") or [])]:
        if person and not k.db.get(Mitglied, (k.mandant.id, person)):
            raise Ungueltig("Person gehört nicht zu diesem Mandanten")
    neu = {f: w for f, w in werte.items() if getattr(vertrag, f) != w}
    for feld, wert in neu.items():
        setattr(vertrag, feld, wert)
    if neu:
        protokolliere(k.db, "beleg", beleg, k.name, "vertrag_geaendert", neu=neu)
        k.db.commit()


def nach_freigabe(db: Session, beleg: Beleg) -> None:
    partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
    if partner is None and beleg.lieferant:
        partner = Partner(
            mandant_id=beleg.mandant_id,
            name=beleg.lieferant,
            uid=beleg.lieferant_uid,
            ibans=[],
            kreditor=naechster_kreditor(db, beleg.mandant_id),
        )
        db.add(partner)
        db.flush()
        beleg.partner_id = partner.id
    if partner and beleg.iban and iban_gueltig(beleg.iban) and beleg.iban not in partner.ibans:
        partner.ibans = [*partner.ibans, beleg.iban]
    if beleg.zahlstatus == "offen" and beleg.art == "gutschrift":
        beleg.zahlstatus = "keine"
    from .anforderung import aktualisiere_nach_beleg

    aktualisiere_nach_beleg(db, beleg)


def naechster_kreditor(db: Session, mandant_id: int) -> str:
    nummern = [
        int(n) for n in db.scalars(select(Partner.kreditor).where(Partner.mandant_id == mandant_id)) if n and n.isdigit()
    ]
    return str(max(nummern, default=330000) + 1)


def bestaetige_iban(k: Kontext, beleg: Beleg, grund: str) -> None:
    if not k.hat("freigabe", "admin"):
        raise Verboten("Dafür fehlt das Freigaberecht")
    if not any(e["code"] == "iban_neu" for e in beleg.pruefbericht):
        raise Konflikt("Bei diesem Beleg gibt es keine neue IBAN")
    if beleg.bearbeitet_von == k.id:
        raise Konflikt("Wer bearbeitet hat, darf die IBAN nicht bestätigen")
    beleg.bestaetigte_iban = beleg.iban
    bewerte(k.db, beleg)
    protokolliere(k.db, "beleg", beleg, k.name, "iban_bestaetigt", iban=beleg.iban, grund=grund)
    k.db.commit()


def behalte_duplikat(k: Kontext, beleg: Beleg, grund: str) -> None:
    pruefe_bearbeitbar(k, beleg)
    beleg.kein_duplikat = True
    bewerte(k.db, beleg)
    protokolliere(k.db, "beleg", beleg, k.name, "kein_duplikat", grund=grund)
    k.db.commit()


def in_papierkorb(k: Kontext, beleg: Beleg, grund: str = "") -> None:
    pruefe_bearbeitbar(k, beleg)
    beleg.status = "papierkorb"
    protokolliere(k.db, "beleg", beleg, k.name, "papierkorb", grund=grund)
    k.db.commit()


def wiederherstellen(k: Kontext, beleg: Beleg) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf Belege wiederherstellen")
    if beleg.status != "papierkorb":
        raise Konflikt("Beleg liegt nicht im Papierkorb")
    beleg.status = "neu"
    bewerte(k.db, beleg)
    protokolliere(k.db, "beleg", beleg, k.name, "wiederhergestellt")
    k.db.commit()


def ablegen_im_archiv(k: Kontext, beleg: Beleg) -> None:
    pruefe_bearbeitbar(k, beleg)
    if beleg.art in RECHNUNGEN:
        raise Konflikt("Rechnungen werden freigegeben und nicht abgelegt")
    beleg.status = "abgelegt"
    protokolliere(k.db, "beleg", beleg, k.name, "abgelegt")
    k.db.commit()


def setze_klaerung(k: Kontext, beleg: Beleg, an: bool) -> None:
    pruefe_bearbeitbar(k, beleg)
    beleg.klaerung = an
    protokolliere(k.db, "beleg", beleg, k.name, "klaerung" if an else "klaerung_beendet")
    k.db.commit()


def setze_sichtbarkeit(k: Kontext, beleg: Beleg, an: bool, personen: list[int]) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    for person in personen:
        if not k.db.get(Mitglied, (k.mandant.id, person)):
            raise Ungueltig("Person gehört nicht zu diesem Mandanten")
    beleg.eingeschraenkt = an
    beleg.sichtbar = sorted({*personen, k.id}) if an else []
    protokolliere(k.db, "beleg", beleg, k.name, "sichtbarkeit", eingeschraenkt=an, personen=beleg.sichtbar)
    k.db.commit()


def setze_schlagwoerter(k: Kontext, beleg: Beleg, namen: list[str]) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    sauber = list(dict.fromkeys(" ".join(n.split())[:60] for n in namen if n.strip()))[:20]
    k.db.execute(delete(Schlagwort).where(Schlagwort.beleg_id == beleg.id))
    for name in sauber:
        k.db.add(Schlagwort(beleg_id=beleg.id, name=name))
    protokolliere(k.db, "beleg", beleg, k.name, "schlagwoerter", namen=sauber)
    k.db.commit()


def erwaehnte(db: Session, mandant_id: int, text: str) -> list[int]:
    personen = db.execute(
        select(Benutzer.id, Benutzer.name)
        .join(Mitglied, Mitglied.benutzer_id == Benutzer.id)
        .where(Mitglied.mandant_id == mandant_id)
    )
    return [nummer for nummer, name in personen if re.search(rf"@{re.escape(name)}\b", text)]


def kommentieren(k: Kontext, art: str, objekt, text: str) -> None:
    protokolliere(k.db, art, objekt, k.name, "kommentar", text=text)
    mitteilen(
        k.db,
        k.mandant.id,
        erwaehnte(k.db, k.mandant.id, text),
        f"{k.name} hat dich erwähnt: {text}",
        f"{art}/{objekt.id}",
        k.id,
    )
    k.db.commit()


def anhaengen(k: Kontext, art: str, objekt, dateiname: str, inhalt: bytes) -> Anhang:
    pruefe_groesse(inhalt)
    typ = erkenne_typ(inhalt)
    anhang = Anhang(
        mandant_id=k.mandant.id,
        objekt_art=art,
        objekt_id=objekt.id,
        dateiname=dateiname[:255],
        dateityp=typ,
        sha256=ablegen(inhalt, typ),
        von=k.name,
    )
    k.db.add(anhang)
    protokolliere(k.db, art, objekt, k.name, "anhang", datei=dateiname[:255])
    k.db.commit()
    return anhang


def an_beleg_haengen(k: Kontext, beleg: Beleg, ziel: Beleg) -> None:
    pruefe_bearbeitbar(k, beleg)
    if beleg.id == ziel.id:
        raise Ungueltig("Beleg kann nicht an sich selbst hängen")
    k.db.add(
        Anhang(
            mandant_id=k.mandant.id,
            objekt_art="beleg",
            objekt_id=ziel.id,
            dateiname=beleg.dateiname,
            dateityp=beleg.dateityp,
            sha256=beleg.sha256,
            von=k.name,
        )
    )
    protokolliere(k.db, "beleg", ziel, k.name, "anhang", datei=beleg.dateiname, aus_beleg=beleg.id)
    beleg.status = "papierkorb"
    protokolliere(k.db, "beleg", beleg, k.name, "papierkorb", grund=f"an Beleg {ziel.id} angehängt")
    k.db.commit()


def ordne(a: tuple[str, int], b: tuple[str, int]) -> tuple[tuple[str, int], tuple[str, int]]:
    return (a, b) if a < b else (b, a)


def verknuepfe(k: Kontext, beleg: Beleg, art: str, nummer: int) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    if art == "anforderung":
        ziel = k.db.get(Anforderung, nummer)
        if not ziel or ziel.mandant_id != k.mandant.id:
            raise NichtGefunden("Bestellanforderung nicht gefunden")
        if ziel.status not in ("freigegeben", "teilweise", "erfuellt"):
            raise Konflikt("Nur freigegebene Bestellanforderungen lassen sich verknüpfen")
    elif art == "beleg" and nummer != beleg.id:
        ziel = hole(k, nummer)
    else:
        raise Ungueltig("Verknüpfung ist nicht möglich")
    a, b = ordne(("beleg", beleg.id), (art, nummer))
    if not k.db.get(Verknuepfung, (*a, *b)):
        k.db.add(Verknuepfung(a_art=a[0], a_id=a[1], b_art=b[0], b_id=b[1], mandant_id=k.mandant.id, von=k.name))
        protokolliere(k.db, "beleg", beleg, k.name, "verknuepft", mit=f"{art} {nummer}")
        protokolliere(k.db, art, ziel, k.name, "verknuepft", mit=f"beleg {beleg.id}")
    if art == "anforderung":
        from .anforderung import aktualisiere

        aktualisiere(k.db, ziel)
    k.db.commit()


def loese(k: Kontext, beleg: Beleg, art: str, nummer: int) -> None:
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    a, b = ordne(("beleg", beleg.id), (art, nummer))
    zeile = k.db.get(Verknuepfung, (*a, *b))
    if not zeile or zeile.mandant_id != k.mandant.id:
        raise NichtGefunden("Verknüpfung nicht gefunden")
    k.db.delete(zeile)
    protokolliere(k.db, "beleg", beleg, k.name, "verknuepfung_geloest", mit=f"{art} {nummer}")
    if art == "anforderung":
        from .anforderung import aktualisiere

        k.db.flush()
        aktualisiere(k.db, k.db.get(Anforderung, nummer))
    k.db.commit()


def verlaufs_aktionen(db: Session, beleg: Beleg) -> int:
    return len(
        list(db.scalars(select(Protokoll.id).where(Protokoll.objekt_art == "beleg", Protokoll.objekt_id == beleg.id)))
    )


def vorzeichen(beleg: Beleg) -> Decimal:
    return Decimal(-1) if beleg.art == "gutschrift" else Decimal(1)
