import { adresse, euro, gehe, h, hat, hole, icon, melde, sende, tag, zeit } from "../kern.js";
import { ARTEN, frage, knopf, kopf, pille, stamm, tabelle, verlauf } from "../teile.js";

const felder = () => [
  { name: "name", text: "Name", pflicht: true, breit: true },
  { name: "kreditor", text: "Kreditorenkonto" },
  { name: "uid", text: "UID" },
  { name: "strasse", text: "Straße", breit: true },
  { name: "plz", text: "PLZ" },
  { name: "ort", text: "Ort" },
  { name: "email", text: "E-Mail", breit: true },
  { name: "iban", text: "IBANs, mit Komma getrennt", breit: true },
  { name: "zahlungsziel", text: "Zahlungsziel in Tagen", art: "zahl", zahlen: true },
  { name: "skonto_prozent", text: "Skonto %", art: "zahl" },
  { name: "skonto_tage", text: "Skonto Tage", art: "zahl", zahlen: true },
  { name: "konto", text: "Konto", art: "wahl", optionen: stamm("konto") },
  { name: "kostenstelle", text: "Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") },
];

async function bearbeite(p = null) {
  const d = await frage(p ? p.name : "Geschäftspartner", felder(), p ? { ...p, iban: p.ibans.join(", ") } : {}, {
    breit: true,
    speichern: ({ iban, ...w }) => sende(p ? `/partner/${p.id}` : "/partner", { ...w, ibans: (iban || "").split(",").map((i) => i.trim()).filter(Boolean) }, p ? "PATCH" : "POST"),
  });
  if (d) window.dispatchEvent(new Event("belegflow-stamm"));
  return d;
}

async function einzeln(nummer) {
  const p = await hole(`/partner/${nummer}`);
  return h(
    "div.seite",
    kopf(p.name, hat("buchhaltung", "admin") ? knopf("Ändern", async () => { if (await bearbeite(p)) gehe(`partner/${p.id}`); }, { bild: "pencil-simple" }) : null),
    h(
      "div.zweispaltig.breitlinks",
      h("section.karte.eng", tabelle([{ titel: "Beleg", wert: (b) => h("div", h("strong", ARTEN[b.art]), h("p.leise.klein", b.nummer || "")) }, { titel: "Datum", wert: (b) => tag(b.datum) }, { titel: "Status", wert: (b) => pille(b.status) }, { titel: "Betrag", wert: (b) => euro(b.brutto, b.waehrung), klasse: "zahl" }], p.belege, { beiKlick: (b) => gehe(`beleg/${b.id}`), leertext: "Noch keine Belege" })),
      h(
        "aside.stapel",
        h("div.karte", h("dl.paare", [["Kreditor", p.kreditor], ["UID", p.uid], ["Anschrift", [p.strasse, [p.plz, p.ort].filter(Boolean).join(" ")].filter(Boolean).join(", ")], ["E-Mail", p.email], ["IBAN", p.ibans.join(", ")], ["Zahlungsziel", p.zahlungsziel === null ? "" : `${p.zahlungsziel} Tage`], ["Skonto", p.skonto_prozent ? `${p.skonto_prozent} % in ${p.skonto_tage} Tagen` : ""], ["Konto", p.konto], ["Kostenstelle", p.kostenstelle]].filter(([, w]) => w).map(([n, w]) => [h("dt", n), h("dd", w)]))),
        h("div.karte", h("h3", "Verlauf"), verlauf(p.verlauf)),
      ),
    ),
  );
}

export async function seite([welcher = ""]) {
  if (welcher === "neu") {
    const d = await bearbeite();
    gehe(d ? `partner/${d.id}` : "partner");
    return h("div.seite");
  }
  if (welcher) return einzeln(welcher);
  const kasten = h("div.karte.eng");
  const suche = h("input", { type: "search", placeholder: "Name oder UID", "aria-label": "Suchen" });
  const neu = async () => {
    const liste = await hole("/partner", { suche: suche.value.trim(), grenze: 200 });
    kasten.replaceChildren(
      tabelle(
        [
          { titel: "Name", wert: (p) => h("div", h("strong", p.name), h("p.leise.klein", [p.plz, p.ort].filter(Boolean).join(" "))) },
          { titel: "Kreditor", wert: (p) => p.kreditor || "–" },
          { titel: "UID", wert: (p) => p.uid || "", klasse: "breitab" },
          { titel: "Kontierung", wert: (p) => [p.konto, p.kostenstelle].filter(Boolean).join(" / "), klasse: "breitab" },
          { titel: "Belege heuer", wert: (p) => String(p.belege), klasse: "zahl" },
          { titel: "Umsatz heuer", wert: (p) => h("strong", euro(p.umsatz)), klasse: "zahl" },
        ],
        liste,
        { beiKlick: (p) => gehe(`partner/${p.id}`), leertext: "Nichts gefunden" },
      ),
    );
  };
  let uhr;
  suche.oninput = () => {
    clearTimeout(uhr);
    uhr = setTimeout(neu, 220);
  };
  await neu();
  return h("div.seite", kopf("Geschäftspartner", h("div.suchfeld", icon("magnifying-glass"), suche), hat("buchhaltung", "admin") ? knopf("Neu", async () => { if (await bearbeite()) await neu(); }, { art: "haupt", bild: "plus" }) : null), kasten);
}

export async function nachrichten() {
  const kasten = h("div.karte.eng");
  async function neu() {
    const liste = await hole("/nachrichten");
    kasten.replaceChildren(
      tabelle(
        [
          { titel: "Absender", wert: (n) => h("div", h("strong", n.absender), h("p.leise.klein", n.betreff)) },
          { titel: "Status", wert: (n) => pille(n.status) },
          { titel: "Belege", wert: (n) => h("div.reihe", n.belege.map((b) => h("a.chip", { href: adresse(`beleg/${b.id}`) }, icon("file-text"), b.dateiname))) },
          { titel: "Empfangen", wert: (n) => zeit(n.empfangen_am) },
          {
            titel: "",
            wert: (n) =>
              n.gesperrt || !hat("buchhaltung", "admin")
                ? n.gesperrt ? pille("gesperrt", "Gesperrt") : ""
                : knopf("Sperren", async () => {
                    await sende("/sperren", { art: "absender", wert: n.absender, grund: "Aus dem Postfach gesperrt" });
                    melde("Absender gesperrt");
                    await neu();
                  }, { art: "leise", bild: "lock" }),
          },
        ],
        liste,
        { leertext: "Noch keine E-Mails" },
      ),
    );
  }
  await neu();
  return h("div.seite", kopf("E-Mail Inbox"), h("p.leise", "Alle eingegangenen E-Mails bleiben hier nachvollziehbar, auch ohne Beleg."), kasten);
}
