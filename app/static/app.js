const wurzel = document.getElementById("app");
const STATUS = {
  pruefen: ["Prüfen", "pencil-simple"],
  bereit: ["Freigabe offen", "clock"],
  freigegeben: ["Freigegeben", "check"],
  exportiert: ["Exportiert", "download-simple"],
  abgelehnt: ["Abgelehnt", "x"],
};
const SEITEN = [
  ["uebersicht", "Übersicht", "squares-four"],
  ["aufgaben", "Aufgaben", "list-checks"],
  ["freigabe", "Freigabe", "check-circle"],
  ["uebertragung", "Übertragung", "paper-plane-tilt"],
  ["belege", "Belege", "files"],
  ["auswertung", "Auswertung", "chart-bar"],
  ["regelwerk", "Regelwerk", "scales"],
  ["lieferanten", "Lieferanten", "buildings"],
  ["benutzer", "Benutzer", "users"],
  ["papierkorb", "Papierkorb", "trash"],
];
const GELD = ["netto", "ust", "brutto"];
const OFFEN = ["pruefen", "bereit"];
const AKTIONEN = {
  erfasst: "hat den Beleg erfasst",
  korrigiert: "hat Felder geändert",
  freigegeben: "hat freigegeben",
  abgelehnt: "hat abgelehnt",
  exportiert: "hat exportiert",
  iban_bestaetigt: "hat die neue IBAN bestätigt",
  kommentar: "hat kommentiert",
};
let token = sessionStorage.getItem("belegflow") || "";
let ich = null;
let bildAdresse = null;
let lauf = 0;

function farbe(neu) {
  document.documentElement.dataset.farbe = neu;
  try {
    localStorage.setItem("belegflow-farbe", neu);
  } catch {
    return;
  }
}

try {
  document.documentElement.dataset.farbe = localStorage.getItem("belegflow-farbe") || "hell";
} catch {
  document.documentElement.dataset.farbe = "hell";
}

function el(art, eigenschaften = {}, ...kinder) {
  const knoten = Object.assign(document.createElement(art), eigenschaften);
  knoten.append(...kinder.filter((kind) => kind !== null && kind !== undefined));
  return knoten;
}

function svg(art, eigenschaften = {}, ...kinder) {
  const knoten = document.createElementNS("http://www.w3.org/2000/svg", art);
  for (const [name, wert] of Object.entries(eigenschaften)) knoten.setAttribute(name, wert);
  knoten.append(...kinder);
  return knoten;
}

function icon(name) {
  return svg("svg", { class: "icon", "aria-hidden": "true" }, svg("use", { href: `/static/icons.svg#${name}` }));
}

function melde(text, fehler = false) {
  document.querySelector(".meldung")?.remove();
  const box = el("div", { className: "meldung" + (fehler ? " fehler" : ""), textContent: text });
  box.setAttribute("role", fehler ? "alert" : "status");
  document.body.append(box);
  setTimeout(() => box.remove(), fehler ? 6000 : 3000);
}

async function api(pfad, methode = "GET", inhalt = null) {
  const optionen = { method: methode, headers: { Authorization: `Bearer ${token}` } };
  if (inhalt instanceof FormData) optionen.body = inhalt;
  else if (inhalt) {
    optionen.body = JSON.stringify(inhalt);
    optionen.headers["Content-Type"] = "application/json";
  }
  const antwort = await fetch(pfad, optionen);
  if (!antwort.ok) {
    const daten = await antwort.json().catch(() => ({}));
    const fehler = new Error(typeof daten.detail === "string" ? daten.detail : "Eingabe ist ungültig");
    fehler.status = antwort.status;
    throw fehler;
  }
  return antwort;
}

const holen = async (pfad) => (await api(pfad)).json();
const darf = (rolle) => ich?.rollen.includes(rolle);
const euro = (wert) => (wert === null ? "" : Number(wert).toLocaleString("de-AT", { style: "currency", currency: "EUR" }));
const tag = (wert) => (wert ? new Date(`${wert}T00:00`).toLocaleDateString("de-AT") : "");
const zeit = (wert) => new Date(wert).toLocaleString("de-AT", { dateStyle: "short", timeStyle: "short" });
const pille = (status) => el("span", { className: `pille s-${status}` }, icon(STATUS[status][1]), STATUS[status][0]);

async function versuche(aufgabe) {
  try {
    await aufgabe();
  } catch (fehler) {
    if (fehler.status === 401 && ich) abmelden();
    melde(fehler.message, true);
  }
}

function knopf(text, aufgabe, { klasse = "", symbol = null, gesperrt = false, titel = "" } = {}) {
  const k = el("button", { type: "button", className: `knopf ${klasse}`, disabled: gesperrt, onclick: () => versuche(aufgabe) });
  if (symbol) k.append(icon(symbol));
  if (text) k.append(text);
  if (titel) {
    k.title = titel;
    k.setAttribute("aria-label", titel);
  }
  return k;
}

function frage(titel, hinweis) {
  return new Promise((fertig) => {
    const feld = el("textarea", { required: true, minLength: 3, maxLength: 500 });
    feld.setAttribute("aria-label", hinweis);
    const abbruch = el("button", { type: "button", className: "knopf", textContent: "Abbrechen" });
    const formular = el(
      "form",
      { method: "dialog" },
      el("h2", { textContent: titel }),
      el("p", { className: "leise", textContent: hinweis }),
      feld,
      el("div", { className: "ende" }, abbruch, el("button", { className: "knopf haupt", textContent: "Bestätigen" })),
    );
    const fenster = el("dialog", {}, formular);
    let ergebnis = null;
    abbruch.onclick = () => fenster.close();
    formular.onsubmit = () => {
      ergebnis = feld.value.trim();
    };
    fenster.onclose = () => {
      fenster.remove();
      fertig(ergebnis);
    };
    document.body.append(fenster);
    fenster.showModal();
  });
}

function anmeldeseite() {
  const feld = el("input", { type: "password", autocomplete: "off", placeholder: "Zugangstoken", required: true });
  feld.setAttribute("aria-label", "Zugangstoken");
  const formular = el(
    "form",
    {},
    el("div", { className: "marke" }, el("span", { className: "zeichen" }, icon("file-text")), "Belegflow"),
    el("p", { className: "leise", textContent: "Eingangsrechnungen erfassen, prüfen und freigeben" }),
    feld,
    el("button", { className: "knopf haupt", textContent: "Anmelden" }),
  );
  formular.onsubmit = (ereignis) => {
    ereignis.preventDefault();
    token = feld.value.trim();
    versuche(start);
  };
  wurzel.replaceChildren(el("div", { className: "anmeldung" }, formular));
}

function abmelden() {
  sessionStorage.removeItem("belegflow");
  token = "";
  ich = null;
  anmeldeseite();
}

function rahmen(aktiv, stand, inhalt, schmal = false) {
  const marker = { aufgaben: stand.je_status.pruefen, freigabe: stand.je_status.bereit, uebertragung: stand.je_status.freigegeben };
  const nav = el(
    "nav",
    {},
    el("div", { className: "marke" }, el("div", { className: "zeichen" }, icon("file-text")), el("span", { textContent: "Belegflow" })),
  );
  nav.setAttribute("aria-label", "Hauptmenü");
  for (const [name, titel, symbol] of SEITEN) {
    if (name === "lieferanten") nav.append(el("div", { className: "luft" }));
    const link = el("a", { href: `#${name}`, title: titel, className: name === aktiv ? "an" : "" }, icon(symbol), el("span", { textContent: titel }));
    if (name === aktiv) link.setAttribute("aria-current", "page");
    if (marker[name]) link.append(el("span", { className: "marker", textContent: marker[name] }));
    nav.append(link);
  }
  const wechsel = () => farbe(document.documentElement.dataset.farbe === "dunkel" ? "hell" : "dunkel");
  nav.append(el("button", { type: "button", title: "Hell oder dunkel", onclick: wechsel }, icon("moon"), el("span", { textContent: "Hell oder dunkel" })));
  const ende = el("button", { type: "button", title: "Abmelden", onclick: abmelden }, icon("sign-out"), el("span", { textContent: "Abmelden" }));
  nav.append(ende);
  wurzel.replaceChildren(el("div", { className: "rahmen" + (schmal ? " schmal" : "") }, nav, inhalt));
  nav.querySelector(".an")?.scrollIntoView({ block: "nearest", inline: "center" });
}

function seite(titel, werkzeuge, ...inhalt) {
  return el("main", {}, el("div", { className: "kopf" }, el("h1", { textContent: titel }), ...werkzeuge), el("div", { className: "seite" }, ...inhalt));
}

function hochladen() {
  const wahl = el("input", { type: "file", accept: ".pdf,.png,.jpg,.jpeg", multiple: true, hidden: true });
  wahl.onchange = () =>
    versuche(async () => {
      const dateien = [...wahl.files];
      let erfasst = 0;
      const probleme = [];
      for (const datei of dateien) {
        melde(`${datei.name} wird ausgelesen`);
        const daten = new FormData();
        daten.append("datei", datei);
        try {
          await api("/belege", "POST", daten);
          erfasst += 1;
        } catch (fehler) {
          if (fehler.status === 401) throw fehler;
          probleme.push(`${datei.name}: ${fehler.message}`);
        }
      }
      await zeige();
      if (probleme.length) melde(probleme.join(" / "), true);
      else melde(erfasst === 1 ? "1 Beleg erfasst" : `${erfasst} Belege erfasst`);
    });
  return el("span", {}, wahl, knopf("Hochladen", () => wahl.click(), { klasse: "haupt", symbol: "upload-simple", gesperrt: !darf("buchhaltung") && !darf("eingang") }));
}

function suchfeld(wert, beiSuche) {
  const feld = el("input", { type: "search", placeholder: "Suche", value: wert });
  feld.setAttribute("aria-label", "Belege suchen");
  const formular = el("form", { className: "suche" }, icon("magnifying-glass"), feld);
  formular.onsubmit = (ereignis) => {
    ereignis.preventDefault();
    beiSuche(feld.value.trim());
  };
  return formular;
}

function tabelle(koepfe, zeilen, leer) {
  if (!zeilen.length) return el("p", { className: "leer", textContent: leer });
  const kopf = el("tr", {}, ...koepfe.map((k) => el("th", { textContent: k.replace("|", ""), className: k.endsWith("|") ? "zahl" : "" })));
  return el("div", { className: "rollen" }, el("table", {}, el("thead", {}, kopf), el("tbody", {}, ...zeilen)));
}

function belegzeile(beleg) {
  const zeile = el(
    "tr",
    { className: "wahl", tabIndex: 0 },
    el("td", {}, pille(beleg.status)),
    el("td", { textContent: beleg.lieferant || beleg.dateiname }),
    el("td", { textContent: beleg.rechnungsnummer || "" }),
    el("td", { textContent: tag(beleg.rechnungsdatum) }),
    el("td", { textContent: tag(beleg.faellig_am) }),
    el("td", { textContent: euro(beleg.brutto), className: "zahl" }),
  );
  zeile.onclick = () => {
    location.hash = `beleg/${beleg.id}`;
  };
  zeile.onkeydown = (ereignis) => {
    if (ereignis.key === "Enter") zeile.onclick();
  };
  return zeile;
}

const belegtabelle = (belege, leer) =>
  tabelle(["Status", "Lieferant", "Rechnungsnummer", "Datum", "Fällig", "Brutto|"], belege.map(belegzeile), leer);

function tachometer(prozent) {
  const laenge = Math.PI * 90;
  const anteil = (prozent ?? 0) / 100;
  const bild = svg(
    "svg",
    { viewBox: "0 0 220 130", width: "220", role: "img", "aria-label": prozent === null ? "Noch keine Belege" : `${prozent} Prozent` },
    svg("path", { class: "bahn", d: "M20 115 A90 90 0 0 1 200 115", "stroke-width": 18, "stroke-linecap": "round" }),
  );
  if (anteil > 0)
    bild.append(svg("path", { class: "bogen", d: "M20 115 A90 90 0 0 1 200 115", "stroke-width": 18, "stroke-dasharray": `${laenge * anteil} ${laenge}` }));
  const text = svg("text", { x: 110, y: 108, "text-anchor": "middle" });
  text.textContent = prozent === null ? "–" : `${prozent} %`;
  bild.append(text);
  return bild;
}

function ring(prozent, titel) {
  const umfang = 2 * Math.PI * 42;
  const bild = svg("svg", { viewBox: "0 0 110 110", width: "110", role: "img", "aria-label": `${titel}: ${prozent ?? 0} Prozent` }, svg("circle", { class: "bahn", cx: 55, cy: 55, r: 42, "stroke-width": 9 }));
  if (prozent) bild.append(svg("circle", { class: "bogen", cx: 55, cy: 55, r: 42, "stroke-width": 9, transform: "rotate(-90 55 55)", "stroke-dasharray": `${(umfang * prozent) / 100} ${umfang}` }));
  const text = svg("text", { x: 55, y: 63, "text-anchor": "middle" });
  text.textContent = prozent === null ? "–" : `${prozent}%`;
  bild.append(text);
  return bild;
}

function kachel(ziel, titel, wert, symbol, art) {
  return el("a", { className: "karte kachel", href: `#${ziel}` }, el("div", { className: `bild s-${art}` }, icon(symbol)), el("div", {}, titel, el("strong", { textContent: wert || 0 })));
}

async function seiteUebersicht(stand) {
  const [belege, protokoll] = await Promise.all([holen("/belege?grenze=6"), holen("/protokoll/pruefung")]);
  const j = stand.je_status;
  const entschieden = (j.freigegeben || 0) + (j.exportiert || 0) + (j.abgelehnt || 0);
  const quote = stand.gesamt ? Math.round((entschieden * 100) / stand.gesamt) : null;
  const infos = el("dl", { className: "karte infos" }, el("h2", { textContent: "Informationen" }));
  for (const [titel, wert] of [
    ["Angemeldet", ich.name],
    ["Rollen", ich.rollen.join(", ")],
    ["Auslesen", stand.extraktor === "claude" ? "Claude" : "Regeln, auf dem eigenen Server"],
    ["Offener Betrag", euro(stand.offen_betrag)],
    ["Protokoll", protokoll.gueltig ? "Unverändert" : `Verändert bei Eintrag ${protokoll.fehler_bei}`],
  ])
    infos.append(el("div", {}, el("dt", { textContent: titel }), el("dd", { textContent: wert })));
  return seite(
    "Übersicht",
    [hochladen()],
    el(
      "div",
      { className: "uebersicht" },
      el(
        "section",
        { className: "karte gross" },
        el("div", {}, el("h2", { textContent: "Automatisch verarbeitet" }), el("p", { className: "wert", textContent: `${stand.automatisch} von ${stand.gesamt}` }), el("p", { className: "leise", textContent: "Belege wurden ohne Korrektur richtig ausgelesen." })),
        tachometer(stand.quote),
      ),
      el("section", { className: "karte ring" }, el("h2", { textContent: "Entschieden" }), ring(quote, "Entschieden"), el("p", { className: "leise klein", textContent: "freigegeben, exportiert oder abgelehnt" })),
      infos,
      kachel("aufgaben", "Prüfen", j.pruefen, "pencil-simple", "pruefen"),
      kachel("freigabe", "Freigeben", j.bereit, "check-circle", "bereit"),
      kachel("uebertragung", "Exportieren", j.freigegeben, "download-simple", "exportiert"),
      el(
        "section",
        { className: "karte tabellenkarte" },
        el("div", { className: "titelzeile" }, el("h2", { textContent: "Letzte Belege" }), el("a", { className: "knopf", href: "#belege", textContent: "Alle anzeigen" })),
        belegtabelle(belege, "Noch keine Belege. Lade oben die erste Rechnung hoch."),
      ),
    ),
  );
}

async function seiteListe(titel, status, leer, suche = "") {
  const belege = await holen(`/belege?grenze=200${status ? `&status=${status}` : ""}${suche ? `&suche=${encodeURIComponent(suche)}` : ""}`);
  const ziel = location.hash.slice(1).split("?")[0];
  const werkzeuge = [
    suchfeld(suche, (wert) => {
      location.hash = wert ? `${ziel}?${encodeURIComponent(wert)}` : ziel;
    }),
    hochladen(),
  ];
  return seite(titel, werkzeuge, el("section", { className: "karte tabellenkarte" }, belegtabelle(belege, suche ? "Keine Belege gefunden." : leer)));
}

async function seiteUebertragung() {
  const [frei, fertig] = await Promise.all([holen("/belege?grenze=200&status=freigegeben"), holen("/belege?grenze=50&status=exportiert")]);
  const exportieren = async () => {
    const datei = await (await api("/export", "POST")).blob();
    const verweis = el("a", { href: URL.createObjectURL(datei), download: "belegflow_export.csv" });
    verweis.click();
    setTimeout(() => URL.revokeObjectURL(verweis.href), 1000);
    await zeige();
    melde("Export erstellt");
  };
  return seite(
    "Übertragung",
    [knopf(`CSV exportieren (${frei.length})`, exportieren, { klasse: "haupt", symbol: "download-simple", gesperrt: !frei.length || !darf("buchhaltung") })],
    el("section", { className: "karte tabellenkarte" }, el("div", { className: "titelzeile" }, el("h2", { textContent: "Bereit zum Export" })), belegtabelle(frei, "Keine freigegebenen Belege.")),
    el("section", { className: "karte tabellenkarte" }, el("div", { className: "titelzeile" }, el("h2", { textContent: "Schon exportiert" })), belegtabelle(fertig, "Noch nichts exportiert.")),
  );
}

async function seiteAuswertung(stand) {
  const groesste = Math.max(1, ...stand.monate.map((m) => m.anzahl));
  const bild = svg("svg", { class: "balken", viewBox: "0 0 600 220", width: "100%", role: "img", "aria-label": "Belege pro Monat" });
  stand.monate.forEach((m, i) => {
    const hoehe = (m.anzahl / groesste) * 150;
    const x = 30 + i * 95;
    const name = svg("text", { x: x + 27, y: 212, "text-anchor": "middle" });
    name.textContent = new Date(`${m.monat}-01T00:00`).toLocaleDateString("de-AT", { month: "short" });
    const wert = svg("text", { x: x + 27, y: 182 - hoehe, "text-anchor": "middle" });
    wert.textContent = m.anzahl;
    bild.append(svg("rect", { x, y: 190 - hoehe, width: 54, height: Math.max(hoehe, 1), rx: 5 }), wert, name);
  });
  const fehler = stand.fehler.map((f) => el("tr", {}, el("td", { textContent: f.text }), el("td", { className: "zahl", textContent: f.anzahl })));
  return seite(
    "Auswertung",
    [],
    el("section", { className: "karte" }, el("h2", { textContent: "Belege pro Monat" }), bild),
    el("section", { className: "karte tabellenkarte" }, el("div", { className: "titelzeile" }, el("h2", { textContent: "Offene Fehler" })), tabelle(["Fehler", "Anzahl|"], fehler, "Keine offenen Fehler.")),
  );
}

async function seiteRegelwerk() {
  const regeln = await holen("/regeln");
  const eingaben = [["lieferant", "Lieferant"], ["lieferant_uid", "UID"], ["konto", "Konto"], ["kostenstelle", "Kostenstelle"]];
  const formular = el("form", { className: "karte formular" }, ...eingaben.map(([name, titel]) => el("label", {}, titel, el("input", { name, required: true }))), el("button", { className: "knopf haupt", textContent: "Regel anlegen" }));
  formular.onsubmit = (ereignis) => {
    ereignis.preventDefault();
    const werte = Object.fromEntries(new FormData(formular));
    versuche(async () => {
      await api("/regeln", "POST", werte);
      await zeige();
      melde("Regel angelegt");
    });
  };
  const zeilen = regeln.map((r) =>
    el(
      "tr",
      {},
      el("td", { textContent: r.lieferant || "" }),
      el("td", { textContent: r.lieferant_uid }),
      el("td", { textContent: r.konto }),
      el("td", { textContent: r.kostenstelle }),
      el("td", { textContent: r.erstellt_von }),
      el("td", { className: "zahl" }, knopf("", async () => { await api(`/regeln/${r.id}`, "DELETE"); await zeige(); }, { klasse: "rund", symbol: "trash", gesperrt: !darf("buchhaltung"), titel: "Regel löschen" })),
    ),
  );
  return seite(
    "Regelwerk",
    [],
    el("p", { className: "leise", textContent: "Neue Belege eines Lieferanten bekommen Konto und Kostenstelle aus der Regel." }),
    darf("buchhaltung") ? formular : "",
    el("section", { className: "karte tabellenkarte" }, tabelle(["Lieferant", "UID", "Konto", "Kostenstelle", "Angelegt von", ""], zeilen, "Noch keine Regeln.")),
  );
}

async function seiteLieferanten() {
  const zeilen = (await holen("/lieferanten")).map((l) =>
    el("tr", {}, el("td", { textContent: l.lieferant || "" }), el("td", { textContent: l.lieferant_uid || "" }), el("td", { className: "zahl", textContent: l.belege }), el("td", { className: "zahl", textContent: `${Math.round((l.automatisch * 100) / l.belege)} %` }), el("td", { className: "zahl", textContent: euro(l.brutto) })),
  );
  return seite("Lieferanten", [], el("section", { className: "karte tabellenkarte" }, tabelle(["Lieferant", "UID", "Belege|", "Automatisch|", "Brutto|"], zeilen, "Noch keine Lieferanten.")));
}

async function seiteBenutzer() {
  const zeilen = (await holen("/benutzer")).map((b) => el("tr", {}, el("td", { textContent: b.name }), el("td", { textContent: b.rollen.join(", ") })));
  return seite("Benutzer", [], el("section", { className: "karte tabellenkarte" }, tabelle(["Name", "Rollen"], zeilen, "Keine Benutzer.")));
}

const steuertext = (beleg) => beleg.steuerzeilen.map((z) => [z.satz, z.netto, z.ust].join(" / ")).join("; ");
const steuerzeilen = (text) =>
  (text || "").split(";").filter((t) => t.trim()).map((t) => {
    const [satz, netto, ust] = t.split("/").map((w) => (w || "").trim().replace(",", "."));
    return { satz: satz ?? "", netto: netto ?? "", ust: ust ?? "" };
  });

function betragText(wert) {
  if (!wert) return wert;
  return wert.includes(",") ? wert.replaceAll(".", "").replace(",", ".") : wert;
}

function verlaufsliste(eintraege) {
  return el(
    "ol",
    { className: "verlauf" },
    ...eintraege.toReversed().map((v) => {
      const inhalt = el("div", {}, el("strong", { textContent: v.benutzer }), ` ${AKTIONEN[v.aktion] || v.aktion}`, el("div", { className: "leise klein", textContent: zeit(v.zeitpunkt) }));
      const text = v.details.text || v.details.grund || (v.details.neu && Object.entries(v.details.neu).map(([feld, wert]) => `${feld}: ${Array.isArray(wert) ? "geändert" : (wert ?? "leer")}`).join(", "));
      if (text) inhalt.append(el("blockquote", { textContent: text }));
      return el("li", {}, el("span", { className: "person", textContent: v.benutzer.slice(0, 2).toUpperCase() }), inhalt);
    }),
  );
}

function dokumentansicht(beleg) {
  const bild = el("img", { alt: `Beleg ${beleg.id}` });
  const blatt = el("div", { className: "blatt" }, bild);
  const anzeige = el("span", { className: "klein leise" });
  const seiten = el("span", { className: "klein leise" });
  let breite = 100;
  let nummer = 1;
  let anzahl = 1;
  const zoom = (neu) => {
    breite = Math.min(250, Math.max(40, neu));
    bild.style.width = `${breite}%`;
    bild.style.maxWidth = breite > 100 ? "none" : "900px";
    anzeige.textContent = `${breite} %`;
  };
  const lade = async (neu) => {
    const antwort = await api(`/belege/${beleg.id}/bild?seite=${neu}`);
    anzahl = Number(antwort.headers.get("X-Seiten"));
    nummer = neu;
    const inhalt = await antwort.blob();
    if (bildAdresse) URL.revokeObjectURL(bildAdresse);
    bildAdresse = URL.createObjectURL(inhalt);
    bild.src = bildAdresse;
    seiten.textContent = `Seite ${nummer} von ${anzahl}`;
    zurueck.disabled = nummer <= 1;
    weiter.disabled = nummer >= anzahl;
  };
  const zurueck = knopf("", () => lade(nummer - 1), { klasse: "rund", symbol: "caret-left", titel: "Vorige Seite" });
  const weiter = knopf("", () => lade(nummer + 1), { klasse: "rund", symbol: "caret-right", titel: "Nächste Seite" });
  const herunterladen = async () => {
    const datei = await (await api(`/belege/${beleg.id}/datei`)).blob();
    const verweis = el("a", { href: URL.createObjectURL(datei), download: beleg.dateiname });
    verweis.click();
    setTimeout(() => URL.revokeObjectURL(verweis.href), 1000);
  };
  zoom(100);
  lade(1).catch((fehler) => blatt.replaceChildren(el("p", { className: "leer", textContent: fehler.message })));
  return el(
    "div",
    { className: "mitte" },
    el(
      "div",
      { className: "werkzeug" },
      zurueck,
      seiten,
      weiter,
      knopf("", () => zoom(breite - 20), { klasse: "rund", symbol: "minus", titel: "Verkleinern" }),
      anzeige,
      knopf("", () => zoom(breite + 20), { klasse: "rund", symbol: "plus", titel: "Vergrößern" }),
      knopf("Herunterladen", herunterladen, { symbol: "download-simple" }),
    ),
    blatt,
  );
}

async function seiteBeleg(id) {
  const [beleg, verlauf, nachbarn] = await Promise.all([holen(`/belege/${id}`), holen(`/belege/${id}/protokoll`), holen("/belege?grenze=200")]);
  const stelle = nachbarn.findIndex((b) => b.id === beleg.id);
  const offen = OFFEN.includes(beleg.status);
  const bearbeitbar = offen && darf("buchhaltung");
  const gehe = (b) => () => {
    location.hash = `beleg/${b.id}`;
  };
  const neu = async (pfad, methode, inhalt, text) => {
    let erfolg = false;
    try {
      await api(pfad, methode, inhalt);
      erfolg = true;
    } finally {
      await zeige();
    }
    if (erfolg) melde(text);
  };

  const kommentarfeld = el("textarea", { placeholder: "Kommentar schreiben", maxLength: 1000 });
  kommentarfeld.setAttribute("aria-label", "Kommentar");
  const links = el(
    "div",
    { className: "links" },
    el(
      "div",
      { className: "rueck" },
      knopf("Liste", () => { location.hash = "belege"; }, { symbol: "caret-left" }),
      knopf("", gehe(nachbarn[stelle - 1]), { klasse: "rund", symbol: "caret-left", gesperrt: stelle <= 0, titel: "Neuerer Beleg" }),
      knopf("", gehe(nachbarn[stelle + 1]), { klasse: "rund", symbol: "caret-right", gesperrt: stelle < 0 || stelle >= nachbarn.length - 1, titel: "Älterer Beleg" }),
    ),
    el(
      "section",
      { className: "karte" },
      el("div", { className: "summe" }, el("h2", { textContent: `Rechnung ${beleg.id}` }), pille(beleg.status)),
      el("p", { textContent: beleg.lieferant || beleg.dateiname }),
      el("p", { className: "leise klein", textContent: beleg.rechnungsnummer || "ohne Nummer" }),
      el("div", { className: "summe" }, el("span", { className: "leise klein", textContent: tag(beleg.rechnungsdatum) }), el("strong", { textContent: euro(beleg.brutto) })),
    ),
    beleg.hinweise.length
      ? el("ul", { className: "meldungen" }, ...beleg.hinweise.map((h) => el("li", { className: h.stufe }, icon(h.stufe === "fehler" ? "warning-circle" : "warning"), h.text)))
      : null,
    el(
      "section",
      { className: "karte" },
      el("h2", { textContent: `Verlauf und Kommentare (${verlauf.length})` }),
      el("div", { className: "kommentar" }, kommentarfeld, knopf("Senden", async () => {
        const text = kommentarfeld.value.trim();
        if (text) await neu(`/belege/${id}/kommentar`, "POST", { text }, "Kommentar gespeichert");
      })),
      verlaufsliste(verlauf),
    ),
  );

  const feld = (name, titel, art = "text") => el("label", {}, titel, el("input", { name, type: art, value: beleg[name] ?? "", disabled: !bearbeitbar }));
  const formular = el(
    "form",
    { className: "inhalt" },
    el("h2", { textContent: offen ? "Wartet auf Bearbeitung" : STATUS[beleg.status][0] }),
    feld("lieferant", "Lieferant"),
    feld("lieferant_uid", "UID"),
    feld("empfaenger", "Empfänger"),
    feld("rechnungsnummer", "Rechnungsnummer"),
    el("div", { className: "paar" }, feld("rechnungsdatum", "Rechnungsdatum", "date"), feld("faellig_am", "Fällig am", "date")),
    feld("iban", "IBAN"),
    el("div", { className: "paar" }, feld("netto", "Netto"), feld("ust", "USt")),
    feld("brutto", "Brutto"),
    el("label", {}, "Steuerzeilen (Satz / Netto / USt)", el("input", { name: "steuerzeilen", value: steuertext(beleg), disabled: !bearbeitbar })),
    el("div", { className: "paar" }, feld("konto", "Konto"), feld("kostenstelle", "Kostenstelle")),
  );
  const speichern = async () => {
    const werte = {};
    for (const eingabe of formular.querySelectorAll("input")) {
      const wert = eingabe.value.trim() || null;
      if (eingabe.name === "steuerzeilen") {
        if (wert !== (steuertext(beleg) || null)) werte.steuerzeilen = steuerzeilen(wert);
      } else {
        const sauber = GELD.includes(eingabe.name) ? betragText(wert) : wert;
        if (sauber !== (beleg[eingabe.name] ?? null)) werte[eingabe.name] = sauber;
      }
    }
    if (!Object.keys(werte).length) return melde("Keine Änderungen");
    await api(`/belege/${id}`, "PATCH", werte);
    await zeige();
    melde("Gespeichert");
  };
  formular.onsubmit = (ereignis) => {
    ereignis.preventDefault();
    if (bearbeitbar) versuche(speichern);
  };

  const fehlerfrei = !beleg.hinweise.some((h) => h.stufe === "fehler");
  const punkt = (text, erledigt) => el("div", { className: erledigt ? "fertig" : "leise" }, icon(erledigt ? "check-circle" : "clock"), text);
  const schritt = el(
    "div",
    { className: "schritt" },
    el("strong", { textContent: "Nächster Schritt" }),
    el(
      "div",
      { className: "schrittbox" },
      punkt("Angaben fehlerfrei", fehlerfrei),
      punkt("Konto und Kostenstelle", Boolean(beleg.konto && beleg.kostenstelle)),
      punkt(beleg.freigegeben_von ? `Freigegeben von ${beleg.freigegeben_von}` : "Freigabe durch zweite Person", Boolean(beleg.freigegeben_von)),
    ),
  );
  if (offen) {
    const knoepfe = el("div", { className: "knoepfe" });
    if (darf("freigabe") && beleg.hinweise.some((h) => h.code === "iban_neu" && h.stufe === "fehler"))
      knoepfe.append(knopf("Neue IBAN bestätigen", async () => {
        const grund = await frage("Neue IBAN bestätigen", "Wie wurde die IBAN geprüft?");
        if (grund) await neu(`/belege/${id}/iban-bestaetigung`, "POST", { grund }, "IBAN bestätigt");
      }, { klasse: "ganz", symbol: "shield-check" }));
    if (bearbeitbar) knoepfe.append(knopf("Speichern", speichern, { klasse: darf("freigabe") ? "ganz" : "ganz haupt" }));
    if (darf("freigabe"))
      knoepfe.append(
        knopf("Ablehnen", async () => {
          const grund = await frage("Beleg ablehnen", "Warum wird der Beleg abgelehnt?");
          if (grund) await neu(`/belege/${id}/ablehnung`, "POST", { grund }, "Abgelehnt");
        }, { klasse: "gefahr" }),
        knopf("Freigeben", () => neu(`/belege/${id}/freigabe`, "POST", null, "Freigegeben"), { klasse: "haupt", gesperrt: !fehlerfrei }),
      );
    schritt.append(knoepfe);
  }
  return el("main", { className: "beleg" }, links, dokumentansicht(beleg), el("div", { className: "rechts" }, formular, schritt));
}

async function zeige() {
  if (!ich) return;
  const meiner = ++lauf;
  const [weg, suche = ""] = location.hash.slice(1).split("?");
  const [name, id] = (weg || "uebersicht").split("/");
  const begriff = decodeURIComponent(suche);
  const stand = await holen("/uebersicht");
  const inhalte = {
    uebersicht: () => seiteUebersicht(stand),
    aufgaben: () => seiteListe("Aufgaben", "pruefen", "Nichts zu prüfen.", begriff),
    freigabe: () => seiteListe("Freigabe", "bereit", "Nichts freizugeben.", begriff),
    uebertragung: () => seiteUebertragung(),
    belege: () => seiteListe("Belege", "", "Noch keine Belege.", begriff),
    auswertung: () => seiteAuswertung(stand),
    regelwerk: () => seiteRegelwerk(),
    lieferanten: () => seiteLieferanten(),
    benutzer: () => seiteBenutzer(),
    papierkorb: () => seiteListe("Papierkorb", "abgelehnt", "Keine abgelehnten Belege.", begriff),
    beleg: () => seiteBeleg(Number(id)),
  };
  const inhalt = await (inhalte[name] || inhalte.uebersicht)();
  if (meiner === lauf) rahmen(name === "beleg" ? "belege" : name in inhalte ? name : "uebersicht", stand, inhalt, name === "beleg");
}

async function start() {
  ich = await holen("/ich");
  if (!darf("buchhaltung") && !darf("freigabe")) {
    ich = null;
    throw new Error("Dieser Zugang darf nur Belege einreichen");
  }
  sessionStorage.setItem("belegflow", token);
  await zeige();
}

window.onhashchange = () => versuche(zeige);
if (token) start().catch(abmelden);
else anmeldeseite();
