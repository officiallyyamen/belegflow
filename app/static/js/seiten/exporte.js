import { euro, gehe, h, hat, hole, icon, melde, pfad, sende, tag, zeit } from "../kern.js";
import { knopf, kopf, pille, reiter, tabelle } from "../teile.js";

const FORMATE = { csv: "CSV", bmd: "BMD", zip: "ZIP mit Belegen", stammdaten: "Stammdaten" };

async function wartend() {
  const gewaehlt = new Set();
  const kasten = h("div.stapel");
  const historie = h("div");
  const wieviele = h("p.klein");
  const summe = h("strong.mittel");
  const offenZahl = h("strong.mittel");
  let format = "bmd";
  let bereit = [];
  const formate = h("div.formate");
  const zeichne = () =>
    formate.replaceChildren(
      ...[["bmd", "BMD", "file-text"], ["csv", "CSV", "list-checks"], ["zip", "ZIP mit Belegen", "archive"]].map(([wert, text, bild]) =>
        h("button.formatkarte", { type: "button", class: wert === format ? "an" : "", "aria-pressed": String(wert === format), onclick: () => { format = wert; zeichne(); } }, icon(bild), h("strong", text)),
      ),
    );
  const los = knopf("Exportieren", exportiere, { art: "haupt", bild: "paper-plane-tilt" });
  const geaendert = () => {
    const posten = gewaehlt.size ? [...gewaehlt] : bereit;
    wieviele.textContent = gewaehlt.size ? `${gewaehlt.size} ausgewählt` : "Alle bereiten Buchungen";
    summe.textContent = euro(posten.reduce((s, b) => s + Number(b.brutto || 0), 0));
    los.disabled = !bereit.length;
  };
  async function exportiere() {
    const e = await sende("/exporte", { format, posten: gewaehlt.size ? [...gewaehlt].map((b) => ({ art: b.art, id: b.id })) : null });
    melde(`${e.anzahl} Buchungen exportiert`);
    location.assign(pfad(`/exporte/${e.id}/datei`));
    gewaehlt.clear();
    await neu();
  }
  async function neu() {
    const [alle, fertig] = await Promise.all([hole("/exporte/wartend"), hole("/exporte")]);
    bereit = alle.filter((b) => !b.hindernis);
    const nicht = alle.filter((b) => b.hindernis);
    offenZahl.textContent = String(alle.length);
    const spalten = [
      { titel: "Geschäftspartner", wert: (b) => h("div", h("strong", b.name), h("p.leise.klein", b.nummer)) },
      { titel: "Datum", wert: (b) => tag(b.datum) },
      { titel: "Kreditor", wert: (b) => b.kreditor || "–", klasse: "breitab" },
      { titel: "Kontierung", wert: (b) => [...new Set(b.zeilen.map((x) => `${x.konto || "?"} / ${x.kostenstelle || "?"}`))].join(", "), klasse: "breitab" },
      { titel: "Betrag", wert: (b) => h("strong", euro(b.brutto, b.waehrung)), klasse: "zahl" },
    ];
    kasten.replaceChildren(
      h("h3", `Bereit (${bereit.length})`),
      h("div.karte.eng", tabelle(spalten, bereit, { beiKlick: (b) => gehe(`${b.art}/${b.id}`), leertext: "Nichts bereit", wahl: hat("buchhaltung", "admin") ? { gewaehlt, geaendert } : null })),
      ...(nicht.length ? [h("h3", `Nicht bereit (${nicht.length})`), h("div.karte.eng", tabelle([...spalten, { titel: "Grund", wert: (b) => pille("warnung", b.hindernis) }], nicht, { beiKlick: (b) => gehe(`${b.art}/${b.id}`) }))] : []),
    );
    historie.replaceChildren(
      ...(fertig.length
        ? fertig.slice(0, 8).map((e) => h("a.historie", { href: pfad(`/exporte/${e.id}/datei`), title: e.dateiname }, icon("check-circle"), h("div", h("strong", `${e.von}, ${tag(e.erstellt_am)}`), h("div.titelzeile", h("span", FORMATE[e.format] || e.format), h("span", String(e.anzahl))))))
        : [h("p.leise.klein", "Noch kein Export")]),
    );
    geaendert();
  }
  zeichne();
  await neu();
  return { kasten, historie, offenZahl, rechts: hat("buchhaltung", "admin") ? [h("h2", "Format"), formate, h("div.summenkarte", wieviele, h("div.titelzeile", h("span", "Summe"), summe)), h("p.leise.klein", "Exportierte Buchungen sind danach gesperrt"), los] : null };
}

async function verlauf() {
  const liste = await hole("/exporte");
  const kasten = h(
    "div.karte.eng",
    tabelle(
      [
        { titel: "Erstellt", wert: (e) => zeit(e.erstellt_am) },
        { titel: "Von", wert: (e) => e.von },
        { titel: "Format", wert: (e) => FORMATE[e.format] || e.format },
        { titel: "Einträge", wert: (e) => String(e.anzahl), klasse: "zahl" },
        { titel: "", wert: (e) => h("a.knopf", { href: pfad(`/exporte/${e.id}/datei`) }, icon("download-simple"), e.dateiname) },
      ],
      liste,
      { leertext: "Noch kein Export" },
    ),
  );
  const stamm = knopf("Geschäftspartner exportieren", async () => {
    const e = await sende("/exporte/stammdaten");
    location.assign(pfad(`/exporte/${e.id}/datei`));
  }, { bild: "buildings" });
  return [kasten, hat("buchhaltung", "admin") ? stamm : null];
}

async function abgrenzung() {
  const letzter = new Date();
  letzter.setDate(0);
  let periode = `${letzter.getFullYear()}-${String(letzter.getMonth() + 1).padStart(2, "0")}`;
  const kasten = h("div.stapel");
  const wahl = h("input", { type: "month", value: periode, "aria-label": "Periode" });
  async function neu() {
    const d = await hole("/exporte/rueckstellungen", { periode });
    const spalten = (betrag) => [
      { titel: "Lieferant", wert: (b) => b.lieferant || "–" },
      { titel: "Nummer", wert: (b) => b.nummer || "–" },
      { titel: "Status", wert: (b) => pille(b.status) },
      { titel: "Netto", wert: (b) => euro(b[betrag]), klasse: "zahl" },
    ];
    kasten.replaceChildren(
      h("h2", "Rückstellungen"),
      h("p.leise", "Leistung liegt in der Periode, die Rechnung ist noch nicht freigegeben."),
      h("div.karte.eng", tabelle(spalten("netto"), d.neu, { beiKlick: (b) => gehe(`beleg/${b.id}`), leertext: "Nichts rückzustellen" })),
      h("h2", "Auflösungen"),
      h("div.karte.eng", tabelle(spalten("betrag"), d.aufloesen, { beiKlick: (b) => gehe(`beleg/${b.id}`), leertext: "Nichts aufzulösen" })),
    );
    los.disabled = !d.neu.length && !d.aufloesen.length;
  }
  const los = knopf("Buchungen erstellen", async () => {
    const e = await sende("/exporte/rueckstellungen", { periode });
    location.assign(pfad(`/exporte/${e.id}/datei`));
    await neu();
  }, { art: "haupt", bild: "paper-plane-tilt" });
  wahl.onchange = () => {
    periode = wahl.value || periode;
    neu();
  };
  await neu();
  return [kasten, h("div.reihe", wahl, hat("buchhaltung", "admin") ? los : null)];
}

const bereiche = [["export/wartend", "Bereit"], ["export/abgrenzung", "Rückstellungen"], ["export/verlauf", "Verlauf"]];

export async function seite([welche = "wartend"]) {
  const leiste = reiter(bereiche, `export/${welche}`);
  if (welche === "wartend") {
    const d = await wartend();
    return h("div.zweiteiler", h("div.seite", h("header", h("h1", "Export"), h("p.leise", "Noch nicht exportiert: ", d.offenZahl)), leiste, d.kasten, h("section", h("h2.abschnitttitel", "Letzte Exporte"), d.historie)), d.rechts ? h("aside.teilrechts", d.rechts) : null);
  }
  const [inhalt, rechts] = await { verlauf, abgrenzung }[welche]();
  return h("div.seite", kopf("Export", rechts), leiste, inhalt);
}
