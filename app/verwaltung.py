import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

from .db import sitzungen
from .dienste.protokoll import gueltig
from .modelle import Benutzer, Mandant, Mitglied, Sitzung
from .sicherheit import passwort_hash


def frage_passwort() -> str:
    passwort = os.environ.get("BELEGFLOW_PASSWORT") or getpass.getpass("Passwort: ")
    if len(passwort) < 12:
        sys.exit("Das Passwort braucht mindestens 12 Zeichen")
    return passwort


def admin(werte) -> None:
    with sitzungen()() as db:
        if db.scalar(select(func.count()).select_from(Benutzer).where(Benutzer.email == werte.email.lower())):
            sys.exit("Diese Person gibt es schon")
        benutzer = Benutzer(name=werte.name, email=werte.email.lower(), passwort=passwort_hash(frage_passwort()))
        mandant = Mandant(name=werte.mandant, einstellungen={"vier_augen": True})
        db.add_all([benutzer, mandant])
        db.flush()
        db.add(Mitglied(mandant_id=mandant.id, benutzer_id=benutzer.id, rollen=["admin", "buchhaltung"]))
        db.commit()
        print(f"{benutzer.name} verwaltet jetzt {mandant.name} mit der Nummer {mandant.id}")


def passwort(werte) -> None:
    with sitzungen()() as db:
        benutzer = db.scalar(select(Benutzer).where(Benutzer.email == werte.email.lower()))
        if not benutzer:
            sys.exit("Diese Person gibt es nicht")
        benutzer.passwort = passwort_hash(frage_passwort())
        db.execute(delete(Sitzung).where(Sitzung.benutzer_id == benutzer.id))
        db.commit()
        print("Passwort geändert, alle Anmeldungen beendet")


def sperren(werte) -> None:
    with sitzungen()() as db:
        benutzer = db.scalar(select(Benutzer).where(Benutzer.email == werte.email.lower()))
        if not benutzer:
            sys.exit("Diese Person gibt es nicht")
        benutzer.aktiv = False
        db.execute(delete(Sitzung).where(Sitzung.benutzer_id == benutzer.id))
        db.commit()
        print(f"{benutzer.name} kann sich nicht mehr anmelden")


def protokoll(_) -> None:
    with sitzungen()() as db:
        for mandant in db.scalars(select(Mandant).order_by(Mandant.id)):
            stimmt, stelle = gueltig(db, mandant.id)
            print(f"{mandant.name}: {'unverändert' if stimmt else f'verändert bei Eintrag {stelle}'}")


def demo(werte) -> None:
    from .demo.anlegen import anlegen

    with sitzungen()() as db:
        if db.scalar(select(func.count()).select_from(Benutzer)):
            sys.exit("Die Datenbank ist nicht leer, Demo-Daten werden nicht angelegt")
        zugaenge = anlegen(db, os.environ.get("BELEGFLOW_PASSWORT"))
    zeilen = [f"{email}  {wort}" for email, wort in zugaenge.items()]
    if werte.datei:
        Path(werte.datei).write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        print(f"Zugänge stehen in {werte.datei}")
    else:
        print("\n".join(zeilen))


def hauptprogramm() -> None:
    befehle = argparse.ArgumentParser(prog="python -m app.verwaltung")
    teile = befehle.add_subparsers(required=True)
    neu = teile.add_parser("admin", help="erste Person und ersten Mandanten anlegen")
    neu.add_argument("--name", required=True)
    neu.add_argument("--email", required=True)
    neu.add_argument("--mandant", required=True)
    neu.set_defaults(tun=admin)
    for name, tun, hilfe in (
        ("passwort", passwort, "Passwort setzen"),
        ("sperren", sperren, "Person sperren"),
    ):
        teil = teile.add_parser(name, help=hilfe)
        teil.add_argument("--email", required=True)
        teil.set_defaults(tun=tun)
    teile.add_parser("protokoll", help="Protokoll aller Mandanten prüfen").set_defaults(tun=protokoll)
    beispiel = teile.add_parser("demo", help="erfundene Firmen und Belege anlegen")
    beispiel.add_argument("--datei", help="Zugänge in diese Datei schreiben statt anzeigen")
    beispiel.set_defaults(tun=demo)
    werte = befehle.parse_args()
    werte.tun(werte)


if __name__ == "__main__":
    hauptprogramm()
