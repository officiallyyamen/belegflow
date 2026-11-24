import io
from pathlib import Path
from threading import Lock

import pypdfium2

SPERRE = Lock()
BREITE = 1400


class BildFehler(Exception):
    pass


def seite_als_png(pfad: Path, seite: int) -> tuple[bytes, int]:
    with SPERRE:
        try:
            dokument = pypdfium2.PdfDocument(pfad)
        except pypdfium2.PdfiumError as fehler:
            raise BildFehler("PDF kann nicht angezeigt werden") from fehler
        try:
            seiten = len(dokument)
            if seite > seiten:
                raise BildFehler("Seite gibt es nicht")
            blatt = dokument[seite - 1]
            breite, hoehe = blatt.get_size()
            bild = blatt.render(scale=BREITE / max(breite, hoehe, 1)).to_pil()
        finally:
            dokument.close()
    puffer = io.BytesIO()
    bild.save(puffer, "PNG")
    return puffer.getvalue(), seiten
