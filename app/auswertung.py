from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import einstellungen
from .db import Beleg


def monate(heute: date, anzahl: int = 6) -> list[str]:
    ergebnis = []
    jahr, monat = heute.year, heute.month
    for _ in range(anzahl):
        ergebnis.append(f"{jahr}-{monat:02d}")
        jahr, monat = (jahr - 1, 12) if monat == 1 else (jahr, monat - 1)
    return ergebnis[::-1]


def uebersicht(db: Session) -> dict:
    je_status, je_monat, fehler = Counter(), Counter(), Counter()
    automatisch = gesamt = 0
    offen_betrag = Decimal(0)
    for beleg in db.scalars(select(Beleg)):
        gesamt += 1
        automatisch += beleg.automatisch
        je_status[beleg.status] += 1
        je_monat[beleg.erstellt_am.strftime("%Y-%m")] += 1
        if beleg.status in ("pruefen", "bereit"):
            offen_betrag += beleg.brutto or Decimal(0)
            fehler.update(hinweis["text"] for hinweis in beleg.hinweise if hinweis["stufe"] == "fehler")
    return {
        "gesamt": gesamt,
        "automatisch": automatisch,
        "quote": round(automatisch * 100 / gesamt) if gesamt else None,
        "je_status": dict(je_status),
        "offen_betrag": offen_betrag,
        "monate": [{"monat": monat, "anzahl": je_monat[monat]} for monat in monate(datetime.now(UTC).date())],
        "fehler": [{"text": text, "anzahl": anzahl} for text, anzahl in fehler.most_common(6)],
        "extraktor": einstellungen().extraktor,
    }


def lieferanten(db: Session) -> list[dict]:
    gruppen: dict[str, dict] = {}
    for beleg in db.scalars(select(Beleg).where(Beleg.status != "abgelehnt").order_by(Beleg.id)):
        schluessel = beleg.lieferant_uid or beleg.lieferant
        if not schluessel:
            continue
        gruppe = gruppen.setdefault(schluessel, {"belege": 0, "brutto": Decimal(0), "automatisch": 0})
        gruppe["belege"] += 1
        gruppe["brutto"] += beleg.brutto or Decimal(0)
        gruppe["automatisch"] += beleg.automatisch
        gruppe |= {"lieferant": beleg.lieferant, "lieferant_uid": beleg.lieferant_uid}
    return sorted(gruppen.values(), key=lambda gruppe: -gruppe["belege"])
