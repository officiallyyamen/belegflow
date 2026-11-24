import { adresse, euro, gehe, h, hat, hole, icon, melde, sende, tag, vorTagen, z } from "../kern.js";
import { hochladen } from "../rahmen.js";
import { ARTEN, feld, knopf, kopf, pille, reiter, tabelle } from "../teile.js";

export function merkmale(b) {
  const liste = [
    b.ueberfaellig ? ["clock", "Überfällig", "fehler"] : null,
    b.probleme ? ["warning-circle", `${b.probleme} Prüfungen fehlgeschlagen`, "fehler"] : null,
    b.duplikat ? ["copy", "Mögliches Duplikat", "fehler"] : null,
    b.e_rechnung ? ["file-text", b.e_rechnung, "info"] : null,
    b.automatik ? ["lightning", "Automatisch verarbeitet", "gut"] : null,
    b.eingeschraenkt ? ["lock", "Eingeschränkt sichtbar", "ruhig"] : null,
    b.kommentare ? ["chat-circle", `${b.kommentare} Kommentare`, "ruhig"] : null,
    b.anhaenge ? ["paperclip", `${b.anhaenge} Anhänge`, "ruhig"] : null,
    b.verknuepfungen ? ["link", `${b.verknuepfungen} Verknüpfungen`, "ruhig"] : null,
    b.zahlstatus === "karte" ? ["credit-card", "Mit Karte bezahlt", "ruhig"] : null,
  ].filter(Boolean);
  return h("span.merkmale", liste.map(([bild, text, farbe]) => h("span", { class: farbe, title: text, role: "img", "aria-label": text }, icon(bild))));
}

export const belegspalten = [
  { titel: "Status", wert: (b) => pille(b.status, b.status === "neu" ? "Neu" : undefined) },
  { titel: "Info", wert: merkmale },
  { titel: "Geschäftspartner", wert: (b) => h("div", h("strong", b.partner || b.lieferant || b.dateiname), h("p.leise.klein", ARTEN[b.art])) },
  { titel: "Gesamtbetrag", wert: (b) => euro(b.art === "gutschrift" && b.brutto ? -b.brutto : b.brutto, b.waehrung), klasse: "zahl" },
  { titel: "Rechnungsnummer", wert: (b) => b.nummer || "–" },
  { titel: "Kontierung", wert: (b) => h("span.leise", [b.konto, b.kostenstelle].filter(Boolean).join(" / ")), klasse: "breitab" },
  { titel: "Rechnungsdatum", wert: (b) => tag(b.datum), klasse: "breitab" },
  { titel: "Fälligkeit", wert: (b) => (b.faellig_am ? h("span", { class: b.ueberfaellig ? "rot" : "", title: vorTagen(b.faellig_am) }, tag(b.faellig_am)) : "–") },
];

export function eingangsreiter(aktiv) {
  const e = z.zaehler?.eingang || {};
  return reiter(
    [
      ["eingang/rechnungen", "Rechnungen", e.rechnungen],
      ["karten/transaktionen", "Transaktionen", e.transaktionen],
      ["eingang/vertraege", "Verträge", e.vertraege],
      ["erstattungen/pruefen", "Erstattungen", e.erstattungen],
      ["eingang/dokumente", "Sonstige Dokumente", e.dokumente],
    ],
    aktiv,
  );
}

const filter = { suche: "", merkmal: "", stufe: "", partner_id: "", sortierung: "neu" };

export async function seite([welcher = "rechnungen", art = ""]) {
  const klaerung = art === "klaerung";
  const gewaehlt = new Set();
  const ergebnis = h("div.karte.eng");
  const hinweis = h("div");
  const leiste = h("div.sammel", { hidden: true });

  async function tue(aktion, text) {
    const antwort = await sende("/belege/sammel", { nummern: [...gewaehlt].map((b) => b.id), aktion });
    gewaehlt.clear();
    melde(antwort.fehler.length ? `${antwort.fertig.length} ${text}, ${antwort.fehler.length} nicht: ${antwort.fehler[0].grund}` : `${antwort.fertig.length} ${text}`, antwort.fehler.length > 0);
    await neu();
  }

  const auswahl = {
    gewaehlt,
    geaendert: () => {
      leiste.hidden = !gewaehlt.size;
      leiste.replaceChildren(
        h("strong", `${gewaehlt.size} ausgewählt`),
        welcher === "rechnungen" ? knopf("Freigabe anfordern", () => tue("anfordern", "angefordert"), { bild: "paper-plane-tilt", art: "haupt" }) : knopf("Im Archiv ablegen", () => tue("ablegen", "abgelegt"), { bild: "archive", art: "haupt" }),
        welcher === "rechnungen" && hat("freigabe") ? knopf("Sofort freigeben", () => tue("freigeben", "freigegeben"), { bild: "check" }) : null,
        knopf(klaerung ? "Klärung beenden" : "Klärung", () => tue("klaerung", "verschoben"), { bild: "question" }),
        knopf("Papierkorb", () => tue("papierkorb", "gelöscht"), { bild: "trash" }),
      );
    },
  };

  async function neu() {
    const daten = await hole("/eingang", { reiter: welcher, klaerung, ...filter });
    ergebnis.replaceChildren(
      tabelle(belegspalten, daten.eintraege, { beiKlick: (b) => gehe(`beleg/${b.id}`), wahl: hat("buchhaltung", "admin") ? auswahl : null, leertext: klaerung ? "Nichts in Klärung" : "Der Eingang ist leer" }),
      daten.eintraege.length ? h("footer.fuss.leise.klein", h("span", daten.gesamt > daten.eintraege.length ? `${daten.eintraege.length} von ${daten.gesamt} Einträgen` : `${daten.gesamt} Einträge`), daten.summe ? h("span", `Summe ${euro(daten.summe)}`) : null) : "",
    );
    auswahl.geaendert();
    hinweis.replaceChildren(
      daten.automatik?.length
        ? h(
            "div.hinweis",
            icon("lightning"),
            h("span", `${daten.automatik.length} ${daten.automatik.length === 1 ? "Rechnung ist" : "Rechnungen sind"} für die Automatik bereit`),
            knopf("Anzeigen", () => gehe(`beleg/${daten.automatik[0]}`)),
          )
        : "",
    );
  }
  await neu();
  const uhr = { nr: null };
  const suche = h("input", { type: "search", placeholder: "Suchen", value: filter.suche, "aria-label": "Suchen" });
  suche.oninput = () => {
    clearTimeout(uhr.nr);
    uhr.nr = setTimeout(() => { filter.suche = suche.value.trim(); neu(); }, 220);
  };
  const wahl = (name, text, optionen, leer) => feld({ name, text, art: "wahl", optionen, leer }, filter[name], (w) => { filter[name] = w; neu(); });
  const gefiltert = filter.merkmal || filter.stufe || filter.partner_id || filter.sortierung !== "neu";
  const mehr = h(
    "div.filterzeile",
    { hidden: !gefiltert },
    wahl("merkmal", "Merkmal", [["ueberfaellig", "Überfällig"], ["e_rechnung", "E-Rechnung"], ["duplikat", "Duplikat"]], "Alle"),
    wahl("stufe", "Prüfung", [["ok", "In Ordnung"], ["warnung", "Warnung"], ["fehler", "Fehler"], ["sperre", "Gesperrt"]], "Alle"),
    z.stamm.partner ? wahl("partner_id", "Partner", z.stamm.partner.map((p) => [p.id, p.name]), "Alle") : null,
    wahl("sortierung", "Sortieren", [["alt", "Älteste"], ["faellig", "Fälligkeit"], ["betrag", "Betrag"], ["lieferant", "Lieferant"]], "Neueste"),
  );
  return h(
    "div.seite",
    kopf("Eingang", knopf("Dokumente hochladen", hochladen, { bild: "plus", art: "haupt" })),
    eingangsreiter(`eingang/${welcher}`),
    hinweis,
    h(
      "div.filterzeile",
      h("div.suchfeld", icon("magnifying-glass"), suche),
      h("div.umschalter", h("a", { href: adresse(`eingang/${welcher}`), class: klaerung ? "" : "an" }, "Eingang"), h("a", { href: adresse(`eingang/${welcher}/klaerung`), class: klaerung ? "an" : "" }, "Klärung")),
      knopf("Filter", () => { mehr.hidden = !mehr.hidden; }, { bild: "plus", art: "leise" }),
    ),
    mehr,
    leiste,
    ergebnis,
  );
}

export { pille };
