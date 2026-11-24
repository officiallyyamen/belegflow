from email.utils import parseaddr

from sqlalchemy import select

from ..modelle import Nachricht, Sperre
from ..sicherheit import Kontext
from . import belege
from .fehler import Konflikt, Ungueltig
from .protokoll import beim_mandanten


def adresse(absender: str) -> str:
    gefunden = parseaddr(absender)[1].lower()
    return (gefunden or absender.strip().lower())[:300]


def ist_gesperrt(k: Kontext, absender: str) -> bool:
    namen = {absender, absender.rsplit("@", 1)[-1]}
    return bool(
        k.db.scalar(
            select(Sperre.id)
            .where(Sperre.mandant_id == k.mandant.id, Sperre.art == "absender", Sperre.wert.in_(namen))
            .limit(1)
        )
    )


def nachricht_fuer(k: Kontext, kopf: dict, status: str) -> Nachricht | None:
    if not (kopf["kennung"] or kopf["absender"]):
        return None
    absender = adresse(kopf["absender"])
    kennung = kopf["kennung"] or f"{absender}|{kopf['betreff']}"[:300]
    vorhanden = k.db.scalar(select(Nachricht).where(Nachricht.mandant_id == k.mandant.id, Nachricht.kennung == kennung))
    if vorhanden:
        return vorhanden
    nachricht = Nachricht(
        mandant_id=k.mandant.id,
        kennung=kennung,
        absender=absender,
        betreff=kopf["betreff"],
        text=kopf["text"][:20000],
        status=status,
    )
    k.db.add(nachricht)
    k.db.flush()
    return nachricht


def antwort(nachricht: Nachricht | None, status: str, hinweis: str = "", beleg=None) -> dict:
    probleme = [e["text"] for e in beleg.pruefbericht if e["stufe"] in ("fehler", "sperre")] if beleg else []
    return {
        "status": status,
        "hinweis": hinweis,
        "nachricht_id": nachricht.id if nachricht else None,
        "beleg_id": beleg.id if beleg else None,
        "art": beleg.art if beleg else None,
        "stufe": beleg.stufe if beleg else None,
        "lieferant": beleg.lieferant if beleg else None,
        "brutto": beleg.brutto if beleg else None,
        "probleme": probleme,
    }


def nimm_an(k: Kontext, kopf: dict, datei: tuple[str, bytes] | None) -> dict:
    if kopf["absender"] and ist_gesperrt(k, adresse(kopf["absender"])):
        nachricht = nachricht_fuer(k, kopf, "gesperrt")
        nachricht.status = "gesperrt"
        beim_mandanten(k.db, k.mandant, k.name, "absender_gesperrt", absender=nachricht.absender, betreff=nachricht.betreff)
        k.db.commit()
        return antwort(nachricht, "gesperrt", "Absender steht auf der Sperrliste")
    nachricht = nachricht_fuer(k, kopf, "empfangen")
    if not datei:
        if nachricht and nachricht.status == "empfangen":
            nachricht.status = "ohne_beleg"
        k.db.commit()
        return antwort(nachricht, "ohne_beleg", "Nachricht hat keinen Anhang")
    k.db.commit()
    try:
        beleg = belege.nimm_auf(k, *datei, quelle="e-mail" if nachricht else "schnittstelle", nachricht=nachricht)
    except (Konflikt, Ungueltig) as fehler:
        k.db.rollback()
        if nachricht:
            nachricht.status = "warnung"
            k.db.commit()
        return antwort(nachricht, "warnung", str(fehler))
    return antwort(nachricht, "erfasst", "", beleg)
