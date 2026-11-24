import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dienste import anforderung, belege, erstattung, export, freigabe, karten, post, zahlung
from ..dienste.dateien import ablegen, pfad, seite_als_png
from ..modelle import (
    Auswertung,
    Automatik,
    Beleg,
    Benutzer,
    Mandant,
    Mitglied,
    Partner,
    Sperre,
    Stammwert,
    Team,
    Workflow,
)
from ..sicherheit import Kontext, kontext_aus, passwort_hash
from .dateien import Firma, Posten, Vorlage, cii, ebinterface, iban, pdf, ubl, uid, zugferd

HEUTE = date.today()
D = Decimal
PERSONEN = (
    ("anna", "Anna Berger"),
    ("bernd", "Bernd Koller"),
    ("clara", "Clara Huber"),
    ("david", "David Novak"),
    ("eva", "Eva Leitner"),
)
MITGLIEDER = {
    0: {
        "anna": ["admin", "buchhaltung"],
        "bernd": ["freigabe", "mitarbeit"],
        "clara": ["freigabe", "mitarbeit"],
        "david": ["mitarbeit"],
        "eva": ["einsicht", "freigabe"],
    },
    1: {"anna": ["buchhaltung"], "bernd": ["admin", "freigabe"], "clara": ["freigabe"]},
    2: {"anna": ["admin", "buchhaltung"], "eva": ["einsicht", "freigabe"]},
}
STAMM = (
    ("konto", "5010", "Wareneinkauf"),
    ("konto", "7200", "Instandhaltung"),
    ("konto", "7320", "Kfz-Aufwand"),
    ("konto", "7340", "Reisekosten"),
    ("konto", "7380", "Telefon und Internet"),
    ("konto", "7400", "Miete"),
    ("konto", "7600", "Büromaterial"),
    ("konto", "7650", "Werbung"),
    ("konto", "7690", "Bewirtung"),
    ("konto", "7750", "Beratung"),
    ("konto", "7780", "Software"),
    ("konto", "7900", "Sonstiger Aufwand"),
    ("kostenstelle", "100", "Verwaltung"),
    ("kostenstelle", "200", "Vertrieb"),
    ("kostenstelle", "300", "Technik"),
    ("kostenstelle", "400", "Hausverwaltung"),
    ("kostentraeger", "P-01", "Projekt Neubau"),
    ("kostentraeger", "P-02", "Projekt Digitalisierung"),
    ("steuerschluessel", "V20", "Vorsteuer 20 %"),
    ("steuerschluessel", "V10", "Vorsteuer 10 %"),
    ("steuerschluessel", "RC", "Reverse Charge"),
    ("vertragstyp", "Miete", "Miete"),
    ("vertragstyp", "Wartung", "Wartung"),
    ("vertragstyp", "Versicherung", "Versicherung"),
    ("vertragstyp", "Software", "Software"),
)
MUSTER = Firma("Muster Holding GmbH", "Beispielgasse 5", "1030", "Wien", uid("2222222"), iban(900))
GASTRO = Firma("Muster Gastro GmbH", "Musterplatz 12", "1070", "Wien", uid("3333333"), iban(901))
IMMO = Firma("Muster Immobilien GmbH", "Testring 8", "4020", "Linz", uid("4444444"), iban(902))
PAPIER = Firma("Papier Muster GmbH", "Lagerstraße 1", "1010", "Wien", uid("1234567"), iban(1))
REINIGUNG = Firma("Reinigung Beispiel KG", "Putzgasse 3", "1120", "Wien", uid("5555555"), iban(2))
WOLKE = Firma("Wolke Sieben Software GmbH", "Serverallee 77", "8010", "Graz", uid("6666666"), iban(3))
NETZ = Firma("Beispielnetz Telekom AG", "Antennenweg 9", "1220", "Wien", uid("7777777"), iban(4))
WERBUNG = Firma("Plakat und Pixel OG", "Farbweg 4", "5020", "Salzburg", uid("8888888"), iban(5))
BERATER = Firma("Kanzlei Zahlenwald Steuerberatung GmbH", "Bilanzgasse 2", "1090", "Wien", uid("1357913"), iban(6))
LIFT = Firma("Lift Beispiel Technik GmbH", "Schachtweg 6", "1230", "Wien", uid("2468024"), iban(7))
MOEBEL = Firma("Möbel Testhaus GmbH", "Tischlerstraße 20", "2340", "Mödling", uid("9876543"), iban(8))
BAU = Firma("Bau und Dach Muster GmbH", "Ziegelweg 11", "4400", "Steyr", uid("1122334"), iban(9))


def vor(tage: int) -> date:
    return HEUTE - timedelta(days=tage)


def posten(nummer: str, text: str, anzahl, preis, satz: int = 20, einheit: str = "Stk") -> Posten:
    return Posten(nummer, text, D(str(anzahl)), einheit, D(str(preis)), satz)


def ohne_uid(firma: Firma) -> Firma:
    return Firma(firma.name, firma.strasse, firma.plz, firma.ort, None, firma.iban)


def rechnung(wer: Firma, an: Firma, nummer: str, tage: int, *zeilen: Posten, **mehr) -> Vorlage:
    tag = vor(tage)
    return Vorlage(wer, an, nummer, tag, list(zeilen), leistung=mehr.pop("leistung", (tag, tag)), **mehr)


class Demo:
    def __init__(self, db: Session, passwort: str | None):
        self.db = db
        self.passwoerter = {}
        self.personen: dict[str, Benutzer] = {}
        for kurz, name in PERSONEN:
            wort = passwort or secrets.token_urlsafe(12)
            self.passwoerter[f"{kurz}@belegflow.example"] = wort
            person = Benutzer(
                name=name, email=f"{kurz}@belegflow.example", passwort=passwort_hash(wort), iban=iban(500 + len(kurz))
            )
            db.add(person)
            self.personen[kurz] = person
        db.flush()
        self.mandanten = [self.mandant(i, firma) for i, firma in enumerate((MUSTER, GASTRO, IMMO))]
        db.commit()

    def mandant(self, stelle: int, firma: Firma) -> Mandant:
        db = self.db
        neu = Mandant(
            name=firma.name,
            strasse=firma.strasse,
            plz=firma.plz,
            ort=firma.ort,
            uid=firma.uid,
            iban=firma.iban,
            einstellungen={"vier_augen": True, "demo": True},
        )
        db.add(neu)
        db.flush()
        for kurz, rollen in MITGLIEDER[stelle].items():
            db.add(Mitglied(mandant_id=neu.id, benutzer_id=self.personen[kurz].id, rollen=rollen))
        for art, code, name in STAMM:
            db.add(Stammwert(mandant_id=neu.id, art=art, code=code, name=name))
        return neu

    def als(self, kurz: str, stelle: int = 0) -> Kontext:
        return kontext_aus(self.db, self.personen[kurz], self.mandanten[stelle].id)

    def partner(self, stelle: int, firma: Firma, konto: str, kostenstelle: str, **mehr) -> Partner:
        eintrag = Partner(
            mandant_id=self.mandanten[stelle].id,
            name=firma.name,
            kreditor=belege.naechster_kreditor(self.db, self.mandanten[stelle].id),
            uid=firma.uid,
            strasse=firma.strasse,
            plz=firma.plz,
            ort=firma.ort,
            ibans=[firma.iban],
            konto=konto,
            kostenstelle=kostenstelle,
            **mehr,
        )
        self.db.add(eintrag)
        self.db.flush()
        return eintrag

    def lade(self, wer: str, name: str, inhalt: bytes, stelle: int = 0, **mehr) -> Beleg:
        return belege.nimm_auf(self.als(wer, stelle), name, inhalt, **mehr)

    def frueher(
        self, v: Vorlage, konto: str, kostenstelle: str, tage: int, stelle: int = 0, pruefer: str = "bernd"
    ) -> Beleg:
        beleg = self.lade("anna", f"{v.nummer}.pdf", pdf(v), stelle)
        anna = self.als("anna", stelle)
        if beleg.status != "neu":
            self.verschiebe(beleg, tage, 1)
            return beleg
        if not beleg.lieferant_uid:
            belege.korrigiere(anna, beleg, {"lieferant_uid": v.lieferant.uid or PAPIER.uid})
        if (beleg.konto, beleg.kostenstelle) != (konto, kostenstelle):
            belege.korrigiere(anna, beleg, {"konto": konto, "kostenstelle": kostenstelle})
        freigabe.sofort(self.als(pruefer, stelle), "beleg", beleg, "Betrag und Leistung geprüft")
        self.verschiebe(beleg, tage, 20 + beleg.id % 5 * 9)
        return beleg

    def verschiebe(self, beleg: Beleg, tage: int, stunden: int) -> None:
        eingang = datetime.combine(vor(tage), datetime.min.time()).astimezone() + timedelta(hours=9)
        beleg.erstellt_am, beleg.freigegeben_am = eingang, eingang + timedelta(hours=stunden)
        self.db.commit()


def grundlagen(demo: Demo) -> None:
    db, m = demo.db, demo.mandanten[0].id
    person = {kurz: p.id for kurz, p in demo.personen.items()}
    demo.partner(0, PAPIER, "7600", "100", zahlungsziel=30, skonto_prozent="2", skonto_tage=10)
    demo.partner(0, REINIGUNG, "7200", "400", zahlungsziel=14)
    demo.partner(0, WOLKE, "7780", "300", zahlungsziel=30)
    telekom = demo.partner(0, NETZ, "7380", "100", zahlungsziel=14)
    demo.partner(0, WERBUNG, "7650", "200", zahlungsziel=21)
    demo.partner(0, BERATER, "7750", "100", zahlungsziel=14)
    demo.partner(0, LIFT, "7200", "400", zahlungsziel=30)
    demo.partner(0, MOEBEL, "7600", "100", zahlungsziel=30, skonto_prozent="3", skonto_tage=14)
    team = Team(mandant_id=m, name="Geschäftsführung", mitglieder=[person["bernd"], person["eva"]])
    db.add(team)
    db.flush()
    klein = Workflow(
        mandant_id=m,
        name="Rechnungen bis 1.000 €",
        rang=10,
        bedingung={"art": "beleg", "bis": "1000"},
        schritte=[{"art": "person", "id": person["clara"]}],
    )
    gross = Workflow(
        mandant_id=m,
        name="Rechnungen über 1.000 €",
        rang=20,
        bedingung={"art": "beleg"},
        schritte=[{"art": "person", "id": person["clara"]}, {"art": "team", "id": team.id}],
    )
    bestellung = Workflow(
        mandant_id=m,
        name="Bestellungen",
        rang=30,
        bedingung={"art": "anforderung"},
        schritte=[{"art": "person", "id": person["bernd"]}],
    )
    spesen = Workflow(
        mandant_id=m,
        name="Erstattungen",
        rang=40,
        bedingung={"art": "erstattung"},
        schritte=[{"art": "team", "id": team.id}],
    )
    db.add_all([klein, gross, bestellung, spesen])
    db.flush()
    db.add(Automatik(mandant_id=m, name="Reinigung vorschlagen", aktion="vorschlagen", max_brutto=D(1500), gleiche=3))
    db.add(
        Automatik(
            mandant_id=m, name="Telekom bis 400 €", aktion="freigeben", partner_id=telekom.id, max_brutto=D(400), gleiche=3
        )
    )
    for art, wert, budget in (
        ("kostenstelle", "100", 30000),
        ("kostenstelle", "300", 18000),
        ("kostenstelle", "400", 24000),
        ("konto", "7650", 9000),
    ):
        db.add(Auswertung(mandant_id=m, art=art, wert=wert, budget=D(budget)))
    db.add(Sperre(mandant_id=m, art="iban", wert=iban(666), grund="Betrugsversuch im September"))
    db.add(Sperre(mandant_id=m, art="absender", wert="gewinn.example", grund="Werbung"))
    demo.personen["clara"].abwesend_von = vor(1)
    demo.personen["clara"].abwesend_bis = HEUTE + timedelta(days=6)
    demo.personen["clara"].vertretung_id = person["bernd"]
    db.commit()


def vergangenheit(demo: Demo) -> None:
    for monat in range(9, 0, -1):
        tage = monat * 30
        nr = 10 - monat
        papier = ohne_uid(PAPIER) if monat in (1, 4) else PAPIER
        demo.frueher(
            rechnung(papier, MUSTER, f"PM-{nr:03d}", tage, posten("PM-100", "Kopierpapier A4", 30 + nr, "11.90")),
            "7600",
            "100",
            tage - 2,
        )
        demo.frueher(
            rechnung(
                REINIGUNG, MUSTER, f"RB-{nr:03d}", tage, posten("RB-1", "Reinigung Stiegenhaus", 1, "890", 20, "Monat")
            ),
            "7200",
            "400",
            tage - 3,
        )
        demo.frueher(
            rechnung(WOLKE, MUSTER, f"W7-{nr:03d}", tage, posten("W-10", "Cloud Arbeitsplätze", 24, "32.50", 20, "Monat")),
            "7780",
            "300",
            tage - 1,
        )
        if monat % 2:
            demo.frueher(
                rechnung(
                    NETZ, MUSTER, f"BT-{nr:03d}", tage, posten("N-5", "Internet und Telefon", 1, "318.40", 20, "Monat")
                ),
                "7380",
                "100",
                tage - 4,
            )
        if monat % 3 == 0:
            demo.frueher(
                rechnung(
                    BERATER,
                    MUSTER,
                    f"ZW-{nr:03d}",
                    tage,
                    posten("B-1", "Laufende Buchhaltung", 12, "125", 20, "Std"),
                    mit_uid=True,
                ),
                "7750",
                "100",
                tage - 5,
            )
            demo.frueher(
                rechnung(WERBUNG, MUSTER, f"PP-{nr:03d}", tage, posten("P-3", "Plakate Innenstadt", 60, "28", 20)),
                "7650",
                "200",
                tage - 6,
            )
    anna = demo.als("anna")
    alt = [
        b
        for b in demo.db.scalars(select(Beleg).where(Beleg.mandant_id == anna.mandant.id, Beleg.status == "freigegeben"))
        if b.datum < vor(45)
    ]
    offen = {p["id"] for p in zahlung.offene(anna) if not p["hindernis"]}
    auswahl = [{"art": "beleg", "id": b.id, "skonto": False} for b in alt if b.id in offen]
    zahlung.zahle(anna, auswahl, HEUTE)
    export.exportiere(anna, "bmd", [{"art": "beleg", "id": b.id} for b in alt])


def eingang(demo: Demo) -> None:
    lade = demo.lade
    lade(
        "anna",
        "papier_muster.pdf",
        pdf(
            rechnung(
                PAPIER,
                MUSTER,
                "PM-210",
                3,
                posten("PM-100", "Kopierpapier A4", 40, "11.90"),
                posten("FB-7", "Fachbuch Buchhaltung", 2, "45.50", 10),
                skonto=(2, 10),
            )
        ),
    )
    lade(
        "anna",
        "reinigung_november.pdf",
        pdf(
            rechnung(
                REINIGUNG, MUSTER, "RB-311", 19, posten("RB-1", "Reinigung Stiegenhaus", 1, "890", 20, "Monat"), ziel=14
            )
        ),
    )
    lade(
        "anna",
        "cloud_xrechnung.xml",
        ubl(rechnung(WOLKE, MUSTER, "W7-412", 5, posten("W-10", "Cloud Arbeitsplätze", 26, "32.50"), mit_uid=True)),
    )
    lade(
        "anna",
        "telekom_zugferd.pdf",
        zugferd(
            rechnung(NETZ, MUSTER, "BT-88", 18, posten("N-5", "Internet und Telefon", 1, "318.40"), ziel=14, mit_uid=True)
        ),
    )
    lade(
        "anna",
        "steuerberater_ebinterface.xml",
        ebinterface(
            rechnung(
                BERATER,
                MUSTER,
                "ZW-77",
                6,
                posten("B-1", "Laufende Buchhaltung", 14, "125"),
                posten("B-9", "Jahresabschluss", 1, "9800"),
                mit_uid=True,
            )
        ),
    )
    lade(
        "anna",
        "papier_falsche_summe.pdf",
        pdf(rechnung(PAPIER, MUSTER, "PM-211", 2, posten("PM-300", "Toner schwarz", 6, "96"), falsch=D(100))),
    )
    fremd = Firma(PAPIER.name, PAPIER.strasse, PAPIER.plz, PAPIER.ort, PAPIER.uid, iban(666))
    lade("anna", "papier_neue_iban.pdf", pdf(rechnung(fremd, MUSTER, "PM-212", 1, posten("PM-120", "Ordner", 80, "3.95"))))
    lade(
        "anna",
        "papier_duplikat.pdf",
        pdf(rechnung(PAPIER, MUSTER, "PM-210", 3, posten("PM-100", "Kopierpapier A4", 40, "11.90"), skonto=(2, 14))),
    )
    ohne = Firma("Blumen Testgarten", "Rosenweg 2", "1140", "Wien", "ATU12345670", iban(12))
    lade("anna", "blumen.pdf", pdf(rechnung(ohne, MUSTER, "B-19", 7, posten("B-2", "Pflanzen Empfang", 1, "640"))))
    taxi = Firma("Taxi Musterfahrt e.U.", "Bahnhofplatz 1", "1150", "Wien", None, iban(13))
    lade("david", "taxi.pdf", pdf(rechnung(taxi, MUSTER, "T-551", 2, posten("T-1", "Fahrt zum Flughafen", 1, "39.09", 10))))
    schweiz = Firma("Alpen Beispiel AG", "Dorfstrasse 4", "8001", "Zürich", "CHE123456789", None)
    lade(
        "anna",
        "messe_zuerich.pdf",
        pdf(rechnung(schweiz, MUSTER, "AB-9", 8, posten("M-1", "Messestand", 1, "1850", 0), waehrung="CHF")),
    )
    gutschrift = rechnung(
        WERBUNG, MUSTER, "GS-4", 5, posten("P-3", "Plakate zurück", 4, "28"), titel="GUTSCHRIFT", ziel=None
    )
    lade("anna", "gutschrift.pdf", pdf(gutschrift))
    scan = rechnung(MOEBEL, MUSTER, "MT-900", 9, posten("S-1", "Bürostuhl", 4, "249"))
    anna = demo.als("anna")
    abgelegt = ablegen(pdf(scan), "application/pdf")
    bild, _ = seite_als_png(pfad(abgelegt, "application/pdf"), 1)
    geklaert = lade("anna", "scan_moebel.png", bild)
    belege.setze_klaerung(anna, geklaert, True)
    belege.kommentieren(anna, "beleg", geklaert, "@Clara Huber kannst du bitte sagen, ob die Stühle geliefert wurden?")


def dokumente(demo: Demo) -> None:
    anna = demo.als("anna")
    miete = Vorlage(
        IMMO,
        MUSTER,
        "MV-2021-8",
        vor(400),
        [],
        titel="VERTRAG",
        ziel=None,
        zeilen=["Mietvertrag über Büroflächen im dritten Stock", "Laufzeit fünf Jahre, Verlängerung um ein Jahr"],
    )
    wartung = Vorlage(
        LIFT,
        MUSTER,
        "WV-77",
        vor(330),
        [],
        titel="VERTRAG",
        ziel=None,
        zeilen=["Wartungsvertrag für zwei Personenaufzüge", "Kündigung drei Monate vor Ablauf"],
    )
    software = Vorlage(
        WOLKE, MUSTER, "SV-12", vor(20), [], titel="VERTRAG", ziel=None, zeilen=["Softwarevertrag für 24 Arbeitsplätze"]
    )
    for name, v, werte in (
        (
            "mietvertrag.pdf",
            miete,
            {
                "typ": "Miete",
                "beginn": vor(400),
                "ende": vor(400) + timedelta(days=1826),
                "kuendigen_bis": HEUTE + timedelta(days=240),
            },
        ),
        (
            "wartung_aufzug.pdf",
            wartung,
            {
                "typ": "Wartung",
                "beginn": vor(330),
                "ende": HEUTE + timedelta(days=110),
                "kuendigen_bis": HEUTE + timedelta(days=20),
                "erinnerung_am": vor(1),
                "verantwortlich_id": demo.personen["bernd"].id,
                "informieren": [demo.personen["anna"].id],
            },
        ),
        ("softwarevertrag.pdf", software, None),
    ):
        beleg = demo.lade("anna", name, pdf(v))
        if werte:
            belege.vertrag_aendern(anna, beleg, werte)
            belege.setze_schlagwoerter(anna, beleg, [werte["typ"], "Vertrag"])
            belege.ablegen_im_archiv(anna, beleg)
            if werte["typ"] == "Miete":
                belege.setze_sichtbarkeit(anna, beleg, True, [demo.personen["bernd"].id])
    angebot = rechnung(
        MOEBEL, MUSTER, "AN-55", 35, posten("T-9", "Schreibtisch höhenverstellbar", 6, "489"), titel="ANGEBOT", ziel=None
    )
    demo.lade("anna", "angebot_moebel.pdf", pdf(angebot))


def bestellungen(demo: Demo) -> None:
    david, bernd, anna = demo.als("david"), demo.als("bernd"), demo.als("anna")
    tische = anforderung.anlegen(
        david,
        {
            "lieferant": MOEBEL.name,
            "titel": "Höhenverstellbare Tische",
            "beschreibung": "Sechs neue Arbeitsplätze für den Vertrieb",
            "kostenstelle": "200",
            "konto": "7600",
            "leistung_am": HEUTE + timedelta(days=10),
            "positionen": [{"nummer": "T-9", "text": "Schreibtisch höhenverstellbar", "menge": "6", "einzelpreis": "489"}],
        },
        None,
    )
    freigabe.entscheiden(bernd, "anforderung", tische, True)
    demo.db.commit()
    anforderung.erfasse_wareneingang(david, tische, vor(4), "LS-4711", {"0": "4"})
    beleg = demo.lade(
        "anna",
        "moebel_teilrechnung.pdf",
        pdf(
            rechnung(
                MOEBEL,
                MUSTER,
                "MT-921",
                3,
                posten("T-9", "Schreibtisch höhenverstellbar", 5, "499"),
                bestellnummer=tische.nummer,
                skonto=(3, 14),
            )
        ),
    )
    belege.verknuepfe(anna, beleg, "anforderung", tische.id)
    anforderung.anlegen(
        david,
        {
            "lieferant": WERBUNG.name,
            "titel": "Messebanner",
            "beschreibung": "Zwei Roll-ups für die Immobilienmesse",
            "kostenstelle": "200",
            "konto": "7650",
            "netto": "640",
        },
        None,
    )
    kaffee = anforderung.anlegen(
        demo.als("clara"),
        {"lieferant": "Kaffee Beispielhaus GmbH", "titel": "Kaffeemaschine", "kostenstelle": "100", "netto": "2890"},
        None,
    )
    freigabe.entscheiden(bernd, "anforderung", kaffee, False, "Bitte zwei Vergleichsangebote einholen")
    demo.db.commit()


def freigaben(demo: Demo) -> None:
    anna, db = demo.als("anna"), demo.db
    wolke = db.scalar(select(Beleg).where(Beleg.nummer == "W7-412"))
    berater = db.scalar(select(Beleg).where(Beleg.nummer == "ZW-77"))
    plakate = demo.lade(
        "anna",
        "plakate_winter.pdf",
        pdf(rechnung(WERBUNG, MUSTER, "PP-101", 26, posten("P-4", "Plakate Winteraktion", 25, "28"), ziel=21)),
    )
    for beleg in (wolke, plakate, berater):
        workflow = freigabe.waehle_workflow(anna, "beleg", beleg)
        freigabe.anfordern(anna, "beleg", beleg, workflow.schritte, "Geprüft", workflow.name)
        db.commit()
    freigabe.entscheiden(demo.als("bernd"), "beleg", berater, True)
    db.commit()
    neu = demo.lade(
        "anna",
        "plakate_rechnung.pdf",
        pdf(rechnung(WERBUNG, MUSTER, "PP-100", 12, posten("P-3", "Plakate Innenstadt", 20, "28"), ziel=21)),
    )
    freigabe.sofort(demo.als("eva"), "beleg", neu)
    ab = demo.lade(
        "anna",
        "aufzug_reparatur.pdf",
        pdf(rechnung(LIFT, MUSTER, "LB-31", 10, posten("L-4", "Reparatur Aufzug", 6, "142", 20, "Std"))),
    )
    workflow = freigabe.waehle_workflow(anna, "beleg", ab)
    freigabe.anfordern(anna, "beleg", ab, workflow.schritte, name=workflow.name)
    freigabe.entscheiden(demo.als("bernd"), "beleg", ab, False, "Stunden stimmen nicht mit dem Regiebericht überein")
    db.commit()


def spesen(demo: Demo) -> None:
    david, anna, clara = (demo.als(n) for n in ("david", "anna", "clara"))

    def wann(tage: int, stunde: int, minute: int = 0) -> str:
        return f"{vor(tage).isoformat()}T{stunde:02d}:{minute:02d}"

    reise = erstattung.anlegen(david, "Kundentermin München", "Abstimmung mit dem neuen Partner")
    taggeld = {
        "etappen": [
            {"land": "Österreich", "von": wann(15, 6, 30)},
            {"land": "Deutschland", "von": wann(15, 9, 45)},
            {"land": "Österreich", "von": wann(13, 16, 10)},
        ],
        "ende": wann(13, 19, 40),
        "mahlzeiten": {vor(15).isoformat(): ["abend"], vor(14).isoformat(): ["mittag", "abend"]},
        "naechte": [{"land": "Deutschland", "anzahl": 1}],
        "grund": "Kundentermin",
    }
    erstattung.posten_anlegen(david, reise, "taggeld", "Verpflegung München", vor(15), taggeld, None)
    fahrt = {"start": "Wien", "ziel": "München", "km": "402", "hin_zurueck": True, "fahrzeug": "pkw", "mitfahrer": 1}
    erstattung.posten_anlegen(david, reise, "kilometer", "", vor(15), fahrt | {"grund": "Kundentermin"}, None)
    park = Firma("Parkhaus Beispiel GmbH", "Ring 3", "1010", "Wien", uid("3141592"), None)
    beleg = pdf(rechnung(park, MUSTER, "P-12", 14, posten("P-1", "Parken", 1, "20")))
    erstattung.posten_anlegen(david, reise, "auslage", "Parkgebühr", None, {"grund": "Kundentermin"}, ("parken.pdf", beleg))
    erstattung.einreichen(david, reise)

    essen = erstattung.anlegen(clara, "Geschäftsessen Oktober", None)
    lokal = Firma("Gasthaus Musterwirt", "Marktplatz 2", "1080", "Wien", uid("2718281"), None)
    beleg = pdf(
        rechnung(lokal, MUSTER, "R-88", 26, posten("E-1", "Speisen", 1, "96.50", 10), posten("G-1", "Getränke", 1, "38"))
    )
    angaben = {
        "grund": "Vertragsverlängerung",
        "extern": "Peter Muster, Lift Beispiel",
        "intern": "Clara Huber",
        "trinkgeld": "12",
    }
    erstattung.posten_anlegen(clara, essen, "bewirtung", "Mittagessen Musterwirt", None, angaben, ("essen.pdf", beleg))
    erstattung.einreichen(clara, essen)
    erstattung.aendern(anna, essen, {"konto": "7690", "kostenstelle": "200"})
    workflow = freigabe.waehle_workflow(anna, "erstattung", essen)
    freigabe.anfordern(anna, "erstattung", essen, workflow.schritte, name=workflow.name)
    demo.db.commit()

    bahn = erstattung.anlegen(david, "Bahnfahrt Linz", None)
    eigen = {"betrag": "41.80", "ust": "3.80", "grund": "Besichtigung", "eigenbeleg": "Ticket in der App gekauft"}
    erstattung.posten_anlegen(david, bahn, "auslage", "Zugticket", vor(40), eigen, None)
    erstattung.einreichen(david, bahn)
    erstattung.aendern(anna, bahn, {"konto": "7340", "kostenstelle": "200"})
    freigabe.sofort(demo.als("eva"), "erstattung", bahn)
    demo.db.commit()
    entwurf = erstattung.anlegen(david, "Werkzeug Baumarkt", "Rechnung folgt")
    erstattung.posten_anlegen(
        david, entwurf, "auslage", "Bohrer", vor(3), {"betrag": "24.90", "ust": "4.15", "grund": "Montage Regal"}, None
    )


def firmenkarten(demo: Demo) -> None:
    anna, david = demo.als("anna"), demo.als("david")
    karten.anlegen(
        anna,
        {
            "name": "Reisekarte",
            "inhaber_id": demo.personen["david"].id,
            "letzte4": "4242",
            "limit_monat": D(2000),
            "limit_zahlung": D(800),
            "konto": "7340",
            "kostenstelle": "200",
        },
    )
    karten.anlegen(
        anna,
        {
            "name": "Online-Einkauf",
            "inhaber_id": demo.personen["anna"].id,
            "letzte4": "1881",
            "limit_monat": D(1500),
            "konto": "7780",
            "kostenstelle": "300",
        },
    )
    karten.anlegen(david, {"name": "Messekarte", "limit_monat": D(500), "grund": "Immobilienmesse im Frühjahr"})
    hotel = Firma("Hotel Beispielblick GmbH", "Seeweg 5", "5020", "Salzburg", uid("1618033"), None)
    demo.lade(
        "david",
        "hotel.pdf",
        pdf(rechnung(hotel, MUSTER, "H-204", 6, posten("Z-1", "Zimmer mit Frühstück", 2, "118", 10, "Stk"))),
        quelle="karte",
    )
    zeilen = [
        "Karte;Datum;Händler;Betrag;Währung",
        f"**** 4242;{vor(6):%d.%m.%Y};HOTEL BEISPIELBLICK SALZBURG;259,60;EUR",
        f"**** 4242;{vor(5):%d.%m.%Y};TANKSTELLE MUSTER A1;74,30;EUR",
        f"**** 4242;{vor(2):%d.%m.%Y};BISTRO TESTECK;18,90;EUR",
        f"**** 1881;{vor(3):%d.%m.%Y};SCHRIFTEN BEISPIEL;59,00;EUR",
    ]
    karten.importiere(anna, "\r\n".join(zeilen).encode())


def postfach(demo: Demo) -> None:
    k = Kontext(demo.db, demo.mandanten[0], "n8n", {"eingang"})
    v = rechnung(LIFT, MUSTER, "LB-40", 1, posten("L-1", "Wartung Aufzug", 2, "185"))
    kopf = {"kennung": "<1@lift.example>", "absender": "Lift Beispiel <rechnung@lift.example>", "betreff": "Rechnung LB-40"}
    post.nimm_an(k, kopf | {"text": "Anbei unsere Rechnung."}, ("LB-40.pdf", pdf(v)))
    kopf = {"kennung": "<2@wolke.example>", "absender": "info@wolke.example", "betreff": "Wartungsfenster am Sonntag"}
    post.nimm_an(k, kopf | {"text": "Am Sonntag sind die Dienste kurz nicht erreichbar."}, None)
    kopf = {"kennung": "<3@gewinn.example>", "absender": "hallo@gewinn.example", "betreff": "Sie haben gewonnen"}
    post.nimm_an(k, kopf | {"text": ""}, ("gewinn.pdf", pdf(v)))


def andere_mandanten(demo: Demo) -> None:
    demo.partner(1, PAPIER, "7600", "100", zahlungsziel=30)
    demo.partner(1, REINIGUNG, "7200", "400", zahlungsziel=14)
    for nummer, monat in enumerate((3, 2, 1), 1):
        v = rechnung(REINIGUNG, GASTRO, f"RG-{nummer}", monat * 30, posten("RB-2", "Reinigung Küche", 1, "640", 20, "Monat"))
        demo.frueher(v, "7200", "400", monat * 30 - 2, stelle=1)
    demo.lade(
        "anna", "reinigung.pdf", pdf(rechnung(REINIGUNG, GASTRO, "RG-9", 4, posten("RB-2", "Reinigung Küche", 1, "640"))), 1
    )
    demo.lade(
        "anna", "papier.pdf", pdf(rechnung(PAPIER, GASTRO, "PM-310", 2, posten("PM-100", "Kopierpapier A4", 10, "11.90"))), 1
    )
    demo.partner(2, BAU, "7200", "300", zahlungsziel=30)
    demo.partner(2, LIFT, "7200", "400", zahlungsziel=30)
    dach = rechnung(BAU, IMMO, "BD-71", 6, posten("D-1", "Dachsanierung Teil 1", 1, "18400"), mit_uid=True)
    demo.lade("anna", "dach_zugferd.pdf", zugferd(dach), 2)
    demo.lade(
        "anna", "lift.xml", cii(rechnung(LIFT, IMMO, "LB-55", 3, posten("L-1", "Wartung Aufzug", 4, "185"), mit_uid=True)), 2
    )


def anlegen(db: Session, passwort: str | None = None) -> dict[str, str]:
    demo = Demo(db, passwort)
    for teil in (
        grundlagen,
        vergangenheit,
        eingang,
        dokumente,
        bestellungen,
        freigaben,
        spesen,
        firmenkarten,
        postfach,
        andere_mandanten,
    ):
        teil(demo)
        db.commit()
    return demo.passwoerter
