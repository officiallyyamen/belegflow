import io
from datetime import date
from decimal import Decimal
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..modelle import Anforderung, Benutzer, Erstattung
from ..sicherheit import Kontext
from . import erstattung, freigabe

AKZENT = colors.HexColor("#0a6e5c")
LINIE = colors.HexColor("#d9e2de")
NORMAL = ParagraphStyle("normal", fontName="Helvetica", fontSize=9.5, leading=13)
TITEL = ParagraphStyle("titel", fontName="Helvetica-Bold", fontSize=17, leading=22, spaceAfter=8, textColor=AKZENT)
ABSCHNITT = ParagraphStyle("abschnitt", fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)


def euro(wert) -> str:
    text = f"{Decimal(wert):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{text} EUR"


def zelle(wert) -> Paragraph:
    if isinstance(wert, date):
        wert = wert.strftime("%d.%m.%Y")
    return Paragraph(escape("" if wert is None else str(wert)), NORMAL)


def tabelle(zeilen: list[list], breiten: list[float], kopf: bool = True) -> Table:
    stil = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINIE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]
    if kopf:
        stil.append(("LINEBELOW", (0, 0), (-1, 0), 0.9, AKZENT))
    return Table([[zelle(w) for w in z] for z in zeilen], colWidths=[b * mm for b in breiten], style=TableStyle(stil))


def baue(titel: str, mandant: str, teile: list) -> bytes:
    puffer = io.BytesIO()
    blatt = SimpleDocTemplate(
        puffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=titel
    )
    blatt.build([Paragraph(escape(mandant), NORMAL), Paragraph(escape(titel), TITEL), *teile])
    return puffer.getvalue()


def schritte(k: Kontext, art: str, nummer: int) -> list:
    reihe = freigabe.als_liste(k.db, art, nummer)
    if not reihe:
        return []
    zeilen = [["Schritt", "Zuständig", "Ergebnis", "Wer", "Wann"]]
    for s in reihe:
        wer = f"{s['von']} für {s['in_vertretung']}" if s["in_vertretung"] else s["von"]
        zeilen.append([s["reihenfolge"], s["ziel"], s["status"], wer, (s["am"] or "")[:16].replace("T", " ")])
    return [Paragraph("Freigabe", ABSCHNITT), tabelle(zeilen, [16, 48, 34, 40, 32])]


def anforderung(k: Kontext, eintrag: Anforderung) -> bytes:
    angaben = [
        ["Nummer", eintrag.nummer or "noch nicht freigegeben"],
        ["Lieferant", eintrag.lieferant],
        ["Angefordert von", k.db.get(Benutzer, eintrag.benutzer_id).name],
        ["Angelegt am", eintrag.erstellt_am.date()],
        ["Leistung bis", eintrag.leistung_am],
        ["Kostenstelle", eintrag.kostenstelle],
        ["Beschreibung", eintrag.beschreibung],
        ["Summe netto", euro(eintrag.netto)],
    ]
    teile = [tabelle(angaben, [40, 130], kopf=False)]
    if eintrag.positionen:
        zeilen = [["Nr.", "Bezeichnung", "Menge", "Einzelpreis", "Summe"]]
        for p in eintrag.positionen:
            menge, preis = Decimal(p["menge"]), Decimal(p["einzelpreis"])
            zeilen.append([p["nummer"], p["text"], p["menge"].replace(".", ","), euro(preis), euro(menge * preis)])
        teile += [Paragraph("Positionen", ABSCHNITT), tabelle(zeilen, [24, 66, 20, 30, 30])]
    teile += schritte(k, "anforderung", eintrag.id)
    return baue(f"Bestellanforderung {eintrag.titel}", k.mandant.name, teile)


def spesen(k: Kontext, antrag: Erstattung) -> bytes:
    eintraege = erstattung.posten(k.db, antrag.id)
    angaben = [
        ["Person", erstattung.name(k.db, antrag)],
        ["IBAN", antrag.iban],
        ["Status", antrag.status],
        ["Hinweis", antrag.hinweis],
        ["Summe", euro(erstattung.summe(antrag))],
    ]
    zeilen = [["Datum", "Art", "Bezeichnung", "Betrag", "Hinweis"]]
    for p in eintraege:
        hinweis = "ausgeschlossen" if p.ausgeschlossen else p.daten.get("grund", "")
        zeilen.append([p.datum, p.art, p.titel, euro(p.betrag), hinweis])
    teile = [
        tabelle(angaben, [40, 130], kopf=False),
        Paragraph("Posten", ABSCHNITT),
        tabelle(zeilen, [24, 24, 56, 30, 36]),
    ]
    for p in eintraege:
        if p.art == "taggeld" and p.rechnung:
            tage = [["Tag", "Zwölftel", "Land", "Mahlzeiten", "Betrag"]]
            for z in p.rechnung:
                tage.append([z["tag"], z.get("zwoelftel"), z.get("land"), z.get("mahlzeiten"), euro(z["betrag"])])
            teile += [Paragraph(escape(p.titel), ABSCHNITT), tabelle(tage, [30, 24, 60, 26, 30])]
    teile += [Spacer(1, 4 * mm), *schritte(k, "erstattung", antrag.id)]
    return baue(f"Erstattung {antrag.titel}", k.mandant.name, teile)
