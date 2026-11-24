import sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas


def euro(wert: float) -> str:
    return f"{wert:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def beleg(pfad: Path, lieferant, uid, iban, nummer, positionen, tage=10, summe_falsch=0.0):
    c = Canvas(str(pfad), pagesize=A4, invariant=1)
    heute = date.today()
    ausgestellt = heute - timedelta(days=tage)
    y = 790

    def zeile(text, groesse=10, abstand=16):
        nonlocal y
        c.setFont("Helvetica", groesse)
        c.drawString(60, y, text)
        y -= abstand

    zeile(lieferant, 16, 24)
    zeile("Musterstraße 1, 1010 Wien")
    if uid:
        zeile(f"UID: {uid}")
    zeile("Rechnung an: Musterverwaltung GmbH", abstand=30)
    zeile("RECHNUNG", 14, 24)
    zeile(f"Rechnungsnummer: {nummer}")
    zeile(f"Rechnungsdatum: {ausgestellt:%d.%m.%Y}")
    zeile(f"Zahlbar bis: {ausgestellt + timedelta(days=30):%d.%m.%Y}", abstand=30)
    netto_gesamt = ust_gesamt = 0.0
    for text, netto, satz in positionen:
        ust = round(netto * satz / 100, 2)
        netto_gesamt += netto
        ust_gesamt += ust
        zeile(text)
        zeile(f"{satz} % USt von {euro(netto)} EUR: {euro(ust)} EUR", abstand=22)
    zeile(f"Summe netto: EUR {euro(netto_gesamt)}")
    zeile(f"Summe USt: EUR {euro(ust_gesamt)}")
    zeile(f"Gesamtbetrag: EUR {euro(netto_gesamt + ust_gesamt + summe_falsch)}", 12, 30)
    zeile(f"IBAN: {iban}")
    c.save()


def erzeuge(ordner: Path):
    ordner.mkdir(parents=True, exist_ok=True)
    papier = ("Papier Muster GmbH", "ATU12345675", "AT61 1904 3002 3457 3201")
    reinigung = ("Reinigung Beispiel KG", "ATU87654321", "AT48 3200 0000 1234 5864")
    beleg(ordner / "01_in_ordnung.pdf", *papier, "PM-2026-001", [("Kopierpapier", 480.0, 20)])
    beleg(
        ordner / "02_zwei_steuersaetze.pdf", *papier, "PM-2026-002", [("Büromaterial", 300.0, 20), ("Fachbuch", 250.0, 10)]
    )
    beleg(ordner / "03_summe_falsch.pdf", *papier, "PM-2026-003", [("Toner", 600.0, 20)], summe_falsch=100.0)
    beleg(ordner / "04_uid_falsch.pdf", *reinigung, "RB-77", [("Reinigung Büro", 900.0, 20)])
    beleg(ordner / "05_neue_iban.pdf", *papier[:2], "AT48 3200 0000 1234 5864", "PM-2026-004", [("Ordner", 450.0, 20)])
    beleg(ordner / "06_nummer_doppelt.pdf", *papier, "PM-2026-001", [("Kopierpapier", 480.0, 20)], tage=9)


if __name__ == "__main__":
    ziel = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "belege")
    erzeuge(ziel)
    print(f"Demo-Belege liegen in {ziel}")
