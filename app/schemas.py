from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Steuerzeile(BaseModel):
    satz: str
    netto: str
    ust: str


class Rechnung(BaseModel):
    lieferant: str | None
    lieferant_uid: str | None
    empfaenger: str | None
    rechnungsnummer: str | None
    rechnungsdatum: str | None
    faellig_am: str | None
    iban: str | None
    waehrung: str | None
    steuerzeilen: list[Steuerzeile]
    netto: str | None
    ust: str | None
    brutto: str | None


class Korrektur(BaseModel):
    lieferant: str | None = None
    lieferant_uid: str | None = None
    empfaenger: str | None = None
    rechnungsnummer: str | None = None
    rechnungsdatum: date | None = None
    faellig_am: date | None = None
    iban: str | None = None
    netto: Decimal | None = Field(default=None, decimal_places=2)
    ust: Decimal | None = Field(default=None, decimal_places=2)
    brutto: Decimal | None = Field(default=None, decimal_places=2)
    steuerzeilen: list[Steuerzeile] | None = None
    konto: str | None = Field(default=None, max_length=20)
    kostenstelle: str | None = Field(default=None, max_length=20)

    @field_validator("steuerzeilen")
    @classmethod
    def zahlen_pruefen(cls, zeilen):
        for zeile in zeilen or []:
            for wert in (zeile.satz, zeile.netto, zeile.ust):
                try:
                    Decimal(wert)
                except InvalidOperation as fehler:
                    raise ValueError("Steuerzeilen müssen Zahlen enthalten") from fehler
        return zeilen


class Begruendung(BaseModel):
    grund: str = Field(min_length=3, max_length=500)


class Hinweis(BaseModel):
    code: str
    stufe: str
    text: str


class BelegAntwort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dateiname: str
    status: str
    extraktor: str
    lieferant: str | None
    lieferant_uid: str | None
    empfaenger: str | None
    rechnungsnummer: str | None
    rechnungsdatum: date | None
    faellig_am: date | None
    iban: str | None
    waehrung: str
    netto: Decimal | None
    ust: Decimal | None
    brutto: Decimal | None
    steuerzeilen: list[Steuerzeile]
    konto: str | None
    kostenstelle: str | None
    hinweise: list[Hinweis]
    bearbeitet_von: str | None
    freigegeben_von: str | None
    erstellt_am: datetime


class ProtokollAntwort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    beleg_id: int
    benutzer: str
    aktion: str
    details: dict
    zeitpunkt: str
    pruefsumme: str
