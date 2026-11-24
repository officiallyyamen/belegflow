import csv
import io

from .db import Beleg

SPALTEN = [
    "Beleg",
    "Lieferant",
    "UID",
    "Rechnungsnummer",
    "Rechnungsdatum",
    "Faellig",
    "Konto",
    "Kostenstelle",
    "Steuersatz",
    "Netto",
    "USt",
    "Brutto",
    "Waehrung",
    "IBAN",
]


def text(wert) -> str:
    inhalt = "" if wert is None else str(wert)
    return "'" + inhalt if inhalt[:1] in ("=", "+", "-", "@", "\t", "\r") else inhalt


def betrag(wert) -> str:
    return "" if wert is None else str(wert).replace(".", ",")


def tag(wert) -> str:
    return wert.strftime("%d.%m.%Y") if wert else ""


def als_csv(belege: list[Beleg]) -> str:
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(SPALTEN)
    for beleg in belege:
        zeilen = beleg.steuerzeilen or [{"satz": "", "netto": beleg.netto, "ust": beleg.ust}]
        for zeile in zeilen:
            schreiber.writerow(
                [
                    beleg.id,
                    text(beleg.lieferant),
                    text(beleg.lieferant_uid),
                    text(beleg.rechnungsnummer),
                    tag(beleg.rechnungsdatum),
                    tag(beleg.faellig_am),
                    text(beleg.konto),
                    text(beleg.kostenstelle),
                    betrag(zeile["satz"]),
                    betrag(zeile["netto"]),
                    betrag(zeile["ust"]),
                    betrag(beleg.brutto),
                    beleg.waehrung,
                    text(beleg.iban),
                ]
            )
    return "﻿" + puffer.getvalue()
