from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import Field
from sqlalchemy import select

from ..dienste import anforderung, belege, erkennung, freigabe, listen, pruefung, zahlung
from ..dienste.fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from ..dienste.protokoll import verlauf
from ..dienste.werte import ARTEN
from ..modelle import Anforderung, Anhang, Beleg, Nachricht, Partner, Schlagwort, Transaktion, Vertrag
from ..sicherheit import Kontext, Mitglieder
from .gemeinsam import (
    Ab,
    Datei,
    Eingabe,
    Geld,
    Grenze,
    Kommentar,
    auszug,
    bild_antwort,
    datei_antwort,
    lies_datei,
    partnername,
    person,
    zeichen,
)

router = APIRouter(prefix="/api/m/{mandant_id}", tags=["Belege"])

KURZ = (
    "id",
    "art",
    "status",
    "lieferant",
    "partner_id",
    "nummer",
    "datum",
    "faellig_am",
    "brutto",
    "netto",
    "waehrung",
    "konto",
    "kostenstelle",
    "stufe",
    "e_rechnung",
    "quelle",
    "dateityp",
    "dateiname",
    "zahlstatus",
    "klaerung",
    "eingeschraenkt",
    "automatik",
    "automatisch",
    "erstellt_am",
    "freigegeben_am",
)
LANG = (
    *KURZ,
    "hochgeladen_name",
    "lieferant_adresse",
    "lieferant_uid",
    "empfaenger",
    "empfaenger_adresse",
    "empfaenger_uid",
    "leistung_von",
    "leistung_bis",
    "skonto_bis",
    "skonto_prozent",
    "bestellnummer",
    "iban",
    "bic",
    "ust",
    "steuerzeilen",
    "positionen",
    "kostentraeger",
    "steuerschluessel",
    "buchungstext",
    "notiz",
    "aufteilung",
    "erkannt",
    "pruefbericht",
    "sichtbar",
    "kein_duplikat",
    "bearbeitet_von",
    "bestaetigte_iban",
)
VERTRAG = ("typ", "beginn", "ende", "kuendigen_bis", "erinnerung_am", "verantwortlich_id", "informieren")
Art = Literal[ARTEN]
Sortierung = Literal["neu", "alt", "faellig", "betrag", "lieferant"]


class Aufteilung(Eingabe):
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    netto: Geld
    satz: zeichen(6, 1) = "20"
    text: zeichen(200) | None = None


class SteuerEingabe(Eingabe):
    satz: zeichen(6, 1)
    netto: Geld
    ust: Geld


class Aenderung(Eingabe):
    art: Art | None = None
    partner_id: int | None = None
    lieferant: zeichen(255) | None = None
    lieferant_adresse: zeichen(300) | None = None
    lieferant_uid: zeichen(20) | None = None
    empfaenger: zeichen(255) | None = None
    empfaenger_adresse: zeichen(300) | None = None
    empfaenger_uid: zeichen(20) | None = None
    nummer: zeichen(80) | None = None
    datum: date | None = None
    leistung_von: date | None = None
    leistung_bis: date | None = None
    faellig_am: date | None = None
    skonto_bis: date | None = None
    skonto_prozent: Annotated[str, Field(pattern=r"^\d{1,2}(\.\d{1,2})?$")] | None = None
    bestellnummer: zeichen(80) | None = None
    iban: zeichen(40) | None = None
    bic: zeichen(11) | None = None
    waehrung: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    netto: Geld | None = None
    ust: Geld | None = None
    brutto: Geld | None = None
    steuerzeilen: Annotated[list[SteuerEingabe], Field(max_length=10)] | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    kostentraeger: zeichen(20) | None = None
    steuerschluessel: zeichen(20) | None = None
    buchungstext: zeichen(200) | None = None
    notiz: zeichen(1000) | None = None
    aufteilung: Annotated[list[Aufteilung], Field(max_length=30)] | None = None


class VertragEingabe(Eingabe):
    typ: zeichen(80) | None = None
    beginn: date | None = None
    ende: date | None = None
    kuendigen_bis: date | None = None
    erinnerung_am: date | None = None
    verantwortlich_id: int | None = None
    informieren: Annotated[list[int], Field(max_length=20)] | None = None


class Aktion(Eingabe):
    aktion: Literal[
        "papierkorb",
        "wiederherstellen",
        "ablegen",
        "klaerung",
        "klaerung_ende",
        "kein_duplikat",
        "iban_bestaetigen",
        "keine_zahlung",
    ]
    grund: zeichen(500) | None = None


class Sammel(Eingabe):
    nummern: Annotated[list[int], Field(min_length=1, max_length=100)]
    aktion: Literal["papierkorb", "klaerung", "ablegen", "freigeben", "anfordern", "automatik"]
    workflow_id: int | None = None


class Schlagwoerter(Eingabe):
    namen: Annotated[list[zeichen(60, 1)], Field(max_length=20)]


class Sichtbarkeit(Eingabe):
    eingeschraenkt: bool
    personen: Annotated[list[int], Field(max_length=50)] = []


class Verweis(Eingabe):
    art: Literal["beleg", "anforderung"]
    id: int


class Ziel(Eingabe):
    ziel: int


def kurz(k: Kontext, beleg: Beleg, anmerkungen: dict | None = None) -> dict:
    codes = {e["code"] for e in beleg.pruefbericht if e["stufe"] in ("fehler", "sperre")}
    heute = date.today()
    ergebnis = auszug(beleg, *KURZ) | {
        "partner": partnername(k.db, beleg.partner_id),
        "duplikat": "duplikat" in codes,
        "probleme": sum(1 for e in beleg.pruefbericht if e["stufe"] in ("fehler", "sperre")),
        "ueberfaellig": bool(beleg.faellig_am and beleg.faellig_am < heute and beleg.zahlstatus == "offen"),
        "bereit": beleg.status == "neu" and beleg.stufe in ("ok", "warnung") and bool(beleg.konto and beleg.kostenstelle),
    }
    if anmerkungen is not None:
        ergebnis |= anmerkungen.get(beleg.id, {})
    return ergebnis


def verweise(k: Kontext, beleg: Beleg) -> list[dict]:
    ergebnis = []
    for art, nummer in sorted(erkennung.verknuepft(k.db, "beleg", beleg.id)):
        if art == "anforderung":
            ziel = k.db.get(Anforderung, nummer)
            ergebnis.append({"art": art, "id": nummer, "name": f"{ziel.nummer} {ziel.titel}", "hinweis": ziel.status})
        else:
            try:
                ziel = belege.hole(k, nummer)
            except NichtGefunden:
                continue
            ergebnis.append(
                {"art": art, "id": nummer, "name": f"{ziel.art} {ziel.nummer or ziel.id}", "hinweis": ziel.status}
            )
    return ergebnis


def vorschlaege(k: Kontext, beleg: Beleg) -> list[dict]:
    ergebnis = []
    for art, nummer, grund in erkennung.passende(k.db, beleg):
        if art == "anforderung":
            ziel = k.db.get(Anforderung, nummer)
            name = f"{ziel.nummer} {ziel.titel}"
        else:
            try:
                ziel = belege.hole(k, nummer)
            except NichtGefunden:
                continue
            name = f"{ziel.art} {ziel.nummer or ziel.id}"
        ergebnis.append({"art": art, "id": nummer, "name": name, "hinweis": grund})
    return ergebnis


def lang(k: Kontext, beleg: Beleg) -> dict:
    db = k.db
    vertrag = db.get(Vertrag, beleg.id)
    nachricht = db.get(Nachricht, beleg.nachricht_id) if beleg.nachricht_id else None
    transaktion = db.scalar(select(Transaktion).where(Transaktion.beleg_id == beleg.id))
    workflow = freigabe.workflow_finden(db, "beleg", beleg) if beleg.status == "neu" else None
    regel = freigabe.regel_fuer(db, beleg) if beleg.status == "neu" else None
    doppelt = (
        pruefung.duplikate(db, beleg)[:1] if not beleg.kein_duplikat and beleg.art in ("rechnung", "gutschrift") else []
    )
    partner = db.get(Partner, beleg.partner_id) if beleg.partner_id else None
    anhaenge = db.scalars(
        select(Anhang).where(Anhang.objekt_art == "beleg", Anhang.objekt_id == beleg.id).order_by(Anhang.id)
    )
    return (
        kurz(k, beleg)
        | auszug(beleg, *LANG)
        | {
            "partner": auszug(partner, "id", "name", "kreditor", "uid") if partner else None,
            "bearbeitet_name": person(db, beleg.bearbeitet_von),
            "vertrag": auszug(vertrag, *VERTRAG) if vertrag else None,
            "nachricht": auszug(nachricht, "id", "absender", "betreff", "text", "empfangen_am") if nachricht else None,
            "transaktion": auszug(transaktion, "id", "datum", "haendler", "betrag", "waehrung") if transaktion else None,
            "schlagwoerter": sorted(db.scalars(select(Schlagwort.name).where(Schlagwort.beleg_id == beleg.id))),
            "schlagwort_vorschlaege": erkennung.schlagwoerter(db, beleg),
            "anhaenge": [auszug(a, "id", "dateiname", "dateityp", "von", "erstellt_am") for a in anhaenge],
            "verknuepfungen": verweise(k, beleg),
            "verknuepfung_vorschlaege": vorschlaege(k, beleg),
            "abgleich": anforderung.abgleich(db, beleg),
            "freigabe": freigabe.als_liste(db, "beleg", beleg.id),
            "freigabe_moeglich": kann_entscheiden(k, "beleg", beleg),
            "workflow": auszug(workflow, "id", "name") if workflow else None,
            "regel": auszug(regel, "name", "aktion") if regel else None,
            "duplikat_von": doppelt[0].id if doppelt else None,
            "verlauf": verlauf(db, "beleg", beleg.id),
            "darf_aendern": k.hat("buchhaltung", "admin") and beleg.status in belege.BEARBEITBAR,
        }
    )


def kann_entscheiden(k: Kontext, art: str, objekt) -> bool:
    if objekt.status != "freigabe":
        return False
    offen = next((s for s in freigabe.schritte(k.db, art, objekt.id) if s.status == "offen"), None)
    return bool(offen and k.id in freigabe.berechtigt(k.db, offen))


def seite(k: Kontext, ergebnis: dict) -> dict:
    notizen = listen.anmerkungen(k, [b.id for b in ergebnis["belege"]])
    return {
        "gesamt": ergebnis["gesamt"],
        "summe": ergebnis["summe"],
        "eintraege": [kurz(k, b, notizen) for b in ergebnis["belege"]],
    }


class Filter(Eingabe):
    suche: zeichen(80) | None = None
    modus: Literal["enthaelt", "beginnt", "exakt"] = "enthaelt"
    art: Art | None = None
    partner_id: int | None = None
    konto: zeichen(20) | None = None
    kostenstelle: zeichen(20) | None = None
    kostentraeger: zeichen(20) | None = None
    stufe: Literal["ok", "warnung", "fehler", "sperre"] | None = None
    quelle: zeichen(20) | None = None
    zahlstatus: Literal["offen", "bezahlt", "keine", "karte"] | None = None
    merkmal: Literal["ueberfaellig", "e_rechnung", "duplikat", "automatik", "eingeschraenkt"] | None = None
    schlagwort: zeichen(60) | None = None
    von: date | None = None
    bis: date | None = None
    betrag_ab: zeichen(20) | None = None
    betrag_bis: zeichen(20) | None = None
    sortierung: Sortierung = "neu"
    grenze: Grenze = 50
    ab: Ab = 0


class EingangFilter(Filter):
    reiter: Literal["rechnungen", "vertraege", "dokumente"] = "rechnungen"
    klaerung: bool = False


class ArchivFilter(Filter):
    status: Literal["neu", "freigabe", "freigegeben", "exportiert", "abgelehnt", "abgelegt", "papierkorb"] | None = None


@router.get("/eingang")
def eingang(k: Mitglieder, f: Annotated[EingangFilter, Query()]):
    ergebnis = listen.eingang(k, f.reiter, f.klaerung, f.model_dump(), f.sortierung, f.grenze, f.ab)
    antwort = seite(k, ergebnis)
    if f.reiter == "rechnungen" and not f.klaerung and k.hat("buchhaltung", "admin"):
        offen = k.db.scalars(select(Beleg).where(Beleg.mandant_id == k.mandant.id, Beleg.status == "neu"))
        antwort["automatik"] = [b.id for b in offen if freigabe.regel_fuer(k.db, b)]
    return antwort


@router.get("/archiv")
def archiv(k: Mitglieder, f: Annotated[ArchivFilter, Query()]):
    return seite(k, listen.archiv(k, f.status, f.model_dump(), f.sortierung, f.grenze, f.ab))


@router.get("/vertraege")
def vertraege(k: Mitglieder, sortierung: Literal["frist", "erinnerung", "ende", "neu"] = "frist"):
    return [
        kurz(k, b) | {"vertrag": auszug(v, *VERTRAG), "verantwortlich": person(k.db, v.verantwortlich_id)}
        for b, v in listen.vertraege(k, sortierung)
    ]


@router.post("/belege", status_code=201)
def hochladen(
    k: Mitglieder,
    dateien: Annotated[list[UploadFile], File()],
    art: Art | None = None,
):
    if not k.hat("buchhaltung", "admin", "mitarbeit", "freigabe"):
        raise Verboten("Dafür fehlt die Berechtigung")
    if len(dateien) > 20:
        raise Ungueltig("Höchstens 20 Dateien auf einmal")
    ergebnis = []
    for datei in dateien:
        name, inhalt = lies_datei(datei)
        try:
            beleg = belege.nimm_auf(k, name, inhalt, "upload", art)
            ergebnis.append(
                {"dateiname": name, "id": beleg.id, "art": beleg.art, "stufe": beleg.stufe, "status": beleg.status}
            )
        except Konflikt as fehler:
            ergebnis.append({"dateiname": name, "fehler": str(fehler), "id": fehler.angaben.get("beleg_id")})
        except Ungueltig as fehler:
            ergebnis.append({"dateiname": name, "fehler": str(fehler), "id": None})
    return ergebnis


@router.get("/belege/{nummer}")
def einzeln(nummer: int, k: Mitglieder):
    return lang(k, belege.hole(k, nummer))


@router.patch("/belege/{nummer}")
def aendern(nummer: int, eingabe: Aenderung, k: Mitglieder):
    werte = eingabe.model_dump(exclude_unset=True)
    for name in ("steuerzeilen", "aufteilung"):
        if werte.get(name):
            werte[name] = [{f: str(w) if w is not None else None for f, w in zeile.items()} for zeile in werte[name]]
    if "waehrung" in werte and not werte["waehrung"]:
        del werte["waehrung"]
    if "art" in werte and not werte["art"]:
        del werte["art"]
    return lang(k, belege.korrigiere(k, belege.hole(k, nummer), werte))


@router.patch("/belege/{nummer}/vertrag")
def vertrag_aendern(nummer: int, eingabe: VertragEingabe, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    werte = eingabe.model_dump(exclude_unset=True)
    if "informieren" in werte:
        werte["informieren"] = werte["informieren"] or []
    belege.vertrag_aendern(k, beleg, werte)
    return lang(k, beleg)


@router.get("/belege/{nummer}/datei")
def datei(nummer: int, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    return datei_antwort(beleg.sha256, beleg.dateityp, beleg.dateiname)


@router.get("/belege/{nummer}/bild")
def bild(nummer: int, k: Mitglieder, seite: Annotated[int, Query(ge=1, le=500)] = 1):
    beleg = belege.hole(k, nummer)
    return bild_antwort(beleg.sha256, beleg.dateityp, seite)


@router.post("/belege/{nummer}/kommentar", status_code=201)
def kommentieren(nummer: int, eingabe: Kommentar, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.kommentieren(k, "beleg", beleg, eingabe.text)
    return lang(k, beleg)


@router.post("/belege/{nummer}/aktion")
def aktion(nummer: int, eingabe: Aktion, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    grund = eingabe.grund or ""
    if eingabe.aktion in ("kein_duplikat", "iban_bestaetigen", "keine_zahlung") and len(grund) < 3:
        raise Ungueltig("Bitte einen Grund angeben")
    if eingabe.aktion == "keine_zahlung" and not k.hat("buchhaltung", "admin"):
        raise Verboten("Nur die Buchhaltung darf das ändern")
    {
        "papierkorb": lambda: belege.in_papierkorb(k, beleg, grund),
        "wiederherstellen": lambda: belege.wiederherstellen(k, beleg),
        "ablegen": lambda: belege.ablegen_im_archiv(k, beleg),
        "klaerung": lambda: belege.setze_klaerung(k, beleg, True),
        "klaerung_ende": lambda: belege.setze_klaerung(k, beleg, False),
        "kein_duplikat": lambda: belege.behalte_duplikat(k, beleg, grund),
        "iban_bestaetigen": lambda: belege.bestaetige_iban(k, beleg, grund),
        "keine_zahlung": lambda: zahlung.ohne_zahlung(k, beleg, grund),
    }[eingabe.aktion]()
    return lang(k, beleg)


@router.post("/belege/sammel")
def sammel(eingabe: Sammel, k: Mitglieder):
    if not k.hat("buchhaltung", "admin"):
        raise Verboten("Dafür fehlt die Berechtigung")
    fertig, fehler = [], []
    for nummer in dict.fromkeys(eingabe.nummern):
        try:
            beleg = belege.hole(k, nummer)
            einzelaktion(k, beleg, eingabe)
            k.db.commit()
            fertig.append(nummer)
        except (Konflikt, Ungueltig, Verboten, NichtGefunden) as grund:
            k.db.rollback()
            fehler.append({"id": nummer, "grund": str(grund)})
    return {"fertig": fertig, "fehler": fehler}


def einzelaktion(k: Kontext, beleg: Beleg, eingabe: Sammel) -> None:
    if eingabe.aktion == "papierkorb":
        belege.in_papierkorb(k, beleg)
    elif eingabe.aktion == "klaerung":
        belege.setze_klaerung(k, beleg, not beleg.klaerung)
    elif eingabe.aktion == "ablegen":
        belege.ablegen_im_archiv(k, beleg)
    elif eingabe.aktion == "freigeben":
        freigabe.sofort(k, "beleg", beleg)
    elif eingabe.aktion == "automatik":
        regel = freigabe.regel_fuer(k.db, beleg)
        if not regel or not freigabe.automatik_anwenden(k, beleg, regel):
            raise Konflikt("Keine passende Regel")
    else:
        workflow = freigabe.waehle_workflow(k, "beleg", beleg, eingabe.workflow_id)
        freigabe.anfordern(k, "beleg", beleg, workflow.schritte, name=workflow.name)


@router.put("/belege/{nummer}/schlagwoerter")
def schlagwoerter(nummer: int, eingabe: Schlagwoerter, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.setze_schlagwoerter(k, beleg, eingabe.namen)
    return lang(k, beleg)


@router.put("/belege/{nummer}/sichtbarkeit")
def sichtbarkeit(nummer: int, eingabe: Sichtbarkeit, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.setze_sichtbarkeit(k, beleg, eingabe.eingeschraenkt, eingabe.personen)
    return lang(k, beleg)


@router.post("/belege/{nummer}/verknuepfung", status_code=201)
def verknuepfen(nummer: int, eingabe: Verweis, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.verknuepfe(k, beleg, eingabe.art, eingabe.id)
    return lang(k, beleg)


@router.delete("/belege/{nummer}/verknuepfung/{art}/{ziel}")
def loesen(nummer: int, art: Literal["beleg", "anforderung"], ziel: int, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.loese(k, beleg, art, ziel)
    return lang(k, beleg)


@router.post("/belege/{nummer}/anhaenge", status_code=201)
def anhang_hochladen(nummer: int, datei: Datei, k: Mitglieder):
    beleg = belege.hole(k, nummer)
    belege.anhaengen(k, "beleg", beleg, *lies_datei(datei))
    return lang(k, beleg)


@router.post("/belege/{nummer}/anhaengen")
def an_anderen(nummer: int, eingabe: Ziel, k: Mitglieder):
    beleg, ziel = belege.hole(k, nummer), belege.hole(k, eingabe.ziel)
    belege.an_beleg_haengen(k, beleg, ziel)
    return lang(k, ziel)


@router.get("/anhaenge/{nummer}/datei")
def anhang_datei(nummer: int, k: Mitglieder):
    anhang = k.db.get(Anhang, nummer)
    if not anhang or anhang.mandant_id != k.mandant.id:
        raise NichtGefunden("Anhang nicht gefunden")
    if anhang.objekt_art == "beleg":
        belege.hole(k, anhang.objekt_id)
    elif not k.sieht_alles:
        raise NichtGefunden("Anhang nicht gefunden")
    return datei_antwort(anhang.sha256, anhang.dateityp, anhang.dateiname)
