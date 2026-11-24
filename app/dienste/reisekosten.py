import json
import math
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from .fehler import Ungueltig

CENT = Decimal("0.01")
INLAND = "Österreich"
FAHRZEUGE = ("pkw", "motorrad", "fahrrad")


@lru_cache
def saetze() -> dict:
    datei = Path(__file__).parent.parent / "daten" / "reisesaetze.json"
    return json.loads(datei.read_text(encoding="utf-8"))


def laender() -> list[str]:
    return [INLAND, *saetze()["ausland"]]


def satz(land: str, art: str) -> Decimal:
    if land == INLAND:
        return Decimal(saetze()["inland"][art])
    if land not in saetze()["ausland"]:
        raise Ungueltig(f"Für {land} gibt es keinen Satz")
    return Decimal(saetze()["ausland"][land][art])


def runden(wert: Decimal) -> Decimal:
    return wert.quantize(CENT, ROUND_HALF_UP)


def zeitpunkt(wert: str) -> datetime:
    try:
        return datetime.fromisoformat(wert).replace(tzinfo=None)
    except (TypeError, ValueError) as fehler:
        raise Ungueltig("Zeitpunkt ist ungültig") from fehler


def stunden(dauer: timedelta) -> float:
    return dauer.total_seconds() / 3600


def taggeld(etappen: list[dict], ende: str, mahlzeiten: dict | None = None) -> tuple[Decimal, list[dict]]:
    if not etappen:
        raise Ungueltig("Bitte mindestens eine Etappe angeben")
    teile = [(e["land"], zeitpunkt(e["von"])) for e in etappen]
    schluss = zeitpunkt(ende)
    grenzen = [von for _, von in teile] + [schluss]
    if any(a >= b for a, b in zip(grenzen, grenzen[1:], strict=False)):
        raise Ungueltig("Zeiten müssen aufsteigend sein")
    beginn = teile[0][1]
    if schluss - beginn > timedelta(days=180):
        raise Ungueltig("Reise ist länger als 180 Tage")
    mindestens = saetze()["inland"]["stunde_ab"]
    if stunden(schluss - beginn) <= mindestens:
        return Decimal(0), []
    abschnitte = [(land, von, grenzen[i + 1]) for i, (land, von) in enumerate(teile)]
    dauer: dict[str, float] = {}
    for land, von, bis in abschnitte:
        satz(land, "tag")
        dauer[land] = dauer.get(land, 0) + stunden(bis - von)
    ausland = {land for land, h in dauer.items() if land != INLAND and h > mindestens}
    summe, zeilen, block = Decimal(0), [], beginn
    while block < schluss:
        bis = min(block + timedelta(hours=24), schluss)
        gesamt = min(12, math.ceil(stunden(bis - block)))
        uebrig, aussen, betrag_aussen, orte = gesamt, 0, Decimal(0), []
        for land, von, ab in abschnitte:
            if land not in ausland:
                continue
            anteil = stunden(min(bis, ab) - max(block, von))
            if anteil <= 0 or uebrig <= 0:
                continue
            zwoelftel = min(uebrig, math.ceil(anteil))
            uebrig -= zwoelftel
            aussen += zwoelftel
            betrag_aussen += satz(land, "tag") * zwoelftel / 12
            orte.append(land)
        betrag_innen = satz(INLAND, "tag") * uebrig / 12
        gestellt = sum(1 for m in (mahlzeiten or {}).get(block.date().isoformat(), []) if m in ("mittag", "abend"))
        if gestellt and aussen >= uebrig and aussen:
            if gestellt == 2:
                betrag_aussen = betrag_aussen / 3
        elif gestellt:
            betrag_innen = max(Decimal(0), betrag_innen - Decimal(saetze()["inland"]["mahlzeit"]) * gestellt)
        betrag = runden(betrag_aussen + betrag_innen)
        zeilen.append(
            {
                "tag": block.date().isoformat(),
                "zwoelftel": gesamt,
                "land": ", ".join(dict.fromkeys(orte + ([INLAND] if uebrig else []))),
                "mahlzeiten": gestellt,
                "betrag": str(betrag),
            }
        )
        summe += betrag
        block = bis
    return summe, zeilen


def naechtigung(naechte: list[dict], etappen: list[dict], ende: str) -> Decimal:
    if not naechte:
        return Decimal(0)
    moeglich = (zeitpunkt(ende).date() - zeitpunkt(etappen[0]["von"]).date()).days
    if any(int(n["anzahl"]) < 0 for n in naechte) or sum(int(n["anzahl"]) for n in naechte) > moeglich:
        raise Ungueltig(f"Die Reise hat nur {moeglich} Nächte")
    return runden(sum((satz(n["land"], "nacht") * int(n["anzahl"]) for n in naechte), Decimal(0)))


def kilometer(strecke: Decimal, fahrzeug: str, mitfahrer: int = 0) -> Decimal:
    if fahrzeug not in FAHRZEUGE:
        raise Ungueltig("Fahrzeug gibt es nicht")
    if strecke <= 0 or strecke > 5000:
        raise Ungueltig("Kilometer müssen zwischen 1 und 5000 liegen")
    preise = saetze()["kilometer"]
    betrag = strecke * Decimal(preise[fahrzeug])
    if fahrzeug == "pkw" and mitfahrer:
        betrag += strecke * Decimal(preise["mitfahrer"]) * min(max(mitfahrer, 0), 8)
    return runden(betrag)
