import hashlib
import io
from pathlib import Path
from threading import Lock

import pypdfium2

from ..config import einstellungen
from .fehler import Ungueltig

SIGNATUREN = {
    b"%PDF-": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
ENDUNGEN = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/xml": ".xml",
    "application/zip": ".zip",
    "text/csv": ".csv",
}
SPERRE = Lock()
GROESSE = 1400


def pruefe_groesse(inhalt: bytes) -> None:
    if not inhalt:
        raise Ungueltig("Datei ist leer")
    if len(inhalt) > einstellungen().max_mb * 1024 * 1024:
        raise Ungueltig(f"Datei ist größer als {einstellungen().max_mb} MB")


def erkenne_typ(inhalt: bytes) -> str:
    for signatur, typ in SIGNATUREN.items():
        if inhalt.startswith(signatur):
            return typ
    if inhalt.removeprefix(b"\xef\xbb\xbf").lstrip().startswith(b"<"):
        return "application/xml"
    raise Ungueltig("Nur PDF, PNG, JPEG und E-Rechnungen als XML sind erlaubt")


def pruefwert(inhalt: bytes) -> str:
    return hashlib.sha256(inhalt).hexdigest()


def pfad(wert: str, typ: str) -> Path:
    return einstellungen().speicher / wert[:2] / f"{wert}{ENDUNGEN[typ]}"


def ablegen(inhalt: bytes, typ: str) -> str:
    wert = pruefwert(inhalt)
    ziel = pfad(wert, typ)
    if not ziel.exists():
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(inhalt)
    return wert


def seite_als_png(datei: Path, seite: int) -> tuple[bytes, int]:
    with SPERRE:
        try:
            dokument = pypdfium2.PdfDocument(datei)
        except pypdfium2.PdfiumError as fehler:
            raise Ungueltig("PDF kann nicht angezeigt werden") from fehler
        try:
            seiten = len(dokument)
            if seite > seiten:
                raise Ungueltig("Seite gibt es nicht")
            blatt = dokument[seite - 1]
            breite, hoehe = blatt.get_size()
            bild = blatt.render(scale=GROESSE / max(breite, hoehe, 1)).to_pil()
        finally:
            dokument.close()
    puffer = io.BytesIO()
    bild.save(puffer, "PNG")
    return puffer.getvalue(), seiten
