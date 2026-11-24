from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import (
    anforderungen,
    anmeldung,
    belege,
    einstellungen,
    erstattungen,
    exporte,
    freigaben,
    karten,
    mandanten,
    partner,
    schnittstelle,
    zahlungen,
)
from .dienste.fehler import Konflikt, NichtGefunden, Ungueltig, Verboten
from .sicherheit import Db

STATISCH = Path(__file__).parent / "static"
RICHTLINIE = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' blob: data:",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    )
)
KOPFZEILEN = {
    "Content-Security-Policy": RICHTLINIE,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

app = FastAPI(title="Belegflow", version="2.0.0")
app.mount("/static", StaticFiles(directory=STATISCH), name="static")
for modul in (
    anmeldung,
    mandanten,
    belege,
    freigaben,
    zahlungen,
    exporte,
    erstattungen,
    anforderungen,
    karten,
    partner,
    einstellungen,
    schnittstelle,
):
    app.include_router(modul.router)


@app.middleware("http")
async def rahmen(anfrage: Request, weiter):
    if "%00" in anfrage.scope["query_string"].decode("latin-1"):
        return JSONResponse({"detail": "Zeichen ist nicht erlaubt"}, 422)
    antwort = await weiter(anfrage)
    oeffentlich = anfrage.url.path == "/" or anfrage.url.path.startswith("/static/")
    antwort.headers["Cache-Control"] = "no-cache" if oeffentlich else "no-store"
    return antwort


@app.exception_handler(Konflikt)
def bei_konflikt(_: Request, fehler: Konflikt):
    return JSONResponse({"detail": str(fehler)} | fehler.angaben, 409)


@app.exception_handler(Ungueltig)
def bei_ungueltig(_: Request, fehler: Ungueltig):
    return JSONResponse({"detail": str(fehler)}, 422)


@app.exception_handler(Verboten)
def bei_verboten(_: Request, fehler: Verboten):
    return JSONResponse({"detail": str(fehler)}, 403)


@app.exception_handler(NichtGefunden)
def bei_nicht_gefunden(_: Request, fehler: NichtGefunden):
    return JSONResponse({"detail": str(fehler)}, 404)


@app.exception_handler(RequestValidationError)
def bei_eingabefehler(_: Request, fehler: RequestValidationError):
    felder = [".".join(str(teil) for teil in f["loc"][1:]) for f in fehler.errors()]
    namen = ", ".join(dict.fromkeys(f for f in felder if f))
    return JSONResponse({"detail": f"Eingabe ist ungültig: {namen}" if namen else "Eingabe ist ungültig"}, 422)


@app.get("/", include_in_schema=False)
def oberflaeche():
    return FileResponse(STATISCH / "index.html", headers=KOPFZEILEN)


@app.get("/status", tags=["Status"])
def status(db: Db):
    db.execute(select(1))
    return {"status": "ok"}
