from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Basis, Betrag, Zeit


def jetzt() -> datetime:
    return datetime.now(UTC)


class Benutzer(Basis):
    __tablename__ = "benutzer"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    passwort: Mapped[str] = mapped_column(String(200))
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    iban: Mapped[str | None] = mapped_column(String(40))
    abwesend_von: Mapped[date | None] = mapped_column(Date)
    abwesend_bis: Mapped[date | None] = mapped_column(Date)
    vertretung_id: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Sitzung(Basis):
    __tablename__ = "sitzungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    laeuft_ab: Mapped[datetime] = mapped_column(Zeit)


class Anmeldeversuch(Basis):
    __tablename__ = "anmeldeversuche"

    id: Mapped[int] = mapped_column(primary_key=True)
    schluessel: Mapped[str] = mapped_column(String(250), index=True)
    zeitpunkt: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Mandant(Basis):
    __tablename__ = "mandanten"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    strasse: Mapped[str] = mapped_column(String(200), default="")
    plz: Mapped[str] = mapped_column(String(10), default="")
    ort: Mapped[str] = mapped_column(String(100), default="")
    land: Mapped[str] = mapped_column(String(2), default="AT")
    uid: Mapped[str | None] = mapped_column(String(20))
    iban: Mapped[str | None] = mapped_column(String(40))
    bic: Mapped[str | None] = mapped_column(String(11))
    einstellungen: Mapped[dict] = mapped_column(JSON, default=dict)


class Mitglied(Basis):
    __tablename__ = "mitglieder"

    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), primary_key=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), primary_key=True)
    rollen: Mapped[list] = mapped_column(JSON, default=list)


class Zugang(Basis):
    __tablename__ = "zugaenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    rollen: Mapped[list] = mapped_column(JSON, default=list)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Team(Basis):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    mitglieder: Mapped[list] = mapped_column(JSON, default=list)


class Partner(Basis):
    __tablename__ = "partner"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kreditor: Mapped[str | None] = mapped_column(String(20))
    uid: Mapped[str | None] = mapped_column(String(20), index=True)
    strasse: Mapped[str | None] = mapped_column(String(200))
    plz: Mapped[str | None] = mapped_column(String(10))
    ort: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200))
    ibans: Mapped[list] = mapped_column(JSON, default=list)
    zahlungsziel: Mapped[int | None] = mapped_column()
    skonto_prozent: Mapped[str | None] = mapped_column(String(6))
    skonto_tage: Mapped[int | None] = mapped_column()
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    steuerschluessel: Mapped[str | None] = mapped_column(String(20))


class Stammwert(Basis):
    __tablename__ = "stammwerte"
    __table_args__ = (UniqueConstraint("mandant_id", "art", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    art: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    daten: Mapped[dict] = mapped_column(JSON, default=dict)


class Sperre(Basis):
    __tablename__ = "sperren"
    __table_args__ = (UniqueConstraint("mandant_id", "art", "wert"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    art: Mapped[str] = mapped_column(String(10))
    wert: Mapped[str] = mapped_column(String(200))
    grund: Mapped[str] = mapped_column(String(300), default="")


class Nachricht(Basis):
    __tablename__ = "nachrichten"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    kennung: Mapped[str] = mapped_column(String(300), index=True)
    absender: Mapped[str] = mapped_column(String(300))
    betreff: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20))
    empfangen_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Beleg(Basis):
    __tablename__ = "belege"
    __table_args__ = (UniqueConstraint("mandant_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    art: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    dateiname: Mapped[str] = mapped_column(String(255))
    dateityp: Mapped[str] = mapped_column(String(50))
    sha256: Mapped[str] = mapped_column(String(64))
    quelle: Mapped[str] = mapped_column(String(20))
    nachricht_id: Mapped[int | None] = mapped_column(ForeignKey("nachrichten.id"))
    hochgeladen_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    hochgeladen_name: Mapped[str] = mapped_column(String(80))
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partner.id"), index=True)

    lieferant: Mapped[str | None] = mapped_column(String(255))
    lieferant_adresse: Mapped[str | None] = mapped_column(String(300))
    lieferant_uid: Mapped[str | None] = mapped_column(String(20), index=True)
    empfaenger: Mapped[str | None] = mapped_column(String(255))
    empfaenger_adresse: Mapped[str | None] = mapped_column(String(300))
    empfaenger_uid: Mapped[str | None] = mapped_column(String(20))
    nummer: Mapped[str | None] = mapped_column(String(80))
    datum: Mapped[date | None] = mapped_column(Date)
    leistung_von: Mapped[date | None] = mapped_column(Date)
    leistung_bis: Mapped[date | None] = mapped_column(Date)
    faellig_am: Mapped[date | None] = mapped_column(Date)
    skonto_bis: Mapped[date | None] = mapped_column(Date)
    skonto_prozent: Mapped[str | None] = mapped_column(String(6))
    bestellnummer: Mapped[str | None] = mapped_column(String(80))
    iban: Mapped[str | None] = mapped_column(String(40))
    bic: Mapped[str | None] = mapped_column(String(11))
    waehrung: Mapped[str] = mapped_column(String(3), default="EUR")
    netto: Mapped[Decimal | None] = mapped_column(Betrag)
    ust: Mapped[Decimal | None] = mapped_column(Betrag)
    brutto: Mapped[Decimal | None] = mapped_column(Betrag)
    steuerzeilen: Mapped[list] = mapped_column(JSON, default=list)
    positionen: Mapped[list] = mapped_column(JSON, default=list)

    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    kostentraeger: Mapped[str | None] = mapped_column(String(20))
    steuerschluessel: Mapped[str | None] = mapped_column(String(20))
    buchungstext: Mapped[str | None] = mapped_column(String(200))
    notiz: Mapped[str | None] = mapped_column(String(1000))
    aufteilung: Mapped[list] = mapped_column(JSON, default=list)

    erkannt: Mapped[dict] = mapped_column(JSON, default=dict)
    e_rechnung: Mapped[str | None] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text, default="")
    pruefbericht: Mapped[list] = mapped_column(JSON, default=list)
    stufe: Mapped[str] = mapped_column(String(10), default="ok")
    automatisch: Mapped[bool] = mapped_column(Boolean, default=False)
    automatik: Mapped[str | None] = mapped_column(String(20))
    zahlstatus: Mapped[str] = mapped_column(String(20), default="offen")
    klaerung: Mapped[bool] = mapped_column(Boolean, default=False)
    eingeschraenkt: Mapped[bool] = mapped_column(Boolean, default=False)
    sichtbar: Mapped[list] = mapped_column(JSON, default=list)
    bestaetigte_iban: Mapped[str | None] = mapped_column(String(40))
    kein_duplikat: Mapped[bool] = mapped_column(Boolean, default=False)
    bearbeitet_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    freigegeben_am: Mapped[datetime | None] = mapped_column(Zeit)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt, index=True)


class Vertrag(Basis):
    __tablename__ = "vertraege"

    beleg_id: Mapped[int] = mapped_column(ForeignKey("belege.id"), primary_key=True)
    typ: Mapped[str | None] = mapped_column(String(80))
    beginn: Mapped[date | None] = mapped_column(Date)
    ende: Mapped[date | None] = mapped_column(Date)
    kuendigen_bis: Mapped[date | None] = mapped_column(Date)
    erinnerung_am: Mapped[date | None] = mapped_column(Date)
    verantwortlich_id: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    informieren: Mapped[list] = mapped_column(JSON, default=list)


class Anhang(Basis):
    __tablename__ = "anhaenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    objekt_art: Mapped[str] = mapped_column(String(20))
    objekt_id: Mapped[int] = mapped_column(index=True)
    dateiname: Mapped[str] = mapped_column(String(255))
    dateityp: Mapped[str] = mapped_column(String(50))
    sha256: Mapped[str] = mapped_column(String(64))
    von: Mapped[str] = mapped_column(String(80))
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Schlagwort(Basis):
    __tablename__ = "schlagwoerter"

    beleg_id: Mapped[int] = mapped_column(ForeignKey("belege.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), primary_key=True)


class Verknuepfung(Basis):
    __tablename__ = "verknuepfungen"

    a_art: Mapped[str] = mapped_column(String(20), primary_key=True)
    a_id: Mapped[int] = mapped_column(primary_key=True)
    b_art: Mapped[str] = mapped_column(String(20), primary_key=True)
    b_id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    von: Mapped[str] = mapped_column(String(80))


class Workflow(Basis):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    rang: Mapped[int] = mapped_column(default=10)
    bedingung: Mapped[dict] = mapped_column(JSON, default=dict)
    schritte: Mapped[list] = mapped_column(JSON, default=list)


class Automatik(Basis):
    __tablename__ = "automatiken"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    aktion: Mapped[str] = mapped_column(String(20))
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partner.id"))
    max_brutto: Mapped[Decimal] = mapped_column(Betrag)
    gleiche: Mapped[int] = mapped_column(default=3)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflows.id"))
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Freigabeschritt(Basis):
    __tablename__ = "freigabeschritte"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    objekt_art: Mapped[str] = mapped_column(String(20))
    objekt_id: Mapped[int] = mapped_column(index=True)
    runde: Mapped[int] = mapped_column(default=1)
    reihenfolge: Mapped[int] = mapped_column()
    ziel_art: Mapped[str] = mapped_column(String(10))
    ziel_id: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20))
    angefragt_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    entschieden_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    in_vertretung: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    entschieden_am: Mapped[datetime | None] = mapped_column(Zeit)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Protokoll(Basis):
    __tablename__ = "protokoll"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    objekt_art: Mapped[str] = mapped_column(String(20))
    objekt_id: Mapped[int] = mapped_column(index=True)
    wer: Mapped[str] = mapped_column(String(80))
    aktion: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON)
    zeitpunkt: Mapped[str] = mapped_column(String(40))
    vorgaenger: Mapped[str] = mapped_column(String(64))
    pruefsumme: Mapped[str] = mapped_column(String(64))


class Mitteilung(Basis):
    __tablename__ = "mitteilungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), index=True)
    text: Mapped[str] = mapped_column(String(300))
    ziel: Mapped[str] = mapped_column(String(60))
    gelesen: Mapped[bool] = mapped_column(Boolean, default=False)
    zugestellt: Mapped[bool] = mapped_column(Boolean, default=False)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Zahlung(Basis):
    __tablename__ = "zahlungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    von: Mapped[str] = mapped_column(String(80))
    ausfuehrung: Mapped[date] = mapped_column(Date)
    summe: Mapped[Decimal] = mapped_column(Betrag)
    posten: Mapped[list] = mapped_column(JSON, default=list)
    xml: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Export(Basis):
    __tablename__ = "exporte"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    von: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(20))
    anzahl: Mapped[int] = mapped_column()
    posten: Mapped[list] = mapped_column(JSON, default=list)
    dateiname: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64))
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Rueckstellung(Basis):
    __tablename__ = "rueckstellungen"
    __table_args__ = (UniqueConstraint("beleg_id", "periode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    beleg_id: Mapped[int] = mapped_column(ForeignKey("belege.id"))
    periode: Mapped[str] = mapped_column(String(7))
    betrag: Mapped[Decimal] = mapped_column(Betrag)
    konto: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="gebucht")


class Erstattung(Basis):
    __tablename__ = "erstattungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), index=True)
    titel: Mapped[str] = mapped_column(String(120))
    hinweis: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), index=True, default="entwurf")
    zahlstatus: Mapped[str] = mapped_column(String(20), default="offen")
    iban: Mapped[str | None] = mapped_column(String(40))
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    bearbeitet_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    freigegeben_am: Mapped[datetime | None] = mapped_column(Zeit)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Erstattungsposten(Basis):
    __tablename__ = "erstattungsposten"

    id: Mapped[int] = mapped_column(primary_key=True)
    erstattung_id: Mapped[int] = mapped_column(ForeignKey("erstattungen.id"), index=True)
    art: Mapped[str] = mapped_column(String(20))
    titel: Mapped[str] = mapped_column(String(200), default="")
    datum: Mapped[date | None] = mapped_column(Date)
    daten: Mapped[dict] = mapped_column(JSON, default=dict)
    rechnung: Mapped[list] = mapped_column(JSON, default=list)
    betrag: Mapped[Decimal] = mapped_column(Betrag, default=Decimal(0))
    ust: Mapped[Decimal] = mapped_column(Betrag, default=Decimal(0))
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    ausgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
    dateiname: Mapped[str | None] = mapped_column(String(255))
    dateityp: Mapped[str | None] = mapped_column(String(50))
    sha256: Mapped[str | None] = mapped_column(String(64))


class Anforderung(Basis):
    __tablename__ = "anforderungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), index=True)
    nummer: Mapped[str | None] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="freigabe")
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partner.id"))
    lieferant: Mapped[str] = mapped_column(String(255))
    titel: Mapped[str] = mapped_column(String(200))
    beschreibung: Mapped[str] = mapped_column(String(2000), default="")
    notiz: Mapped[str | None] = mapped_column(String(1000))
    leistung_am: Mapped[date | None] = mapped_column(Date)
    netto: Mapped[Decimal] = mapped_column(Betrag)
    positionen: Mapped[list] = mapped_column(JSON, default=list)
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    bearbeitet_von: Mapped[int | None] = mapped_column(ForeignKey("benutzer.id"))
    freigegeben_am: Mapped[datetime | None] = mapped_column(Zeit)
    erstellt_am: Mapped[datetime] = mapped_column(Zeit, default=jetzt)


class Wareneingang(Basis):
    __tablename__ = "wareneingaenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    anforderung_id: Mapped[int] = mapped_column(ForeignKey("anforderungen.id"), index=True)
    datum: Mapped[date] = mapped_column(Date)
    lieferschein: Mapped[str | None] = mapped_column(String(80))
    mengen: Mapped[dict] = mapped_column(JSON, default=dict)
    von: Mapped[str] = mapped_column(String(80))


class Karte(Basis):
    __tablename__ = "karten"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    inhaber_id: Mapped[int] = mapped_column(ForeignKey("benutzer.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    letzte4: Mapped[str | None] = mapped_column(String(4))
    art: Mapped[str] = mapped_column(String(20), default="virtuell")
    status: Mapped[str] = mapped_column(String(20), default="beantragt")
    limit_monat: Mapped[Decimal] = mapped_column(Betrag)
    limit_zahlung: Mapped[Decimal | None] = mapped_column(Betrag)
    gueltig_bis: Mapped[date | None] = mapped_column(Date)
    konto: Mapped[str | None] = mapped_column(String(20))
    kostenstelle: Mapped[str | None] = mapped_column(String(20))
    grund: Mapped[str] = mapped_column(String(300), default="")


class Transaktion(Basis):
    __tablename__ = "transaktionen"
    __table_args__ = (UniqueConstraint("mandant_id", "kennung"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    karte_id: Mapped[int] = mapped_column(ForeignKey("karten.id"), index=True)
    kennung: Mapped[str] = mapped_column(String(120))
    datum: Mapped[date] = mapped_column(Date)
    haendler: Mapped[str] = mapped_column(String(200))
    betrag: Mapped[Decimal] = mapped_column(Betrag)
    waehrung: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="fehlt")
    beleg_id: Mapped[int | None] = mapped_column(ForeignKey("belege.id"))


class Auswertung(Basis):
    __tablename__ = "auswertungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandant_id: Mapped[int] = mapped_column(ForeignKey("mandanten.id"), index=True)
    art: Mapped[str] = mapped_column(String(20))
    wert: Mapped[str] = mapped_column(String(80))
    budget: Mapped[Decimal] = mapped_column(Betrag)


class Kurs(Basis):
    __tablename__ = "kurse"

    waehrung: Mapped[str] = mapped_column(String(3), primary_key=True)
    datum: Mapped[date] = mapped_column(Date, primary_key=True)
    kurs: Mapped[str] = mapped_column(String(20))
