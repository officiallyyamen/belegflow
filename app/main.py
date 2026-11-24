import hmac
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from . import auswertung, service
from .bild import BildFehler, seite_als_png
from .config import Benutzer, einstellungen
from .db import Beleg, Protokoll, Regel, datenbank
from .export import als_csv
from .schemas import Begruendung, BelegAntwort, Kommentar, Korrektur, ProtokollAntwort, RegelAntwort, RegelEingabe

app = FastAPI(title="Belegflow", version="1.1.0")
STATISCH = Path(__file__).parent / "static"
RICHTLINIE = "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
KOPFZEILEN = {"Content-Security-Policy": RICHTLINIE, "X-Content-Type-Options": "nosniff"}
app.mount("/static", StaticFiles(directory=STATISCH), name="static")
anmeldung = HTTPBearer(auto_error=False)

Db = Annotated[Session, Depends(datenbank)]


def angemeldet(zugang: Annotated[HTTPAuthorizationCredentials | None, Depends(anmeldung)]) -> Benutzer:
    if zugang:
        for token, benutzer in einstellungen().benutzer.items():
            if hmac.compare_digest(token.encode(), zugang.credentials.encode()):
                return benutzer
    raise HTTPException(401, "Anmeldung fehlt oder ist ungültig")


def rolle(*erlaubt: str):
    def pruefe(benutzer: Annotated[Benutzer, Depends(angemeldet)]) -> Benutzer:
        if not set(erlaubt) & set(benutzer.rollen):
            raise HTTPException(403, "Dafür fehlt die Berechtigung")
        return benutzer

    return pruefe


Eingang = Annotated[Benutzer, Depends(rolle("eingang", "buchhaltung"))]
Buchhaltung = Annotated[Benutzer, Depends(rolle("buchhaltung"))]
Freigabe = Annotated[Benutzer, Depends(rolle("freigabe"))]
Leser = Annotated[Benutzer, Depends(rolle("buchhaltung", "freigabe"))]


def hole(beleg_id: int, db: Db) -> Beleg:
    beleg = db.get(Beleg, beleg_id)
    if not beleg:
        raise HTTPException(404, "Beleg nicht gefunden")
    return beleg


BelegDb = Annotated[Beleg, Depends(hole)]


def pfad_zu(beleg: Beleg) -> Path:
    endung = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}[beleg.dateityp]
    pfad = einstellungen().speicher / f"{beleg.sha256}{endung}"
    if not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    return pfad


@app.middleware("http")
async def zwischenspeicher(anfrage: Request, weiter):
    antwort = await weiter(anfrage)
    oeffentlich = anfrage.url.path == "/" or anfrage.url.path.startswith("/static/")
    antwort.headers["Cache-Control"] = "no-cache" if oeffentlich else "no-store"
    return antwort


@app.exception_handler(service.Konflikt)
def bei_konflikt(_: Request, fehler: service.Konflikt):
    return JSONResponse({"detail": str(fehler), "beleg_id": fehler.beleg_id}, 409)


@app.exception_handler(service.Ungueltig)
def bei_ungueltig(_: Request, fehler: service.Ungueltig):
    return JSONResponse({"detail": str(fehler)}, 422)


@app.get("/", include_in_schema=False)
def oberflaeche():
    return FileResponse(STATISCH / "index.html", headers=KOPFZEILEN)


@app.get("/status")
def status(db: Db):
    db.execute(select(1))
    return {"status": "ok", "extraktor": einstellungen().extraktor}


@app.get("/ich")
def ich(benutzer: Annotated[Benutzer, Depends(angemeldet)]) -> Benutzer:
    return benutzer


@app.post("/belege", status_code=201)
def aufnehmen(db: Db, benutzer: Eingang, datei: Annotated[UploadFile, File()]) -> BelegAntwort:
    inhalt = datei.file.read(einstellungen().max_mb * 1024 * 1024 + 1)
    return service.nimm_auf(db, datei.filename or "beleg", inhalt, benutzer)


@app.get("/belege")
def liste(
    db: Db,
    _: Leser,
    status: str | None = None,
    suche: Annotated[str | None, Query(max_length=80)] = None,
    grenze: Annotated[int, Query(ge=1, le=200)] = 50,
    ab: Annotated[int, Query(ge=0)] = 0,
) -> list[BelegAntwort]:
    abfrage = select(Beleg).order_by(Beleg.id.desc()).limit(grenze).offset(ab)
    if status:
        abfrage = abfrage.where(Beleg.status == status)
    if suche:
        abfrage = abfrage.where(
            or_(
                Beleg.lieferant.icontains(suche, autoescape=True),
                Beleg.rechnungsnummer.icontains(suche, autoescape=True),
                Beleg.lieferant_uid.icontains(suche, autoescape=True),
            )
        )
    return list(db.scalars(abfrage))


@app.get("/belege/{beleg_id}")
def einzeln(beleg: BelegDb, _: Leser) -> BelegAntwort:
    return beleg


@app.get("/belege/{beleg_id}/datei")
def datei(beleg: BelegDb, _: Leser):
    return FileResponse(pfad_zu(beleg), media_type=beleg.dateityp, headers={"X-Content-Type-Options": "nosniff"})


@app.get("/belege/{beleg_id}/bild")
def bild(beleg: BelegDb, _: Leser, seite: Annotated[int, Query(ge=1, le=200)] = 1):
    pfad = pfad_zu(beleg)
    if beleg.dateityp != "application/pdf":
        return FileResponse(pfad, media_type=beleg.dateityp, headers={"X-Seiten": "1"})
    try:
        inhalt, seiten = seite_als_png(pfad, seite)
    except BildFehler as fehler:
        raise HTTPException(422, str(fehler)) from fehler
    return Response(inhalt, media_type="image/png", headers={"X-Seiten": str(seiten)})


@app.patch("/belege/{beleg_id}")
def korrigieren(beleg: BelegDb, eingabe: Korrektur, db: Db, benutzer: Buchhaltung) -> BelegAntwort:
    return service.korrigiere(db, beleg, eingabe.model_dump(exclude_unset=True), benutzer)


@app.post("/belege/{beleg_id}/freigabe")
def freigeben(beleg: BelegDb, db: Db, benutzer: Freigabe) -> BelegAntwort:
    return service.gib_frei(db, beleg, benutzer)


@app.post("/belege/{beleg_id}/ablehnung")
def ablehnen(beleg: BelegDb, eingabe: Begruendung, db: Db, benutzer: Freigabe) -> BelegAntwort:
    return service.lehne_ab(db, beleg, eingabe.grund, benutzer)


@app.post("/belege/{beleg_id}/iban-bestaetigung")
def iban_bestaetigen(beleg: BelegDb, eingabe: Begruendung, db: Db, benutzer: Freigabe) -> BelegAntwort:
    return service.bestaetige_iban(db, beleg, eingabe.grund, benutzer)


@app.post("/belege/{beleg_id}/kommentar", status_code=201)
def kommentieren(beleg: BelegDb, eingabe: Kommentar, db: Db, benutzer: Leser) -> list[ProtokollAntwort]:
    service.protokolliere(db, beleg, benutzer.name, "kommentar", text=eingabe.text)
    db.commit()
    return protokoll(beleg, db, benutzer)


@app.get("/belege/{beleg_id}/protokoll")
def protokoll(beleg: BelegDb, db: Db, _: Leser) -> list[ProtokollAntwort]:
    return list(db.scalars(select(Protokoll).where(Protokoll.beleg_id == beleg.id).order_by(Protokoll.id)))


@app.get("/protokoll")
def gesamtprotokoll(db: Db, _: Leser, grenze: Annotated[int, Query(ge=1, le=200)] = 50) -> list[ProtokollAntwort]:
    return list(db.scalars(select(Protokoll).order_by(Protokoll.id.desc()).limit(grenze)))


@app.get("/uebersicht")
def uebersicht(db: Db, _: Leser):
    return auswertung.uebersicht(db)


@app.get("/lieferanten")
def lieferanten(db: Db, _: Leser):
    return auswertung.lieferanten(db)


@app.get("/benutzer")
def benutzerliste(_: Leser) -> list[Benutzer]:
    return list(einstellungen().benutzer.values())


@app.get("/regeln")
def regeln(db: Db, _: Leser) -> list[RegelAntwort]:
    return list(db.scalars(select(Regel).order_by(Regel.lieferant, Regel.id)))


@app.post("/regeln", status_code=201)
def regel_anlegen(eingabe: RegelEingabe, db: Db, benutzer: Buchhaltung) -> RegelAntwort:
    return service.lege_regel_an(db, eingabe.model_dump(), benutzer)


@app.delete("/regeln/{regel_id}", status_code=204)
def regel_loeschen(regel_id: int, db: Db, _: Buchhaltung):
    if not db.execute(delete(Regel).where(Regel.id == regel_id)).rowcount:
        raise HTTPException(404, "Regel nicht gefunden")
    db.commit()


@app.get("/protokoll/pruefung")
def protokoll_pruefen(db: Db, _: Leser):
    gueltig, eintrag = service.protokoll_gueltig(db)
    return {"gueltig": gueltig, "fehler_bei": eintrag}


@app.post("/export")
def exportieren(db: Db, benutzer: Buchhaltung):
    belege = list(db.scalars(select(Beleg).where(Beleg.status == "freigegeben").order_by(Beleg.id).with_for_update()))
    if not belege:
        raise HTTPException(404, "Keine freigegebenen Belege")
    inhalt = als_csv(belege)
    for beleg in belege:
        beleg.status = "exportiert"
        service.protokolliere(db, beleg, benutzer.name, "exportiert")
    db.commit()
    return Response(
        inhalt,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="belegflow_export.csv"'},
    )
