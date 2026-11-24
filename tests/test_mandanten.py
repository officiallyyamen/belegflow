from datetime import date

import pytest

from app.modelle import Anforderung, Erstattung, Karte, Transaktion

from .conftest import rechnung


@pytest.fixture
def fremd(haus):
    beleg = haus.kontiert(rechnung("F-1"), "boris", mandant="b")
    with haus.db() as db:
        m, p = haus.m["b"], haus.p["boris"]
        karte = Karte(mandant_id=m, inhaber_id=p, name="K", limit_monat=100, letzte4="1111", status="aktiv")
        antrag = Erstattung(mandant_id=m, benutzer_id=p, titel="Fremd", status="pruefung")
        bestellung = Anforderung(mandant_id=m, benutzer_id=p, lieferant="X", titel="Y", netto=10, status="freigegeben")
        db.add_all([karte, antrag, bestellung])
        db.flush()
        buchung = Transaktion(mandant_id=m, karte_id=karte.id, kennung="1", datum=date.today(), haendler="H", betrag=1)
        db.add(buchung)
        db.commit()
        return {
            "beleg": beleg,
            "karte": karte.id,
            "erstattung": antrag.id,
            "anforderung": bestellung.id,
            "buchung": buchung.id,
        }


def test_mandant_ist_fuer_andere_unsichtbar(haus):
    for pfad in ("/eingang", "/archiv", "/stammdaten", "/zaehler", "/uebersicht", "/partner", "/protokoll", "/personen"):
        assert haus.rufe("anna", "GET", pfad, "b").status_code == 404
    namen = [m["name"] for m in haus.rufe("anna", "GET", "/api/mandanten", erwarte=200).json()]
    assert namen == ["Muster Holding GmbH"]


@pytest.mark.parametrize(
    "pfad",
    [
        "/belege/{beleg}",
        "/belege/{beleg}/datei",
        "/belege/{beleg}/bild",
        "/erstattungen/{erstattung}",
        "/erstattungen/{erstattung}/pdf",
        "/anforderungen/{anforderung}",
        "/anforderungen/{anforderung}/pdf",
        "/karten/{karte}",
    ],
)
def test_fremde_nummern_lassen_sich_nicht_lesen(haus, fremd, pfad):
    for wer in ("anna", "ben", "admin", "eva"):
        assert haus.rufe(wer, "GET", pfad.format(**fremd)).status_code == 404


def test_fremde_nummern_lassen_sich_nicht_aendern(haus, fremd):
    eigen = haus.kontiert(rechnung())
    for wer, methode, pfad, daten in (
        ("anna", "PATCH", f"/belege/{fremd['beleg']}", {"konto": "1"}),
        ("anna", "POST", f"/belege/{fremd['beleg']}/kommentar", {"text": "x"}),
        ("anna", "POST", f"/belege/{fremd['beleg']}/aktion", {"aktion": "papierkorb"}),
        ("ben", "POST", f"/freigaben/beleg/{fremd['beleg']}/sofort", {}),
        ("ben", "POST", f"/freigaben/erstattung/{fremd['erstattung']}/sofort", {}),
        ("anna", "POST", f"/belege/{eigen}/anhaengen", {"ziel": fremd["beleg"]}),
        ("anna", "POST", f"/belege/{eigen}/verknuepfung", {"art": "beleg", "id": fremd["beleg"]}),
        ("anna", "POST", f"/belege/{eigen}/verknuepfung", {"art": "anforderung", "id": fremd["anforderung"]}),
        ("anna", "POST", f"/transaktionen/{fremd['buchung']}/beleg", {"beleg_id": eigen}),
        ("anna", "POST", f"/erstattungen/{fremd['erstattung']}/zurueckgeben", {"grund": "nein"}),
        ("anna", "PATCH", f"/karten/{fremd['karte']}", {"status": "gesperrt"}),
    ):
        assert haus.rufe(wer, methode, pfad, json=daten).status_code == 404, pfad
    antwort = haus.rufe(
        "anna", "POST", "/belege/sammel", erwarte=200, json={"nummern": [fremd["beleg"]], "aktion": "papierkorb"}
    )
    assert antwort.json()["fertig"] == []
    lauf = {"posten": [{"art": "beleg", "id": fremd["beleg"]}], "ausfuehrung": date.today().isoformat()}
    assert haus.rufe("anna", "POST", "/zahlungen", json=lauf).status_code == 409


def test_fremde_verweise_werden_abgelehnt(haus):
    fremder_partner = haus.partner(mandant="b")
    nummer = haus.lade(rechnung())
    haus.aendere(nummer, partner_id=fremder_partner, erwarte=422)
    haus.fordere(haus.kontiert(rechnung("PM-2")), "boris", erwarte=422)
    regel = {"name": "Regel", "aktion": "freigeben", "max_brutto": "100", "partner_id": fremder_partner}
    haus.rufe("admin", "POST", "/automatiken", erwarte=404, json=regel)
    sicht = {"eingeschraenkt": True, "personen": [haus.p["boris"]]}
    haus.rufe("anna", "PUT", f"/belege/{nummer}/sichtbarkeit", erwarte=422, json=sicht)


def test_token_gilt_nur_fuer_seinen_mandanten(haus):
    assert haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/mitteilungen", "b").status_code == 404
    assert haus.rufe("bf_schnittstelle", "GET", "/schnittstelle/mitteilungen").status_code == 200
    assert haus.rufe("bf_falsch", "GET", "/schnittstelle/mitteilungen").status_code == 401


def test_token_ersetzt_keine_person(haus):
    for pfad in ("/eingang", "/stammdaten", "/partner", "/zugaenge", "/exporte/wartend"):
        assert haus.rufe("bf_schnittstelle", "GET", pfad).status_code == 403
        assert haus.rufe("bf_eingang", "GET", pfad).status_code == 403


@pytest.mark.parametrize(
    ("wer", "methode", "pfad"),
    [
        ("dora", "GET", "/partner"),
        ("dora", "GET", "/exporte/wartend"),
        ("dora", "GET", "/zahlungen/offen"),
        ("dora", "GET", "/protokoll"),
        ("dora", "POST", "/exporte"),
        ("dora", "POST", "/zahlungen"),
        ("ben", "POST", "/zahlungen"),
        ("eva", "POST", "/zahlungen"),
        ("eva", "POST", "/exporte"),
        ("eva", "POST", "/exporte/stammdaten"),
        ("anna", "PATCH", "/mandant"),
        ("anna", "POST", "/personen"),
        ("anna", "POST", "/zugaenge"),
        ("anna", "GET", "/zugaenge"),
        ("anna", "POST", "/workflows"),
        ("eva", "POST", "/partner"),
        ("ben", "POST", "/stammwerte"),
    ],
)
def test_rollen_begrenzen_den_zugriff(haus, wer, methode, pfad):
    antwort = haus.rufe(wer, methode, pfad, json={} if methode != "GET" else None)
    assert antwort.status_code in (403, 422)
    if antwort.status_code == 422:
        pytest.fail(f"{wer} durfte {pfad} bis zur Eingabeprüfung aufrufen")


def test_einsicht_darf_lesen_aber_nicht_aendern(haus):
    nummer = haus.kontiert(rechnung())
    assert haus.beleg(nummer, "eva")["darf_aendern"] is False
    haus.aendere(nummer, "eva", erwarte=403, konto="1")
    haus.rufe("eva", "POST", f"/belege/{nummer}/aktion", erwarte=403, json={"aktion": "papierkorb"})
    haus.sofort(nummer, "eva", erwarte=403)


def test_mitarbeit_sieht_nur_eigene_belege(haus):
    eigene = haus.lade(rechnung("D-1"), "dora")
    fremde = haus.lade(rechnung("RB-77"), "anna")
    assert haus.rufe("dora", "GET", f"/belege/{eigene}").status_code == 200
    assert haus.rufe("dora", "GET", f"/belege/{fremde}").status_code == 404
    liste = haus.rufe("dora", "GET", "/eingang", erwarte=200).json()
    assert [b["id"] for b in liste["eintraege"]] == [eigene]
    assert haus.rufe("dora", "GET", "/suche?q=RB-77", erwarte=200).json()["belege"] == []


def test_neuer_mandant_nur_durch_verwaltung(haus):
    assert haus.rufe("anna", "POST", "/api/mandanten", json={"name": "Neu GmbH"}).status_code == 409
    neu = haus.rufe("admin", "POST", "/api/mandanten", erwarte=201, json={"name": "Neu GmbH"}).json()
    assert haus.rufe("admin", "GET", f"/api/m/{neu['id']}/stammdaten").status_code == 200


def test_letzte_verwaltung_bleibt(haus):
    haus.rufe("admin", "PATCH", f"/personen/{haus.p['admin']}", erwarte=409, json={"rollen": ["buchhaltung"]})
    haus.rufe("admin", "DELETE", f"/personen/{haus.p['admin']}", erwarte=409)


def test_personen_verwalten(haus):
    neu = {"name": "Nina Neu", "email": "Nina@Test.example", "rollen": ["mitarbeit"]}
    haus.rufe("admin", "POST", "/personen", erwarte=422, json=neu)
    liste = haus.rufe("admin", "POST", "/personen", erwarte=201, json=neu | {"passwort": "Startpasswort-1"}).json()
    nina = next(p for p in liste if p["email"] == "nina@test.example")
    haus.rufe("admin", "POST", "/personen", erwarte=409, json=neu)
    haus.rufe("admin", "PATCH", f"/personen/{nina['id']}", erwarte=200, json={"rollen": ["freigabe"]})
    haus.rufe("admin", "DELETE", f"/personen/{nina['id']}", erwarte=200)


def test_bestehende_person_behaelt_ihr_passwort(haus):
    daten = {
        "name": "Anderer Name",
        "email": "boris@test.example",
        "rollen": ["mitarbeit"],
        "passwort": "Uebernahme-Versuch",
    }
    haus.rufe("admin", "POST", "/personen", erwarte=201, json=daten)
    antwort = haus.client.post(
        "/api/anmeldung",
        json={"email": "boris@test.example", "passwort": "Uebernahme-Versuch"},
        headers={"X-Belegflow": "1"},
    )
    assert antwort.status_code == 401
    assert haus.rufe("boris", "GET", "/api/ich", erwarte=200).json()["name"] == "Boris"
