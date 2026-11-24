import hmac
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .config import Benutzer, einstellungen
from .db import Beleg, Protokoll, datenbank
from .export import als_csv
from .schemas import Begruendung, BelegAntwort, Korrektur, ProtokollAntwort

app = FastAPI(title="Belegflow", version="1.0.0")
OBERFLAECHE = Path(__file__).parent / "static" / "index.html"
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


@app.exception_handler(service.Konflikt)
def bei_konflikt(_: Request, fehler: service.Konflikt):
    return JSONResponse({"detail": str(fehler), "beleg_id": fehler.beleg_id}, 409)


@app.exception_handler(service.Ungueltig)
def bei_ungueltig(_: Request, fehler: service.Ungueltig):
    return JSONResponse({"detail": str(fehler)}, 422)


@app.get("/", include_in_schema=False)
def oberflaeche():
    return FileResponse(OBERFLAECHE)


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
    grenze: Annotated[int, Query(ge=1, le=200)] = 50,
    ab: Annotated[int, Query(ge=0)] = 0,
) -> list[BelegAntwort]:
    abfrage = select(Beleg).order_by(Beleg.id.desc()).limit(grenze).offset(ab)
    if status:
        abfrage = abfrage.where(Beleg.status == status)
    return list(db.scalars(abfrage))


@app.get("/belege/{beleg_id}")
def einzeln(beleg: BelegDb, _: Leser) -> BelegAntwort:
    return beleg


@app.get("/belege/{beleg_id}/datei")
def datei(beleg: BelegDb, _: Leser):
    endung = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}[beleg.dateityp]
    pfad = einstellungen().speicher / f"{beleg.sha256}{endung}"
    if not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(pfad, media_type=beleg.dateityp, headers={"X-Content-Type-Options": "nosniff"})


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


@app.get("/belege/{beleg_id}/protokoll")
def protokoll(beleg: BelegDb, db: Db, _: Leser) -> list[ProtokollAntwort]:
    return list(db.scalars(select(Protokoll).where(Protokoll.beleg_id == beleg.id).order_by(Protokoll.id)))


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


@app.get("/kennzahlen")
def kennzahlen(db: Db, _: Leser):
    anzahl = dict(db.execute(select(Beleg.status, func.count()).group_by(Beleg.status)).all())
    gesamt = sum(anzahl.values())
    berichtigt = db.scalar(select(func.count()).select_from(Beleg).where(Beleg.bearbeitet_von.is_not(None)))
    return {"gesamt": gesamt, "je_status": anzahl, "manuell_bearbeitet": berichtigt}
