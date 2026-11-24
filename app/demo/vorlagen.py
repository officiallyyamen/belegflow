import re
from math import cos, pi, sin

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

BREITE, HOEHE = A4
TEXT = HexColor("#1b1b1b")
GRAU = HexColor("#8a8a8a")
STRICH = HexColor("#b9b9b9")
NORMAL, FETT, KURSIV, KURSIVFETT = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"
NAMEN = {
    "RECHNUNG": "Rechnungsnummer",
    "GUTSCHRIFT": "Gutschriftsnummer",
    "ANGEBOT": "Angebotsnummer",
    "AUFTRAGSBESTÄTIGUNG": "Auftragsnummer",
    "LIEFERSCHEIN": "Lieferscheinnummer",
    "VERTRAG": "Vertragsnummer",
}
ANREDE = {
    "RECHNUNG": "wir erlauben uns, wie folgt in Rechnung zu stellen:",
    "GUTSCHRIFT": "wir schreiben Ihnen folgende Positionen gut:",
    "ANGEBOT": "gerne bieten wir Ihnen folgende Leistungen an:",
    "AUFTRAGSBESTÄTIGUNG": "wir bedanken uns für Ihren Auftrag und bestätigen folgende Leistungen:",
    "LIEFERSCHEIN": "wir liefern Ihnen folgende Positionen:",
}


def euro(wert) -> str:
    return f"{wert:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def zahl(wert) -> str:
    return format(wert.normalize(), "f").replace(".", ",")


class Blatt:
    def __init__(self, c: Canvas, v):
        self.c, self.v = c, v
        self.zeichen = "€" if v.waehrung == "EUR" else v.waehrung

    def geld(self, wert) -> str:
        return f"{euro(wert)} {self.zeichen}"

    def text(self, x, y, inhalt, schrift=NORMAL, groesse=9.5, farbe=TEXT):
        self.c.setFont(schrift, groesse)
        self.c.setFillColor(farbe)
        self.c.drawString(x, y, str(inhalt))

    def rechts(self, x, y, inhalt, schrift=NORMAL, groesse=9.5, farbe=TEXT):
        self.c.setFont(schrift, groesse)
        self.c.setFillColor(farbe)
        self.c.drawRightString(x, y, str(inhalt))

    def mitte(self, x, y, inhalt, schrift=NORMAL, groesse=9.5, farbe=TEXT):
        self.c.setFont(schrift, groesse)
        self.c.setFillColor(farbe)
        self.c.drawCentredString(x, y, str(inhalt))

    def linie(self, x1, y, x2, farbe=TEXT, staerke=0.6):
        self.c.setStrokeColor(farbe)
        self.c.setLineWidth(staerke)
        self.c.line(x1, y, x2, y)

    def kasten(self, x, y, b, h, fuellung=None, rand=None, staerke=0.6, radius=0):
        if fuellung:
            self.c.setFillColor(fuellung)
        if rand:
            self.c.setStrokeColor(rand)
            self.c.setLineWidth(staerke)
        if radius:
            self.c.roundRect(x, y, b, h, radius, stroke=int(bool(rand)), fill=int(bool(fuellung)))
        else:
            self.c.rect(x, y, b, h, stroke=int(bool(rand)), fill=int(bool(fuellung)))

    def absatz(self, x, y, inhalt, breite=491, schrift=NORMAL, groesse=9.5, abstand=14):
        for zeile in simpleSplit(inhalt, schrift, groesse, breite):
            self.text(x, y, zeile, schrift, groesse)
            y -= abstand
        return y

    def fuss(self, y, farbe=GRAU, spalten=(52, 220, 400), schrift=NORMAL, trenner=False):
        f = self.v.lieferant
        if trenner:
            self.linie(52, y + 18, 543, TEXT, 1)
            self.linie(52, y + 16, 543, TEXT, 0.4)
        eins = [f.name, f.strasse, f"{f.plz} {f.ort}"]
        if f.uid:
            eins.append(f"UID: {f.uid}")
        bank = ["Beispielbank", f"IBAN: {f.iban}"] if f.iban and not self.v.ohne_summen else ["Zahlung laut Beleg"]
        kurz = re.sub(r"[^a-z]", "", f.name.lower().translate(str.maketrans("äöü", "aou")))[:22]
        netz = [f"office@{kurz}.example", f"www.{kurz}.example"]
        for x, zeilen in zip(spalten, (eins, bank, netz), strict=True):
            for i, zeile in enumerate(zeilen):
                self.text(x, y - i * 11, zeile, schrift, 7.5, farbe)

    def absender(self, x, y, farbe=GRAU, schrift=NORMAL, groesse=7.5, strich=False):
        f = self.v.lieferant
        zeile = f"{f.name} - {f.strasse} - {f.plz} {f.ort}"
        self.text(x, y, zeile, schrift, groesse, farbe)
        if strich:
            self.linie(x, y - 1.5, x + self.c.stringWidth(zeile, schrift, groesse), farbe, 0.4)

    def anschrift(self, x, y, schrift=NORMAL, groesse=9.5, abstand=13.5):
        e = self.v.empfaenger
        for zeile in (e.name, e.strasse, f"{e.plz} {e.ort}"):
            self.text(x, y, zeile, schrift, groesse)
            y -= abstand
        if self.v.mit_uid and e.uid:
            self.text(x, y, f"Ihre UID: {e.uid}", schrift, groesse)

    def angaben(self):
        v = self.v
        rechnung = v.titel == "RECHNUNG"
        zeilen = [
            (NAMEN.get(v.titel, "Belegnummer"), v.nummer),
            ("Rechnungsdatum" if rechnung else "Datum", f"{v.datum:%d.%m.%Y}"),
        ]
        if v.leistung:
            von, bis = v.leistung
            zeilen.append(
                ("Leistungsdatum", f"{von:%d.%m.%Y}")
                if von == bis
                else ("Leistungszeitraum", f"{von:%d.%m.%Y} bis {bis:%d.%m.%Y}")
            )
        if v.faellig and rechnung:
            zeilen.append(("Zahlbar bis", f"{v.faellig:%d.%m.%Y}"))
        if v.bestellnummer:
            zeilen.append(("Bestellnummer", v.bestellnummer))
        return zeilen

    def titel(self):
        return self.v.titel.capitalize()

    def bedingungen(self, x, y, schrift=NORMAL):
        v = self.v
        if v.titel == "RECHNUNG" and v.faellig:
            self.text(x, y, f"Zahlungsbedingungen: Zahlung innerhalb von {v.ziel} Tagen ohne Abzüge", schrift)
            y -= 14
        if v.skonto:
            prozent, tage = v.skonto
            self.text(x, y, f"{prozent} % Skonto bei Zahlung innerhalb von {tage} Tagen", schrift)
            y -= 14
        return y

    def steuertext(self, satz, netto):
        return f"{satz} % USt von {self.geld(netto)}"


def zeichen_wolke(c: Canvas, x, y, farbe):
    c.setFillColor(farbe)
    for dx, dy, r in ((-16, -2, 12), (0, 8, 16), (16, 0, 12)):
        c.circle(x + dx, y + dy, r, stroke=0, fill=1)
    c.roundRect(x - 28, y - 14, 56, 18, 9, stroke=0, fill=1)
    c.setStrokeColor(farbe)
    c.setLineWidth(1.6)
    for i in range(4):
        weg = -15 + i * 10
        c.line(x + weg, y - 14, x + weg, y - 26)
        c.circle(x + weg, y - 28, 2, stroke=0, fill=1)


def zeichen_papier(c: Canvas, x, y, farbe):
    for i, ton in enumerate(("#f2d9d5", "#e7b4ad", None)):
        c.setFillColor(HexColor(ton) if ton else farbe)
        c.saveState()
        c.translate(x, y)
        c.rotate(14 - i * 12)
        c.roundRect(-19, -24, 38, 48, 3, stroke=0, fill=1)
        c.restoreState()
    c.setFillColor(white)
    c.circle(x - 6, y + 4, 2.2, stroke=0, fill=1)
    c.circle(x + 7, y + 2, 2.2, stroke=0, fill=1)
    c.setStrokeColor(white)
    c.setLineWidth(1.6)
    c.arc(x - 6, y - 12, x + 7, y, 190, 150)


def zeichen_blume(c: Canvas, x, y, farbe):
    c.setFillColor(farbe)
    for i in range(6):
        c.circle(x + 13 * sin(i * pi / 3), y + 13 * cos(i * pi / 3), 9, stroke=0, fill=1)
    c.setFillColor(HexColor("#e9c65b"))
    c.circle(x, y, 8, stroke=0, fill=1)


def zeichen_besen(c: Canvas, x, y, farbe):
    c.setFillColor(HexColor("#efe3cf"))
    c.circle(x, y, 44, stroke=0, fill=1)
    c.setStrokeColor(farbe)
    c.setLineWidth(2)
    c.line(x - 18, y + 30, x + 4, y - 4)
    c.setFillColor(farbe)
    weg = c.beginPath()
    weg.moveTo(x - 1, y - 1)
    weg.lineTo(x + 9, y - 7)
    weg.lineTo(x + 24, y - 24)
    weg.lineTo(x - 4, y - 28)
    weg.close()
    c.drawPath(weg, stroke=0, fill=1)
    c.setStrokeColor(HexColor("#efe3cf"))
    c.setLineWidth(1)
    for i in range(4):
        c.line(x + 4, y - 6, x + i * 6, y - 26)
    c.setStrokeColor(farbe)
    c.setLineWidth(1.4)
    for dx, dy, r in ((-22, -8, 5), (-12, -22, 3.5), (20, 12, 4)):
        c.circle(x + dx, y + dy, r, stroke=1, fill=0)


def zeichen_werk(c: Canvas, x, y, farbe, kurz):
    c.setFillColor(farbe)
    c.roundRect(x + 40, y - 20, 40, 40, 4, stroke=0, fill=1)
    c.setFillColor(white)
    for seite in (1, -1):
        weg = c.beginPath()
        weg.moveTo(x + 50, y + seite * 4)
        weg.lineTo(x + 70, y + seite * 4)
        weg.lineTo(x + 60, y + seite * 14)
        weg.close()
        c.drawPath(weg, stroke=0, fill=1)
    c.setFillColor(HexColor("#2c2c2c"))
    c.setFont(FETT, 26)
    c.drawRightString(x + 34, y - 9, kurz)


def zeichen_farbe(c: Canvas, x, y, farbe):
    c.setFillColor(farbe)
    c.roundRect(x - 30, y + 8, 60, 9, 3, stroke=0, fill=1)
    for weg in (-24, 17):
        c.rect(x + weg, y - 24, 7, 32, stroke=0, fill=1)
    c.setFillColor(HexColor("#2c2c2c"))
    c.roundRect(x - 2, y - 8, 17, 13, 2, stroke=0, fill=1)
    c.circle(x - 14, y + 22, 5, stroke=0, fill=1)


def zeichen_stern(c: Canvas, x, y, farbe, radius=20):
    c.setFillColor(farbe)
    weg = c.beginPath()
    for i in range(16):
        r = radius if i % 2 == 0 else radius * 0.55
        punkt = (x + r * sin(i * pi / 8), y + r * cos(i * pi / 8))
        weg.lineTo(*punkt) if i else weg.moveTo(*punkt)
    weg.close()
    c.drawPath(weg, stroke=0, fill=1)


def technik(b: Blatt, farbe):
    v, c = b.v, b.c
    serif, serifett = "Times-Roman", "Times-Bold"
    b.fuss(62, spalten=(52, 205, 415))
    c.setFillColor(farbe)
    zeichen_wolke(c, BREITE / 2 - 24, 752, farbe)
    for i, wort in enumerate(v.lieferant.name.split()[:3]):
        b.text(BREITE / 2 + 14, 762 - i * 11, wort, FETT, 9)
    b.absender(52, 692, TEXT, serif, 8, strich=True)
    b.anschrift(52, 664, serif, 10.5, 14)
    b.text(52, 566, f"{b.titel()} Nr. {v.nummer}", serifett, 11.5)
    y = 692
    for name, wert in b.angaben():
        b.text(335, y, name, serif, 10.5)
        b.rechts(543, y, wert, serif, 10.5)
        y -= 14
    b.text(52, 540, "Guten Tag,", serif, 10.5)
    b.text(52, 513, ANREDE.get(v.titel, ""), serif, 10.5)
    b.kasten(49, 460, 496, 15, HexColor("#cfcfcf"), TEXT)
    c.setStrokeColor(TEXT)
    for x in (86, 152, 330, 400, 472):
        c.line(x, 460, x, 475)
    for x, name in ((52, "Pos."), (89, "Art.-Nr."), (155, "Bezeichnung")):
        b.text(x, 464, name, serifett, 10.5)
    for x, name in ((397, "Menge"), (469, "Einzelpreis"), (543, "Gesamtpreis")):
        b.rechts(x, 464, name, serif, 10.5)
    y = 438
    for i, p in enumerate(v.posten, 1):
        b.rechts(83, y, i, serif, 10.5)
        b.text(89, y, p.nummer, serif, 10.5)
        b.text(155, y, p.text, serif, 10.5)
        b.rechts(397, y, f"{zahl(p.menge)} {p.einheit}", serif, 10.5)
        b.rechts(469, y, b.geld(p.preis), serif, 10.5)
        b.rechts(543, y, b.geld(p.netto), serif, 10.5)
        y -= 15
    if not v.ohne_summen:
        y -= 26
        b.text(122, y, "Summe netto", serif, 10.5)
        b.rechts(543, y, b.geld(v.netto), serif, 10.5)
        for satz, netto, ust in v.steuern:
            y -= 22
            b.text(122, y, b.steuertext(satz, netto), serif, 10.5)
            b.rechts(543, y, b.geld(ust), serif, 10.5)
        if len(v.steuern) > 1:
            y -= 22
            b.text(122, y, "Summe USt", serif, 10.5)
            b.rechts(543, y, b.geld(v.ust), serif, 10.5)
        y -= 30
        b.kasten(119, y - 6, 426, 19, HexColor("#cfcfcf"), TEXT, 0.9)
        b.text(122, y, "Rechnungsbetrag" if v.titel == "RECHNUNG" else "Gesamtbetrag", FETT, 12)
        b.rechts(542, y, b.geld(v.brutto), FETT, 12)
    y = b.bedingungen(52, y - 44, serif)
    b.text(52, y - 14, "Mit freundlichen Grüßen", serif, 10.5)
    b.text(52, y - 42, v.lieferant.name, serif, 10.5)


def linien(b: Blatt, farbe):
    v, c = b.v, b.c
    b.fuss(62, TEXT, (92, 238, 420), trenner=True)
    zeichen = zeichen_blume if "Blumen" in v.lieferant.name else zeichen_papier
    zeichen(c, 484, 766, farbe)
    b.mitte(484, 722, v.lieferant.name.split()[0].lower(), FETT, 17, farbe)
    b.mitte(484, 708, " ".join(v.lieferant.name.split()[1:]), NORMAL, 8, farbe)
    b.absender(52, 670, farbe, FETT, 7.5)
    b.anschrift(52, 656)
    b.text(52, 520, f"{v.titel}   {v.nummer}", FETT, 12, farbe)
    y = 656
    for name, wert in b.angaben():
        b.rechts(466, y, f"{name}:", FETT, 9.5)
        b.rechts(543, y, wert)
        y -= 14
    b.text(
        52,
        464,
        "Wir berechnen wie folgt:" if v.titel == "RECHNUNG" else ANREDE.get(v.titel, ""),
    )
    kanten = (49, 84, 150, 318, 392, 468, 545)
    namen = ("Pos.", "Art.-Nr.", "Beschreibung", "Menge", "Einzelpreis", "Gesamtpreis")
    y = 418
    b.kasten(49, y, 496, 14, farbe, TEXT)
    c.setStrokeColor(TEXT)
    for x in kanten[1:-1]:
        c.line(x, y, x, y + 14)
    for i, name in enumerate(namen):
        if i in (1, 2):
            b.text(kanten[i] + 3, y + 3.5, name, FETT, 9.5, white)
        else:
            b.rechts(kanten[i + 1] - 3, y + 3.5, name, FETT, 9.5, white)
    for nr, p in enumerate(v.posten, 1):
        y -= 14
        c.setStrokeColor(TEXT)
        c.setLineWidth(0.6)
        c.rect(49, y, 496, 14, stroke=1, fill=0)
        for x in kanten[1:-1]:
            c.line(x, y, x, y + 14)
        b.rechts(81, y + 3.5, f"{nr}.")
        b.text(87, y + 3.5, p.nummer)
        b.text(153, y + 3.5, p.text)
        b.rechts(389, y + 3.5, f"{zahl(p.menge)} {p.einheit}")
        b.rechts(465, y + 3.5, b.geld(p.preis))
        b.rechts(542, y + 3.5, b.geld(p.netto))
    if not v.ohne_summen:
        summen = [("Summe netto", v.netto)] + [(b.steuertext(s, n), u) for s, n, u in v.steuern]
        if len(v.steuern) > 1:
            summen.append(("Summe USt", v.ust))
        for name, wert in summen:
            y -= 14
            b.kasten(318, y, 227, 14, None, TEXT)
            c.line(468, y, 468, y + 14)
            b.rechts(465, y + 3.5, name, groesse=9)
            b.rechts(542, y + 3.5, b.geld(wert))
        y -= 14
        b.kasten(318, y, 227, 14, farbe, TEXT)
        b.rechts(465, y + 3.5, "Gesamtsumme", FETT, 9.5, white)
        b.rechts(542, y + 3.5, b.geld(v.brutto), FETT, 9.5, white)
    y = b.bedingungen(52, y - 32)
    b.text(52, y - 12, "Mit freundlichen Grüßen")
    b.text(52, y - 52, v.lieferant.name)


def gruppen(b: Blatt, farbe, band="#efe3cf", logo=zeichen_besen, mittig=False):
    v, c = b.v, b.c
    b.fuss(62)
    if mittig:
        logo(c, 232, 764, farbe)
        b.text(276, 757, v.lieferant.name.upper(), FETT, 15)
    else:
        b.text(52, 766, v.lieferant.name, FETT, 14)
        logo(c, 452, 762, farbe)
    b.absender(52, 700)
    b.anschrift(52, 684, FETT if mittig else NORMAL, 9, 14)
    b.text(52, 538, b.titel(), FETT, 13)
    b.text(362, 672, "Kontakt", FETT, 9.5)
    b.text(362, 658, v.lieferant.strasse, farbe=GRAU)
    b.text(362, 644, f"{v.lieferant.plz} {v.lieferant.ort}", farbe=GRAU)
    y = 612
    for name, wert in b.angaben():
        b.text(362, y, f"{name}:", groesse=9)
        b.text(462, y, wert, groesse=9)
        y -= 14
    b.text(52, 508, "Sehr geehrte Damen und Herren,", groesse=9)
    b.text(52, 494, ANREDE.get(v.titel, ""), groesse=9)
    b.kasten(49, 456, 496, 17, HexColor(band))
    for x, name in ((52, "Pos."), (84, "Art.-Nr."), (190, "Bezeichnung")):
        b.text(x, 461, name, groesse=9)
    for x, name in ((178, "Anzahl"), (466, "Einzelpreis"), (542, "Gesamtpreis")):
        b.rechts(x, 461, name, groesse=9)
    stunden = [p for p in v.posten if p.einheit.startswith(("Std", "Monat"))]
    artikel = [p for p in v.posten if p not in stunden]
    nr = 0
    y = 444
    for name, liste in (("Dienstleistungen", stunden), ("Artikel", artikel)):
        if not liste:
            continue
        b.text(52, y, name, FETT, 9)
        b.linie(49, y - 5, 545, TEXT, 0.9)
        for p in liste:
            nr += 1
            y -= 16
            b.rechts(72, y, nr, groesse=9)
            b.text(84, y, p.nummer, groesse=9)
            b.rechts(178, y, f"{zahl(p.menge)} {p.einheit}", groesse=9)
            b.text(190, y, p.text, groesse=9)
            b.rechts(466, y, b.geld(p.preis), groesse=9)
            b.rechts(542, y, b.geld(p.netto), groesse=9)
            b.linie(49, y - 5, 545, STRICH)
        y -= 16
        b.rechts(466, y, name, KURSIV, 9)
        b.rechts(542, y, b.geld(sum(p.netto for p in liste)), KURSIV, 9)
        b.linie(49, y - 5, 545, TEXT, 0.9)
        y -= 18
    if not v.ohne_summen:
        b.rechts(466, y, "Summe netto", KURSIVFETT, 9)
        b.rechts(542, y, b.geld(v.netto), KURSIVFETT, 9)
        y -= 26
        for satz, netto, ust in v.steuern:
            b.rechts(466, y, b.steuertext(satz, netto), groesse=9)
            b.rechts(542, y, b.geld(ust), groesse=9)
            y -= 14
        if len(v.steuern) > 1:
            b.rechts(466, y, "Summe USt", groesse=9)
            b.rechts(542, y, b.geld(v.ust), groesse=9)
            y -= 14
        b.kasten(49, y - 5, 496, 17, HexColor("#d4d4d4"))
        b.rechts(466, y, "Gesamtbetrag", FETT, 9.5)
        b.rechts(542, y, b.geld(v.brutto), FETT, 9.5)
    y = b.bedingungen(52, y - 40)
    b.text(52, y - 6, "Bei Fragen erreichen Sie uns werktags unter der angegebenen Adresse oder per E-Mail", groesse=9)


def buero(b: Blatt, farbe):
    gruppen(b, farbe, "#55c3a0", zeichen_farbe, True)


def industrie(b: Blatt, farbe):
    v, c, e, f = b.v, b.c, b.v.empfaenger, b.v.lieferant
    y = 790
    b.text(52, y, f.name, FETT, 10)
    for zeile in (f"{f.strasse}", f"{f.plz} {f.ort}"):
        y -= 13
        b.text(52, y, zeile, groesse=9.5)
    if f.uid:
        y -= 13
        b.text(52, y, f"UID: {f.uid}", groesse=9.5)
    kurz = "".join(w[0] for w in f.name.split()[:2]).upper()
    zeichen_werk(c, 436, 776, farbe, kurz)
    b.rechts(543, 728, f.name.split()[0].upper() + " " + f.name.split()[1].upper(), FETT, 9)
    for x, name in ((80, "Kunde" if v.titel != "RECHNUNG" else "Rechnungsanschrift"), (356, "Lieferanschrift")):
        b.text(x, 694, name, FETT, 10)
        c.setStrokeColor(TEXT)
        c.setLineWidth(0.9)
        c.line(x - 6, 620, x - 6, 686)
    b.text(80, 674, f"Kunde: {e.name}")
    b.text(80, 654, e.strasse)
    b.text(80, 634, f"{e.plz} {e.ort}")
    b.text(356, 674, e.name)
    b.text(356, 654, e.strasse)
    b.text(356, 634, f"{e.plz} {e.ort}")
    if v.mit_uid and e.uid:
        b.text(80, 606, f"Ihre UID: {e.uid}")
    b.text(56, 560, v.titel, FETT, 17 if len(v.titel) < 12 else 11)
    Code128(v.nummer, barWidth=0.85, barHeight=20, quiet=False).drawOn(c, 440, 582)
    y = 560
    for name, wert in b.angaben():
        b.text(206, y, f"{name}:", FETT, 8.5)
        b.text(292, y, wert, groesse=8.5)
        y -= 13
    if f.iban and not v.ohne_summen:
        b.text(392, 560, "Bank:", FETT, 8.5)
        b.text(424, 560, "Beispielbank", groesse=8.5)
        b.text(392, 547, "IBAN:", FETT, 8.5)
        b.text(424, 547, f.iban, groesse=8.5)
    b.linie(52, 486, 545, TEXT, 1)
    for x, name in ((52, "Artikel"), (120, "Beschreibung")):
        b.text(x, 473, name, FETT, 8.5)
    for x, name in ((350, "Anzahl"), (446, "Per Stück"), (543, "Summe")):
        b.rechts(x, 473, name, FETT, 8.5)
    b.linie(52, 464, 545, TEXT, 1)
    y = 444
    for p in v.posten:
        b.text(52, y, p.nummer, groesse=8.5)
        b.text(120, y, p.text, groesse=8.5)
        b.rechts(350, y, f"{zahl(p.menge)} {p.einheit}", groesse=8.5)
        b.rechts(446, y, b.geld(p.preis), groesse=8.5)
        b.rechts(543, y, b.geld(p.netto), groesse=8.5)
        y -= 17
    y = 250
    b.linie(52, y, 545, TEXT, 1)
    if not v.ohne_summen:
        zeilen = [("Summe netto:", v.netto)] + [(f"{b.steuertext(s, n)}:", u) for s, n, u in v.steuern]
        if len(v.steuern) > 1:
            zeilen.append(("Summe USt:", v.ust))
        for name, wert in zeilen:
            y -= 15
            b.rechts(462, y, name, FETT, 8.5)
            b.rechts(543, y, b.geld(wert), groesse=8.5)
        b.linie(474, y - 5, 545, TEXT, 0.9)
        y -= 18
        b.rechts(462, y, "Gesamtbetrag:", FETT, 8.5)
        b.rechts(543, y, b.geld(v.brutto), FETT, 8.5)
    b.bedingungen(56, 110)


def vertrag(b: Blatt, farbe):
    v, c, f, e = b.v, b.c, b.v.lieferant, b.v.empfaenger
    b.fuss(62)
    art = v.zeilen[0].split()[0].upper() if v.zeilen else "VERTRAG"
    b.kasten(52, 752, 150, 40, farbe, radius=5)
    c.setFillColor(white)
    zeichen_stern(c, 74, 772, white, 12)
    name = f.name.split()
    b.text(94, 775, name[0].upper(), FETT, 12, white)
    b.text(94, 762, " ".join(name[1:])[:24], NORMAL, 7.5, white)
    b.rechts(543, 778, art, FETT, 15)
    b.rechts(543, 758, f"Vertragsnummer: {v.nummer}", groesse=8.5, farbe=GRAU)
    b.linie(49, 744, 545, HexColor("#4aa777"), 1.6)
    hell = HexColor("#dfe6f0")
    b.kasten(49, 706, 496, 26, hell, STRICH)
    b.kasten(49, 636, 496, 70, None, STRICH)
    c.line(297, 636, 297, 732)
    for x, titel, wer in ((58, "Auftragnehmer", f), (306, "Auftraggeber", e)):
        b.text(x, 715, titel, FETT, 9)
        zeilen = [wer.name, wer.strasse, f"{wer.plz} {wer.ort}"] + ([f"USt-Nummer {wer.uid}"] if wer.uid else [])
        for i, zeile in enumerate(zeilen):
            b.text(x, 690 - i * 14, zeile, groesse=9, farbe=HexColor("#4d4d4d"))
    b.text(58, 612, f"Datum: {v.datum:%d.%m.%Y}", groesse=9)
    absaetze = [
        ("Vertragsgegenstand", v.zeilen[0] if v.zeilen else ""),
        ("Laufzeit", v.zeilen[1] if len(v.zeilen) > 1 else "Der Vertrag läuft auf unbestimmte Zeit."),
        ("Entgelt", "Das Entgelt wird monatlich im Voraus verrechnet. Die Umsatzsteuer kommt in gesetzlicher Höhe dazu."),
        ("Kündigung", "Die Kündigung muss schriftlich erfolgen und spätestens am letzten Tag der Frist einlangen."),
        ("Schlussbestimmungen", "Änderungen sind nur schriftlich gültig. Es gilt österreichisches Recht."),
    ]
    y = 576
    for nr, (titel, inhalt) in enumerate(absaetze, 1):
        b.text(52, y, f"§ {nr}   {titel}", FETT, 11, farbe)
        y = b.absatz(52, y - 18, inhalt) - 16
    for x, wer in ((52, "Auftragnehmer"), (320, "Auftraggeber")):
        b.linie(x, 150, x + 200, TEXT)
        b.text(x, 138, f"Unterschrift {wer}", groesse=8, farbe=GRAU)


def bon(b: Blatt):
    v, c, f, e = b.v, b.c, b.v.lieferant, b.v.empfaenger
    breite, hoehe = c._pagesize
    schrift, fett = "Courier", "Courier-Bold"
    m = breite / 2
    y = hoehe - 34
    b.mitte(m, y, f.name, fett, 11)
    for zeile in (f.strasse, f"{f.plz} {f.ort}", f"UID: {f.uid}" if f.uid else None):
        if zeile:
            y -= 13
            b.mitte(m, y, zeile, schrift, 8.5)

    def strich(y):
        b.mitte(m, y, "-" * 40, schrift, 8)

    y -= 18
    strich(y)
    y -= 18
    b.mitte(m, y, v.titel, fett, 12)
    y -= 18
    for zeile in [f"{n}: {w}" for n, w in b.angaben()] + [f"Rechnung an: {e.name}", e.strasse, f"{e.plz} {e.ort}"]:
        b.text(18, y, zeile, schrift, 8)
        y -= 12
    strich(y)
    y -= 16
    for p in v.posten:
        b.text(18, y, f"{p.nummer} {p.text}", schrift, 7)
        b.rechts(breite - 18, y, f"{zahl(p.menge)} {p.einheit} {euro(p.preis)} {euro(p.netto)}", schrift, 7)
        y -= 14
    strich(y)
    y -= 16
    zeilen = [(b.steuertext(s, n), u) for s, n, u in v.steuern] + [("Summe netto", v.netto), ("Summe USt", v.ust)]
    for name, wert in zeilen:
        b.text(18, y, name, schrift, 8)
        b.rechts(breite - 18, y, b.geld(wert), schrift, 8)
        y -= 13
    y -= 6
    b.text(18, y, "Gesamtbetrag", fett, 11)
    b.rechts(breite - 18, y, b.geld(v.brutto), fett, 11)
    y -= 22
    if f.iban:
        b.text(18, y, f"IBAN: {f.iban}", schrift, 8)
        y -= 16
    strich(y)
    b.mitte(m, y - 18, "Danke für Ihren Besuch", schrift, 8.5)
    Code128(v.nummer, barWidth=0.9, barHeight=22, quiet=False).drawOn(c, m - 45, y - 52)


GESTALTUNG = {
    "Papier Muster GmbH": (linien, "#c8554b"),
    "Blumen Testgarten": (linien, "#4b8a57"),
    "Reinigung Beispiel KG": (gruppen, "#4d4234"),
    "Gasthaus Musterwirt": (gruppen, "#4d4234"),
    "Kanzlei Zahlenwald Steuerberatung GmbH": (technik, "#2f5d50"),
    "Wolke Sieben Software GmbH": (technik, "#b04a52"),
    "Beispielnetz Telekom AG": (technik, "#2d6aa3"),
    "Plakat und Pixel OG": (buero, "#55c3a0"),
    "Möbel Testhaus GmbH": (buero, "#55c3a0"),
    "Lift Beispiel Technik GmbH": (industrie, "#c32f35"),
    "Bau und Dach Muster GmbH": (industrie, "#b8611b"),
    "Hotel Beispielblick GmbH": (technik, "#8a6d2f"),
    "Alpen Beispiel AG": (industrie, "#c32f35"),
}
BONS = {"Taxi Musterfahrt e.U.", "Parkhaus Beispiel GmbH", "Gasthaus Musterwirt"}


def zeichne(puffer, v) -> None:
    kassenbon = v.lieferant.name in BONS and v.titel == "RECHNUNG"
    groesse = (250, 400 + 14 * len(v.posten) + 13 * len(v.steuern)) if kassenbon else A4
    c = Canvas(puffer, pagesize=groesse, invariant=1)
    b = Blatt(c, v)
    if kassenbon:
        bon(b)
    elif v.titel == "VERTRAG":
        vertrag(b, HexColor("#1f5c3a"))
    else:
        form, farbe = GESTALTUNG.get(v.lieferant.name, (linien, "#44617b"))
        form(b, HexColor(farbe))
    b.text(18 if kassenbon else 52, 16, "Beispieldokument mit erfundenen Firmen und Beträgen", groesse=6.5, farbe=GRAU)
    c.save()
