from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..modelle import (
    Anforderung,
    Automatik,
    Beleg,
    Benutzer,
    Erstattung,
    Freigabeschritt,
    Mitglied,
    Team,
    Workflow,
    jetzt,
)
from ..sicherheit import Kontext
from . import erkennung
from .fehler import Konflikt, Ungueltig, Verboten
from .protokoll import mitteilen, protokolliere
from .werte import als_betrag

KLASSEN = {"beleg": Beleg, "erstattung": Erstattung, "anforderung": Anforderung}
NAMEN = {"beleg": "Beleg", "erstattung": "Erstattung", "anforderung": "Bestellanforderung"}
OFFEN = {"beleg": ("neu",), "erstattung": ("pruefung",), "anforderung": ("neu",)}


def abwesend(benutzer: Benutzer, heute: date | None = None) -> bool:
    heute = heute or date.today()
    return bool(
        benutzer.vertretung_id
        and benutzer.abwesend_von
        and benutzer.abwesend_von <= heute
        and (benutzer.abwesend_bis is None or heute <= benutzer.abwesend_bis)
    )


def vertretene(db: Session, benutzer_id: int) -> set[int]:
    return {b.id for b in db.scalars(select(Benutzer).where(Benutzer.vertretung_id == benutzer_id)) if abwesend(b)}


def eigene_teams(db: Session, mandant_id: int, ids: set[int]) -> set[int]:
    teams = db.scalars(select(Team).where(Team.mandant_id == mandant_id))
    return {team.id for team in teams if ids & set(team.mitglieder)}


def zustaendig_filter(db: Session, mandant_id: int, benutzer_id: int):
    ids = {benutzer_id} | vertretene(db, benutzer_id)
    teams = eigene_teams(db, mandant_id, ids)
    return or_(
        (Freigabeschritt.ziel_art == "person") & Freigabeschritt.ziel_id.in_(ids),
        (Freigabeschritt.ziel_art == "team") & Freigabeschritt.ziel_id.in_(teams or {-1}),
    )


def personen(db: Session, ziel_art: str, ziel_id: int) -> list[Benutzer]:
    if ziel_art == "team":
        team = db.get(Team, ziel_id)
        ids = team.mitglieder if team else []
    else:
        ids = [ziel_id]
    ergebnis = []
    for benutzer_id in ids:
        benutzer = db.get(Benutzer, benutzer_id)
        if benutzer and benutzer.aktiv:
            ergebnis.append(benutzer)
    return ergebnis


def empfaenger(db: Session, schritt: Freigabeschritt) -> list[int]:
    ids = []
    for benutzer in personen(db, schritt.ziel_art, schritt.ziel_id):
        ids.append(benutzer.vertretung_id if abwesend(benutzer) else benutzer.id)
    return ids


def berechtigt(db: Session, schritt: Freigabeschritt) -> set[int]:
    ids = set()
    for benutzer in personen(db, schritt.ziel_art, schritt.ziel_id):
        ids.add(benutzer.id)
        if abwesend(benutzer):
            ids.add(benutzer.vertretung_id)
    return ids


def schritte(db: Session, art: str, nummer: int, runde: int | None = None) -> list[Freigabeschritt]:
    alle = list(
        db.scalars(
            select(Freigabeschritt)
            .where(Freigabeschritt.objekt_art == art, Freigabeschritt.objekt_id == nummer)
            .order_by(Freigabeschritt.runde, Freigabeschritt.reihenfolge)
        )
    )
    letzte = max((s.runde for s in alle), default=0)
    return [s for s in alle if s.runde == (runde or letzte)]


def betrag(objekt):
    if isinstance(objekt, Beleg):
        return objekt.brutto or 0
    if isinstance(objekt, Anforderung):
        return objekt.netto
    from .erstattung import summe

    return summe(objekt)


def passt(workflow: Workflow, art: str, objekt) -> bool:
    b = workflow.bedingung
    wert = betrag(objekt)
    return (
        (not b.get("art") or b["art"] == art)
        and (not b.get("ab") or wert >= als_betrag(b["ab"]))
        and (not b.get("bis") or wert <= als_betrag(b["bis"]))
        and (not b.get("kostenstelle") or b["kostenstelle"] == objekt.kostenstelle)
        and (not b.get("partner_id") or b["partner_id"] == getattr(objekt, "partner_id", None))
    )


def workflow_finden(db: Session, art: str, objekt) -> Workflow | None:
    alle = db.scalars(select(Workflow).where(Workflow.mandant_id == objekt.mandant_id).order_by(Workflow.rang, Workflow.id))
    return next((w for w in alle if passt(w, art, objekt)), None)


def waehle_workflow(k: Kontext, art: str, objekt, workflow_id: int | None = None) -> Workflow:
    if workflow_id:
        workflow = k.db.get(Workflow, workflow_id)
        if not workflow or workflow.mandant_id != k.mandant.id:
            raise Ungueltig("Workflow gibt es nicht")
        return workflow
    workflow = workflow_finden(k.db, art, objekt)
    if not workflow:
        raise Konflikt("Kein Workflow passt zu diesem Vorgang")
    return workflow


def pruefe_ziele(db: Session, mandant_id: int, ziele: list[dict]) -> None:
    if not ziele or len(ziele) > 6:
        raise Ungueltig("Bitte ein bis sechs Freigabeschritte wählen")
    for ziel in ziele:
        if ziel["art"] == "team":
            team = db.get(Team, ziel["id"])
            if not team or team.mandant_id != mandant_id or not team.mitglieder:
                raise Ungueltig("Team gibt es nicht oder es ist leer")
        else:
            mitglied = db.get(Mitglied, (mandant_id, ziel["id"]))
            if not mitglied or not {"freigabe", "admin"} & set(mitglied.rollen):
                raise Ungueltig("Person darf nicht freigeben")


def pruefe_bereit(art: str, objekt, grund: str | None) -> None:
    if objekt.status not in OFFEN[art]:
        raise Konflikt(f"{NAMEN[art]} ist nicht mehr offen")
    if art != "beleg":
        return
    if objekt.art not in ("rechnung", "gutschrift"):
        raise Konflikt("Nur Rechnungen und Gutschriften werden freigegeben")
    if objekt.stufe == "sperre":
        raise Konflikt("Beleg ist gesperrt, bitte zuerst die Prüfung klären")
    if objekt.stufe == "fehler" and not (grund or "").strip():
        raise Konflikt("Prüfung hat Fehler gefunden, bitte eine Begründung angeben", grund_noetig=True)
    if not (objekt.konto and objekt.kostenstelle) and not objekt.aufteilung:
        raise Konflikt("Konto und Kostenstelle fehlen")


def anfordern(k: Kontext, art: str, objekt, ziele: list[dict], grund: str | None = None, name: str = "") -> None:
    db = k.db
    pruefe_bereit(art, objekt, grund)
    pruefe_ziele(db, objekt.mandant_id, ziele)
    runde = max((s.runde for s in schritte(db, art, objekt.id)), default=0) + 1
    for reihe, ziel in enumerate(ziele, 1):
        db.add(
            Freigabeschritt(
                mandant_id=objekt.mandant_id,
                objekt_art=art,
                objekt_id=objekt.id,
                runde=runde,
                reihenfolge=reihe,
                ziel_art=ziel["art"],
                ziel_id=ziel["id"],
                status="offen" if reihe == 1 else "wartet",
                angefragt_von=k.id,
            )
        )
    objekt.status = "freigabe"
    if art == "beleg":
        objekt.klaerung = False
    protokolliere(db, art, objekt, k.name, "freigabe_angefordert", workflow=name, schritte=len(ziele), grund=grund or "")
    melde_schritt(db, art, objekt, schritte(db, art, objekt.id)[0])


def melde_schritt(db: Session, art: str, objekt, schritt: Freigabeschritt) -> None:
    text = f"{NAMEN[art]} {objekt.id} wartet auf deine Freigabe"
    mitteilen(db, objekt.mandant_id, empfaenger(db, schritt), text, f"{art}/{objekt.id}")


def pruefe_vier_augen(k: Kontext, art: str, objekt) -> None:
    if not k.mandant.einstellungen.get("vier_augen", True):
        return
    if objekt.bearbeitet_von and objekt.bearbeitet_von == k.id:
        raise Konflikt("Wer bearbeitet hat, darf nicht selbst freigeben")
    if art != "beleg" and objekt.benutzer_id == k.id:
        raise Konflikt("Eigene Anträge darf man nicht selbst freigeben")


def abschliessen(k: Kontext, art: str, objekt) -> None:
    objekt.status = "freigegeben"
    objekt.freigegeben_am = jetzt()
    if art == "beleg":
        from .belege import nach_freigabe

        nach_freigabe(k.db, objekt)
    elif art == "anforderung":
        from .anforderung import nach_freigabe as nummer_vergeben

        nummer_vergeben(k.db, objekt)
    if art != "beleg":
        mitteilen(
            k.db,
            objekt.mandant_id,
            [objekt.benutzer_id],
            f"{NAMEN[art]} {objekt.id} wurde freigegeben",
            f"{art}/{objekt.id}",
            k.id,
        )


def sofort(k: Kontext, art: str, objekt, grund: str | None = None) -> None:
    if not k.hat("freigabe"):
        raise Verboten("Dafür fehlt das Freigaberecht")
    pruefe_bereit(art, objekt, grund)
    pruefe_vier_augen(k, art, objekt)
    abschliessen(k, art, objekt)
    protokolliere(k.db, art, objekt, k.name, "freigegeben", sofort=True, grund=grund or "")


def entscheiden(k: Kontext, art: str, objekt, ja: bool, grund: str | None = None) -> None:
    db = k.db
    if objekt.status != "freigabe":
        raise Konflikt(f"{NAMEN[art]} wartet nicht auf Freigabe")
    offen = next((s for s in schritte(db, art, objekt.id) if s.status == "offen"), None)
    if not offen:
        raise Konflikt("Kein offener Freigabeschritt")
    if k.id not in berechtigt(db, offen):
        raise Verboten("Dieser Freigabeschritt ist einer anderen Person zugewiesen")
    if ja:
        pruefe_vier_augen(k, art, objekt)
        if art == "beleg":
            from .belege import bewerte

            bewerte(db, objekt)
            if objekt.stufe == "sperre":
                db.commit()
                raise Konflikt("Beleg ist gesperrt, bitte zuerst die Prüfung klären")
    elif not (grund or "").strip():
        raise Ungueltig("Bitte einen Grund angeben")
    direkt = {p.id for p in personen(db, offen.ziel_art, offen.ziel_id)}
    offen.entschieden_von = k.id
    offen.entschieden_am = jetzt()
    offen.status = "freigegeben" if ja else "abgelehnt"
    if k.id not in direkt:
        offen.in_vertretung = next((p for p in direkt if p in vertretene(db, k.id)), None)
    vertretung = db.get(Benutzer, offen.in_vertretung).name if offen.in_vertretung else ""
    if not ja:
        for schritt in schritte(db, art, objekt.id):
            if schritt.status == "wartet":
                schritt.status = "entfallen"
        objekt.status = "abgelehnt"
        protokolliere(db, art, objekt, k.name, "abgelehnt", grund=grund, vertretung=vertretung)
        betroffen = [offen.angefragt_von, getattr(objekt, "benutzer_id", None)]
        mitteilen(
            db,
            objekt.mandant_id,
            betroffen,
            f"{NAMEN[art]} {objekt.id} wurde abgelehnt: {grund}",
            f"{art}/{objekt.id}",
            k.id,
        )
        return
    naechster = next((s for s in schritte(db, art, objekt.id) if s.status == "wartet"), None)
    if naechster:
        naechster.status = "offen"
        protokolliere(db, art, objekt, k.name, "schritt_freigegeben", schritt=offen.reihenfolge, vertretung=vertretung)
        melde_schritt(db, art, objekt, naechster)
        return
    abschliessen(k, art, objekt)
    protokolliere(db, art, objekt, k.name, "freigegeben", schritt=offen.reihenfolge, vertretung=vertretung)


def weiterleiten(k: Kontext, art: str, objekt, ziel: dict, grund: str) -> None:
    offen = next((s for s in schritte(k.db, art, objekt.id) if s.status == "offen"), None)
    if objekt.status != "freigabe" or not offen:
        raise Konflikt(f"{NAMEN[art]} wartet nicht auf Freigabe")
    if k.id not in berechtigt(k.db, offen) and not k.hat("admin"):
        raise Verboten("Dieser Freigabeschritt ist einer anderen Person zugewiesen")
    pruefe_ziele(k.db, objekt.mandant_id, [ziel])
    offen.ziel_art, offen.ziel_id = ziel["art"], ziel["id"]
    protokolliere(k.db, art, objekt, k.name, "weitergeleitet", schritt=offen.reihenfolge, grund=grund)
    melde_schritt(k.db, art, objekt, offen)


def zurueckziehen(k: Kontext, art: str, objekt) -> None:
    if objekt.status != "freigabe":
        raise Konflikt(f"{NAMEN[art]} wartet nicht auf Freigabe")
    reihe = schritte(k.db, art, objekt.id)
    if not k.hat("buchhaltung", "admin") and k.id not in {s.angefragt_von for s in reihe}:
        raise Verboten("Nur die anfragende Person oder die Buchhaltung darf zurückziehen")
    for schritt in reihe:
        if schritt.status in ("offen", "wartet"):
            schritt.status = "entfallen"
    objekt.status = OFFEN[art][0]
    protokolliere(k.db, art, objekt, k.name, "zurueckgezogen")


def wieder_oeffnen(k: Kontext, art: str, objekt) -> None:
    if objekt.status != "abgelehnt":
        raise Konflikt("Nur abgelehnte Vorgänge lassen sich wieder öffnen")
    objekt.status = OFFEN[art][0]
    protokolliere(k.db, art, objekt, k.name, "wieder_geoeffnet")


def regel_fuer(db: Session, beleg: Beleg) -> Automatik | None:
    if beleg.status != "neu" or beleg.stufe in ("fehler", "sperre") or beleg.klaerung:
        return None
    if not (beleg.partner_id and beleg.konto and beleg.kostenstelle) or beleg.brutto is None:
        return None
    gleiche = erkennung.gleiche_buchungen(db, beleg)
    regeln = db.scalars(
        select(Automatik)
        .where(Automatik.mandant_id == beleg.mandant_id, Automatik.aktiv.is_(True))
        .order_by(Automatik.partner_id.is_(None), Automatik.id)
    )
    for regel in regeln:
        if regel.partner_id in (None, beleg.partner_id) and beleg.brutto <= regel.max_brutto and gleiche >= regel.gleiche:
            return regel
    return None


def automatik_anwenden(k: Kontext, beleg: Beleg, regel: Automatik) -> bool:
    maschine = Kontext(k.db, k.mandant, "Automatik", {"freigabe", "buchhaltung"})
    if regel.aktion == "freigeben":
        beleg.automatik = "freigegeben"
        abschliessen(maschine, "beleg", beleg)
        protokolliere(k.db, "beleg", beleg, "Automatik", "freigegeben", regel=regel.name)
        return True
    if regel.aktion == "anfordern":
        workflow = k.db.get(Workflow, regel.workflow_id) if regel.workflow_id else workflow_finden(k.db, "beleg", beleg)
        if not workflow:
            return False
        try:
            anfordern(maschine, "beleg", beleg, workflow.schritte, name=workflow.name)
        except (Konflikt, Ungueltig) as fehler:
            protokolliere(k.db, "beleg", beleg, "Automatik", "automatik_fehler", regel=regel.name, grund=str(fehler))
            return False
        beleg.automatik = "angefordert"
        return True
    return False


def als_liste(db: Session, art: str, nummer: int) -> list[dict]:
    ergebnis = []
    for s in schritte(db, art, nummer):
        if s.ziel_art == "team":
            team = db.get(Team, s.ziel_id)
            ziel = f"Team {team.name}" if team else "Team"
        else:
            ziel = db.get(Benutzer, s.ziel_id).name
        hinweis = None
        if s.status == "offen" and s.ziel_art == "person":
            person = db.get(Benutzer, s.ziel_id)
            if abwesend(person):
                hinweis = f"abwesend, Vertretung: {db.get(Benutzer, person.vertretung_id).name}"
        ergebnis.append(
            {
                "reihenfolge": s.reihenfolge,
                "ziel": ziel,
                "status": s.status,
                "von": db.get(Benutzer, s.entschieden_von).name if s.entschieden_von else None,
                "in_vertretung": db.get(Benutzer, s.in_vertretung).name if s.in_vertretung else None,
                "am": s.entschieden_am.isoformat() if s.entschieden_am else None,
                "hinweis": hinweis,
            }
        )
    return ergebnis
