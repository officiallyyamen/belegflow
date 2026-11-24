from datetime import date, timedelta
from decimal import Decimal

from defusedxml.ElementTree import fromstring

from app.demo.dateien import Firma
from app.dienste.zahlung import NAMENSRAUM, sepa_text
from app.modelle import Mandant

from .conftest import EIGEN, PAPIER, PUTZ, rechnung

NS = {"p": NAMENSRAUM}


def lauf(haus, posten, tag=None, wer="anna", erwarte=201):
    daten = {"posten": posten, "ausfuehrung": (tag or date.today()).isoformat()}
    return haus.rufe(wer, "POST", "/zahlungen", erwarte=erwarte, json=daten).json()


def xml(haus, nummer):
    antwort = haus.rufe("anna", "GET", f"/zahlungen/{nummer}/datei", erwarte=200)
    assert antwort.headers["content-type"].startswith("application/xml")
    return fromstring(antwort.content)


def test_sepa_datei(haus):
    eins, zwei = haus.frei(rechnung("PM-1")), haus.frei(rechnung("RB-1", "250", wer=PUTZ))
    offen = haus.rufe("anna", "GET", "/zahlungen/offen", erwarte=200).json()
    assert {p["id"] for p in offen} == {eins, zwei} and all(p["hindernis"] is None for p in offen)
    ergebnis = lauf(haus, [{"art": "beleg", "id": eins}, {"art": "beleg", "id": zwei}])
    assert ergebnis["summe"] == "900.00"
    wurzel = xml(haus, ergebnis["id"])
    kopf = wurzel.find("p:CstmrCdtTrfInitn/p:GrpHdr", NS)
    assert kopf.findtext("p:NbOfTxs", None, NS) == "2" and kopf.findtext("p:CtrlSum", None, NS) == "900.00"
    block = wurzel.find("p:CstmrCdtTrfInitn/p:PmtInf", NS)
    assert block.findtext("p:DbtrAcct/p:Id/p:IBAN", None, NS) == EIGEN.iban
    assert block.findtext("p:ReqdExctnDt/p:Dt", None, NS) == date.today().isoformat()
    ueberweisungen = block.findall("p:CdtTrfTxInf", NS)
    assert [u.findtext("p:CdtrAcct/p:Id/p:IBAN", None, NS) for u in ueberweisungen] == [PAPIER.iban, PUTZ.iban]
    assert ueberweisungen[0].find("p:Amt/p:InstdAmt", NS).get("Ccy") == "EUR"
    assert ueberweisungen[0].findtext("p:RmtInf/p:Ustrd", None, NS) == "Rechnung PM-1"


def test_nichts_wird_doppelt_bezahlt(haus):
    nummer = haus.frei(rechnung())
    lauf(haus, [{"art": "beleg", "id": nummer}])
    lauf(haus, [{"art": "beleg", "id": nummer}], erwarte=409)
    zweiter = haus.frei(rechnung("PM-2"))
    lauf(haus, [{"art": "beleg", "id": zweiter}] * 2, erwarte=409)
    assert haus.rufe("anna", "GET", "/zahlungen/offen").json()[0]["id"] == zweiter


def test_nur_freigegebene_belege(haus):
    nummer = haus.kontiert(rechnung())
    lauf(haus, [{"art": "beleg", "id": nummer}], erwarte=409)
    haus.fordere(nummer, "ben")
    lauf(haus, [{"art": "beleg", "id": nummer}], erwarte=409)


def test_skonto(haus):
    nummer = haus.frei(rechnung(skonto=(2, 14)))
    eintrag = haus.rufe("anna", "GET", "/zahlungen/offen").json()[0]
    assert eintrag["skonto_betrag"] == "588.00"
    spaet = date.today() + timedelta(days=5)
    lauf(haus, [{"art": "beleg", "id": nummer, "skonto": True}], spaet, erwarte=409)
    assert lauf(haus, [{"art": "beleg", "id": nummer, "skonto": True}])["summe"] == "588.00"


def test_skonto_nicht_moeglich(haus):
    nummer = haus.frei(rechnung())
    lauf(haus, [{"art": "beleg", "id": nummer, "skonto": True}], erwarte=409)


def test_hindernisse(haus):
    ohne = Firma(PUTZ.name, PUTZ.strasse, PUTZ.plz, PUTZ.ort, PUTZ.uid, None)
    nummer = haus.frei(rechnung("RB-1", wer=ohne))
    assert haus.rufe("anna", "GET", "/zahlungen/offen").json()[0]["hindernis"] == "IBAN fehlt oder ist ungültig"
    lauf(haus, [{"art": "beleg", "id": nummer}], erwarte=409)
    zweiter = haus.frei(rechnung("PM-1"))
    lauf(haus, [{"art": "beleg", "id": zweiter}], date.today() - timedelta(days=1), erwarte=422)
    with haus.db() as db:
        db.get(Mandant, haus.m["a"]).iban = None
        db.commit()
    lauf(haus, [{"art": "beleg", "id": zweiter}], erwarte=409)


def test_ohne_zahlung_markieren(haus):
    nummer = haus.frei(rechnung())
    aktion = {"aktion": "keine_zahlung", "grund": "bar bezahlt"}
    haus.rufe("lea", "POST", f"/belege/{nummer}/aktion", erwarte=403, json=aktion)
    haus.rufe("anna", "POST", f"/belege/{nummer}/aktion", erwarte=200, json=aktion)
    assert haus.rufe("anna", "GET", "/zahlungen/offen").json() == []


def test_datei_nur_fuer_den_mandanten(haus):
    nummer = lauf(haus, [{"art": "beleg", "id": haus.frei(rechnung())}])["id"]
    assert haus.rufe("boris", "GET", f"/zahlungen/{nummer}/datei", "b").status_code == 404
    assert haus.rufe("ben", "GET", f"/zahlungen/{nummer}/datei").status_code == 403


def test_sepa_zeichen():
    assert sepa_text("Müller & Söhne <GmbH> €", 70) == "Mueller + Soehne GmbH EUR"
    assert sepa_text("", 70) == "NOTPROVIDED"
    assert len(sepa_text("x" * 200, 35)) == 35


def test_summe_bleibt_genau(haus):
    posten = [{"art": "beleg", "id": haus.frei(rechnung(f"PM-{n}", "0.10"))} for n in range(3)]
    assert Decimal(lauf(haus, posten)["summe"]) == Decimal("0.36")
