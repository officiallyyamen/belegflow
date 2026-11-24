import { euro, h, hat, hole, icon, loesche, melde, ruf, sende, tag, versuche, z, zeit } from "../kern.js";
import { feld, fenster, frage, knopf, kopf, lies, personen, pille, reiter, sicher, stamm, tabelle, tat, zielwahl } from "../teile.js";

const ROLLEN = [["admin", "Verwaltung"], ["buchhaltung", "Buchhaltung"], ["freigabe", "Freigabe"], ["mitarbeit", "Mitarbeit"], ["einsicht", "Einsicht"]];
const rollenname = (r) => ROLLEN.find(([c]) => c === r)?.[1] || r;
const OBJEKTE = { beleg: "Beleg", erstattung: "Erstattung", anforderung: "Bestellung", partner: "Partner", karte: "Karte", mandant: "Mandant" };

const stammNeu = () => window.dispatchEvent(new Event("belegflow-stamm"));

async function liste(adr, spalten, { neu = null, leertext = "Noch nichts angelegt" } = {}) {
  const kasten = h("div.karte.eng");
  const zeige = async (d = null) => {
    const daten = Array.isArray(d) ? d : await hole(adr);
    kasten.replaceChildren(tabelle(spalten(zeige), daten, { leertext }));
    stammNeu();
  };
  await zeige();
  return [kasten, neu ? neu(zeige) : null];
}

const weg = (zeige, adr, titel) =>
  knopf("", async () => {
    if (await sicher(titel, "Das lässt sich nicht rückgängig machen.")) await zeige(await loesche(adr));
  }, { art: "rund leise", bild: "trash", titel: "Löschen" });

async function mandant() {
  const d = await hole("/mandant");
  const felder = [
    { name: "name", text: "Name", pflicht: true, breit: true },
    { name: "strasse", text: "Straße", breit: true },
    { name: "plz", text: "PLZ" },
    { name: "ort", text: "Ort" },
    { name: "uid", text: "Eigene UID" },
    { name: "iban", text: "IBAN für Zahlungen" },
    { name: "bic", text: "BIC" },
    { name: "erstattung_konto", text: "Verrechnungskonto Erstattungen" },
    { name: "rueckstellung_konto", text: "Konto Rückstellungen" },
    { name: "erinnerung_tage", text: "Erinnern nach Tagen", art: "zahl", zahlen: true },
    { name: "vier_augen", text: "Vier-Augen-Prinzip: wer bearbeitet, gibt nicht selbst frei", art: "haken", breit: true },
  ];
  const formular = h("form.karte.stapel", h("div.felder", felder.map((f) => feld(f, d[f.name]))), h("div.ende", h("button.knopf.haupt", { disabled: !hat("admin") }, "Speichern")));
  formular.onsubmit = (e) => {
    e.preventDefault();
    versuche(async () => {
      const w = lies(formular, felder);
      await sende("/mandant", Object.fromEntries(Object.entries(w).map(([n, wert]) => [n, wert === null && n !== "erinnerung_tage" ? "" : wert])), "PATCH");
      melde("Gespeichert");
    });
  };
  const neu = knopf("Neuer Mandant", async () => {
    const n = await frage("Neuer Mandant", [{ name: "name", text: "Name", pflicht: true }], {}, { speichern: (w) => ruf("/api/mandanten", "POST", w) });
    if (!n) return;
    z.ich = await ruf("/api/ich");
    z.stamm = null;
    location.hash = `#/${n.id}/einstellungen/mandant`;
  }, { bild: "plus" });
  return [formular, hat("admin") ? neu : null];
}

const leute = () =>
  liste(
    "/personen",
    (zeige) => [
      { titel: "Name", wert: (p) => h("div", h("strong", p.name), h("p.leise.klein", p.email)) },
      { titel: "Rollen", wert: (p) => h("div.reihe", p.rollen.map((r) => h("span.chip", rollenname(r)))) },
      { titel: "Abwesend", wert: (p) => (p.abwesend ? pille("warnung", p.abwesend_bis ? `bis ${tag(p.abwesend_bis)}` : "abwesend") : "") },
      {
        titel: "",
        wert: (p) =>
          hat("admin")
            ? h(
                "div.reihe",
                knopf("", async () => {
                  const w = await frage(p.name, [{ name: "rollen", text: "Rollen", art: "mehr", optionen: ROLLEN }], p, { speichern: (x) => sende(`/personen/${p.id}`, x, "PATCH") });
                  if (w) await zeige(w);
                }, { art: "rund leise", bild: "pencil-simple", titel: "Rollen ändern" }),
                weg(zeige, `/personen/${p.id}`, `${p.name} entfernen`),
              )
            : "",
      },
    ],
    {
      neu: (zeige) =>
        hat("admin")
          ? knopf("Person", async () => {
              const w = await frage("Person aufnehmen", [
                { name: "name", text: "Name", pflicht: true },
                { name: "email", text: "E-Mail", art: "email", pflicht: true },
                { name: "passwort", text: "Startpasswort, mindestens 12 Zeichen", art: "password", hinweis: "Nur bei neuen Personen nötig" },
                { name: "rollen", text: "Rollen", art: "mehr", optionen: ROLLEN },
              ], { rollen: ["mitarbeit"] }, { speichern: (x) => sende("/personen", x) });
              if (w) await zeige(w);
            }, { art: "haupt", bild: "user-plus" })
          : null,
    },
  );

const teams = () => {
  const bearbeite = async (zeige, t = null) => {
    const optionen = z.stamm.personen.filter((p) => p.rollen.some((r) => ["freigabe", "admin"].includes(r))).map((p) => [p.id, p.name]);
    const w = await frage("Team", [{ name: "name", text: "Name", pflicht: true }, { name: "mitglieder", text: "Mitglieder", art: "mehr", zahlen: true, optionen }], t || {}, { speichern: (x) => sende(t ? `/teams/${t.id}` : "/teams", x, t ? "PUT" : "POST") });
    if (w) await zeige(w);
  };
  return liste(
    "/teams",
    (zeige) => [
      { titel: "Name", wert: (t) => h("strong", t.name) },
      { titel: "Mitglieder", wert: (t) => t.mitglieder.map((n) => z.stamm.personen.find((p) => p.id === n)?.name).filter(Boolean).join(", ") },
      { titel: "", wert: (t) => (hat("admin") ? h("div.reihe", knopf("", () => bearbeite(zeige, t), { art: "rund leise", bild: "pencil-simple", titel: "Ändern" }), weg(zeige, `/teams/${t.id}`, "Team löschen")) : "") },
    ],
    { neu: (zeige) => (hat("admin") ? knopf("Team", () => bearbeite(zeige), { art: "haupt", bild: "plus" }) : null) },
  );
};

const partnerliste = () => (z.stamm.partner || []).map((p) => [p.id, p.name]);

const workflows = () => {
  const beschreibe = (b) => [b.art ? OBJEKTE[b.art] : "Alle", b.ab ? `ab ${euro(b.ab)}` : "", b.bis ? `bis ${euro(b.bis)}` : "", b.kostenstelle ? `KSt ${b.kostenstelle}` : "", b.partner_id ? partnerliste().find(([n]) => n === b.partner_id)?.[1] : ""].filter(Boolean).join(", ");
  const ziel = (s) => (s.art === "team" ? `Team ${z.stamm.teams.find((t) => t.id === s.id)?.name || ""}` : z.stamm.personen.find((p) => p.id === s.id)?.name || "?");
  const bearbeite = async (zeige, w = null) => {
    const wahl = zielwahl(w ? w.schritte.map((s) => `${s.art}-${s.id}`) : [""]);
    const b = w?.bedingung || {};
    const d = await frage("Workflow", [
      { name: "name", text: "Name", pflicht: true },
      { name: "rang", text: "Rang (kleiner gewinnt)", art: "zahl", zahlen: true, pflicht: true },
      { name: "art", text: "Gilt für", art: "wahl", leer: "Alles", optionen: [["beleg", "Rechnungen"], ["erstattung", "Erstattungen"], ["anforderung", "Bestellungen"]] },
      { name: "kostenstelle", text: "Kostenstelle", art: "wahl", leer: "Alle", optionen: stamm("kostenstelle") },
      { name: "ab", text: "Ab Betrag", art: "geld" },
      { name: "bis", text: "Bis Betrag", art: "geld" },
      { name: "partner_id", text: "Partner", art: "wahl", leer: "Alle", zahlen: true, optionen: partnerliste(), breit: true },
      { knoten: wahl.knoten },
    ], { name: w?.name, rang: w?.rang ?? 10, ...b }, {
      breit: true,
      speichern: ({ name, rang, ...bedingung }) => sende(w ? `/workflows/${w.id}` : "/workflows", { name, rang, bedingung, schritte: wahl.werte() }, w ? "PUT" : "POST"),
    });
    if (d) await zeige(d);
  };
  return liste(
    "/workflows",
    (zeige) => [
      { titel: "Rang", wert: (w) => String(w.rang) },
      { titel: "Name", wert: (w) => h("strong", w.name) },
      { titel: "Bedingung", wert: (w) => beschreibe(w.bedingung) },
      { titel: "Schritte", wert: (w) => h("div.reihe", w.schritte.map((s, i) => [i ? icon("caret-right") : null, h("span.chip", ziel(s))])) },
      { titel: "", wert: (w) => (hat("admin") ? h("div.reihe", knopf("", () => bearbeite(zeige, w), { art: "rund leise", bild: "pencil-simple", titel: "Ändern" }), weg(zeige, `/workflows/${w.id}`, "Workflow löschen")) : "") },
    ],
    { neu: (zeige) => (hat("admin") ? knopf("Workflow", () => bearbeite(zeige), { art: "haupt", bild: "plus" }) : null) },
  );
};

const AKTIONEN = [["vorschlagen", "Vorschlagen"], ["anfordern", "Freigabe anfordern"], ["freigeben", "Automatisch freigeben"]];
const automatik = () => {
  const bearbeite = async (zeige, a = null) => {
    const d = await frage("Regel", [
      { name: "name", text: "Name", pflicht: true, breit: true },
      { name: "aktion", text: "Aktion", art: "wahl", pflicht: true, optionen: AKTIONEN },
      { name: "max_brutto", text: "Bis brutto", art: "geld", pflicht: true },
      { name: "gleiche", text: "Nach so vielen gleichen Buchungen", art: "zahl", zahlen: true, pflicht: true },
      { name: "partner_id", text: "Partner", art: "wahl", leer: "Alle", zahlen: true, optionen: partnerliste() },
      { name: "workflow_id", text: "Workflow", art: "wahl", leer: "Passender", zahlen: true, optionen: z.stamm.workflows.map((w) => [w.id, w.name]) },
      { name: "aktiv", text: "Aktiv", art: "haken" },
    ], a || { aktion: "vorschlagen", gleiche: 3, aktiv: true }, { breit: true, hinweis: "Gilt nur für Belege ohne Fehler. Jede Anwendung steht im Verlauf.", speichern: (w) => sende(a ? `/automatiken/${a.id}` : "/automatiken", w, a ? "PUT" : "POST") });
    if (d) await zeige(d);
  };
  return liste(
    "/automatiken",
    (zeige) => [
      { titel: "Name", wert: (a) => h("strong", a.name) },
      { titel: "Aktion", wert: (a) => AKTIONEN.find(([c]) => c === a.aktion)[1] },
      { titel: "Bedingung", wert: (a) => [`bis ${euro(a.max_brutto)}`, `${a.gleiche} gleiche`, partnerliste().find(([n]) => n === a.partner_id)?.[1]].filter(Boolean).join(", ") },
      { titel: "", wert: (a) => pille(a.aktiv ? "aktiv" : "gesperrt", a.aktiv ? "Aktiv" : "Aus") },
      { titel: "", wert: (a) => (hat("admin") ? h("div.reihe", knopf("", () => bearbeite(zeige, a), { art: "rund leise", bild: "pencil-simple", titel: "Ändern" }), weg(zeige, `/automatiken/${a.id}`, "Regel löschen")) : "") },
    ],
    { neu: (zeige) => (hat("admin") ? knopf("Regel", () => bearbeite(zeige), { art: "haupt", bild: "plus" }) : null) },
  );
};

const STAMMNAMEN = { konto: "Konto", kostenstelle: "Kostenstelle", kostentraeger: "Kostenträger", steuerschluessel: "Steuerschlüssel", vertragstyp: "Vertragstyp" };
const stammdaten = () =>
  liste(
    "/stammwerte",
    (zeige) => [
      { titel: "Art", wert: (s) => STAMMNAMEN[s.art] },
      { titel: "Code", wert: (s) => h("strong", s.code) },
      { titel: "Name", wert: (s) => s.name },
      { titel: "", wert: (s) => (hat("buchhaltung", "admin") ? weg(() => zeige(), `/stammwerte/${s.id}`, `${s.code} löschen`) : "") },
    ],
    {
      neu: (zeige) =>
        hat("buchhaltung", "admin")
          ? knopf("Eintrag", async () => {
              const w = await frage("Stammdaten", [{ name: "art", text: "Art", art: "wahl", pflicht: true, optionen: Object.entries(STAMMNAMEN) }, { name: "code", text: "Code", pflicht: true }, { name: "name", text: "Name", pflicht: true }], {}, { speichern: (x) => sende("/stammwerte", x) });
              if (w) await zeige();
            }, { art: "haupt", bild: "plus" })
          : null,
    },
  );

const sperren = () =>
  liste(
    "/sperren",
    (zeige) => [
      { titel: "Art", wert: (s) => (s.art === "iban" ? "IBAN" : "Absender") },
      { titel: "Wert", wert: (s) => h("strong", s.wert) },
      { titel: "Grund", wert: (s) => s.grund },
      { titel: "", wert: (s) => (hat("admin") ? weg(zeige, `/sperren/${s.id}`, "Sperre aufheben") : "") },
    ],
    {
      leertext: "Nichts gesperrt",
      neu: (zeige) =>
        hat("buchhaltung", "admin")
          ? knopf("Sperre", async () => {
              const w = await frage("Sperren", [{ name: "art", text: "Art", art: "wahl", pflicht: true, optionen: [["iban", "IBAN"], ["absender", "E-Mail-Absender oder Domain"]] }, { name: "wert", text: "Wert", pflicht: true }, { name: "grund", text: "Grund", breit: true }], {}, { speichern: (x) => sende("/sperren", { ...x, grund: x.grund || "" }) });
              if (w) await zeige(w);
            }, { art: "haupt", bild: "lock" })
          : null,
    },
  );

const zugaenge = () =>
  liste(
    "/zugaenge",
    (zeige) => [
      { titel: "Name", wert: (s) => h("strong", s.name) },
      { titel: "Rollen", wert: (s) => s.rollen.join(", ") },
      { titel: "Angelegt", wert: (s) => zeit(s.erstellt_am) },
      { titel: "", wert: (s) => weg(zeige, `/zugaenge/${s.id}`, "Zugang entziehen") },
    ],
    {
      neu: (zeige) =>
        knopf("Zugang", async () => {
          const d = await frage("Zugang für n8n oder andere Programme", [{ name: "name", text: "Name", pflicht: true }, { name: "rollen", text: "Darf", art: "mehr", optionen: [["eingang", "Belege einreichen"], ["schnittstelle", "Mitteilungen, Buchungen und Stammdaten"]] }], {}, { speichern: (x) => sende("/zugaenge", x) });
          if (!d?.token) return;
          fenster("Token", h("div.stapel", h("p", "Dieser Token wird nur jetzt angezeigt."), h("code.token", d.token), knopf("Kopieren", async () => { await navigator.clipboard.writeText(d.token); melde("Kopiert"); }, { bild: "copy" })));
          await zeige(d.zugaenge);
        }, { art: "haupt", bild: "key" }),
    },
  );

async function protokoll() {
  const kasten = h("div.karte.eng");
  let alle = await hole("/protokoll");
  const zeige = () =>
    kasten.replaceChildren(
      tabelle(
        [
          { titel: "Wann", wert: (p) => zeit(p.zeitpunkt) },
          { titel: "Wer", wert: (p) => h("strong", p.wer) },
          { titel: "Was", wert: (p) => `${tat(p.aktion)}` },
          { titel: "Objekt", wert: (p) => `${OBJEKTE[p.objekt_art] || p.objekt_art} ${p.objekt_id}` },
          { titel: "Einzelheiten", wert: (p) => h("span.leise.klein.abschnitt", JSON.stringify(p.details)), klasse: "breitab" },
        ],
        alle,
      ),
      h("footer.fuss", knopf("Ältere laden", async () => { alle = [...alle, ...(await hole("/protokoll", { vor: alle.at(-1).id }))]; zeige(); })),
    );
  zeige();
  const pruefe = knopf("Kette prüfen", async () => {
    const d = await hole("/protokoll/pruefung");
    melde(d.gueltig ? "Das Protokoll ist unverändert" : `Veränderung bei Eintrag ${d.fehler_bei}`, !d.gueltig);
  }, { art: "haupt", bild: "shield-check" });
  return [kasten, pruefe];
}

const SEITEN = { mandant: ["Mandant", mandant], personen: ["Personen", leute], teams: ["Teams", teams], workflows: ["Workflows", workflows], automatik: ["Automatik", automatik], stammdaten: ["Stammdaten", stammdaten], sperren: ["Sperrliste", sperren], zugaenge: ["Zugänge", zugaenge], protokoll: ["Protokoll", protokoll] };

export async function seite([welche = "mandant"]) {
  const [inhalt, rechts] = await SEITEN[welche][1]();
  return h("div.seite", kopf("Einstellungen", rechts), reiter(Object.entries(SEITEN).filter(([s]) => s !== "zugaenge" || hat("admin")).map(([s, [t]]) => [`einstellungen/${s}`, t]), `einstellungen/${welche}`), inhalt);
}

export async function profil() {
  const felder = [
    { name: "iban", text: "IBAN für Erstattungen", breit: true },
    { name: "abwesend_von", text: "Abwesend von", art: "date" },
    { name: "abwesend_bis", text: "Abwesend bis", art: "date" },
    { name: "vertretung_id", text: "Vertretung", art: "wahl", zahlen: true, optionen: personen().filter(([n]) => n !== z.ich.id), breit: true },
  ];
  const formular = h("form.karte.stapel", h("h2", "Vertretung und Auszahlung"), h("div.felder", felder.map((f) => feld(f, z.ich[f.name]))), h("div.ende", h("button.knopf.haupt", "Speichern")));
  formular.onsubmit = (e) => {
    e.preventDefault();
    versuche(async () => {
      z.ich = await ruf("/api/ich", "PATCH", lies(formular, felder));
      stammNeu();
      melde("Gespeichert");
    });
  };
  const neu = [{ name: "alt", text: "Bisheriges Passwort", art: "password", pflicht: true }, { name: "neu", text: "Neues Passwort, mindestens 12 Zeichen", art: "password", pflicht: true }];
  return h(
    "div.seite.schmal",
    kopf(z.ich.name, knopf("Passwort ändern", async () => { if (await frage("Passwort ändern", neu, {}, { speichern: (w) => ruf("/api/ich/passwort", "POST", w) })) melde("Passwort geändert"); }, { bild: "key" })),
    h("div.karte", h("p.leise", z.ich.email), h("div.reihe", z.stamm.rollen.map((r) => h("span.chip", rollenname(r))))),
    formular,
  );
}
