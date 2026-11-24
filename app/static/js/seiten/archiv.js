import { euro, gehe, h, hole, icon, tag, vorTagen, z } from "../kern.js";
import { ARTEN, STATUS, feld, kopf, pille, stamm, tabelle } from "../teile.js";
import { belegspalten } from "./eingang.js";

const f = { suche: "", modus: "enthaelt" };

export async function seite() {
  const kasten = h("div.karte.eng");
  let ab = 0;
  async function neu() {
    const d = await hole("/archiv", { ...f, ab, grenze: 50 });
    const blaettern = (text, ziel, an) => h("button.knopf", { type: "button", disabled: !an, textContent: text, onclick: () => { ab = ziel; neu(); } });
    kasten.replaceChildren(
      tabelle(belegspalten, d.eintraege, { beiKlick: (b) => gehe(`beleg/${b.id}`), leertext: "Nichts gefunden" }),
      h("footer.fuss.leise.klein", h("span", `${d.gesamt} Dokumente`), d.summe ? h("span", `Summe ${euro(d.summe)}`) : null, h("div.reihe", blaettern("Zurück", Math.max(ab - 50, 0), ab > 0), blaettern("Weiter", ab + 50, ab + 50 < d.gesamt))),
    );
  }
  const setze = (name) => (wert) => {
    f[name] = wert;
    ab = 0;
    neu();
  };
  const wahl = (name, text, optionen, leer = "Alle") => feld({ name, text, art: "wahl", optionen, leer }, f[name], setze(name));
  let uhr;
  const suche = h("input", { type: "search", value: f.suche, placeholder: "Volltext, Nummer, Lieferant", "aria-label": "Archiv durchsuchen" });
  suche.oninput = () => {
    clearTimeout(uhr);
    uhr = setTimeout(() => setze("suche")(suche.value.trim()), 220);
  };
  await neu();
  return h(
    "div.seite",
    kopf("Archiv"),
    h(
      "div.filterzeile",
      h("div.suchfeld", icon("magnifying-glass"), suche),
      feld({ name: "modus", text: "Suche", art: "wahl", leer: "Enthält", optionen: [["beginnt", "Beginnt mit"], ["exakt", "Exakt"]] }, f.modus, (w) => setze("modus")(w || "enthaelt")),
      wahl("art", "Art", Object.entries(ARTEN)),
      wahl("status", "Status", ["neu", "freigabe", "freigegeben", "exportiert", "abgelehnt", "abgelegt", "papierkorb"].map((s) => [s, STATUS[s][0]])),
      z.stamm.partner ? wahl("partner_id", "Partner", z.stamm.partner.map((p) => [p.id, p.name])) : null,
      wahl("konto", "Konto", stamm("konto")),
      wahl("kostenstelle", "Kostenstelle", stamm("kostenstelle")),
      z.stamm.schlagwoerter ? wahl("schlagwort", "Schlagwort", z.stamm.schlagwoerter.map((s) => [s, s])) : null,
      feld({ name: "von", text: "Von", art: "date" }, f.von, setze("von")),
      feld({ name: "bis", text: "Bis", art: "date" }, f.bis, setze("bis")),
      feld({ name: "betrag_ab", text: "Betrag ab", art: "geld" }, f.betrag_ab, setze("betrag_ab")),
      feld({ name: "betrag_bis", text: "Betrag bis", art: "geld" }, f.betrag_bis, setze("betrag_bis")),
    ),
    kasten,
  );
}

export async function vertraege([sortierung = "frist"]) {
  const liste = await hole("/vertraege", { sortierung });
  const frist = (wert) => {
    if (!wert) return "";
    const tage = (new Date(wert) - Date.now()) / 86400000;
    return h("span", { class: tage < 30 ? "rot" : "", title: tag(wert) }, tage < 60 && tage > -60 ? vorTagen(wert) : tag(wert));
  };
  return h(
    "div.seite",
    kopf("Verträge", feld({ name: "s", text: "Sortieren", art: "wahl", leer: "Kündigungsfrist", optionen: [["erinnerung", "Wiedervorlage"], ["ende", "Ende"], ["neu", "Neueste"]] }, sortierung, (w) => gehe(`vertraege/${w || "frist"}`))),
    h(
      "div.karte.eng",
      tabelle(
        [
          { titel: "Vertragspartner", wert: (b) => h("div", h("strong", b.partner || b.lieferant || b.dateiname), h("p.leise.klein", b.vertrag.typ || "")) },
          { titel: "", wert: (b) => (b.eingeschraenkt ? icon("lock") : "") },
          { titel: "Laufzeit", wert: (b) => [tag(b.vertrag.beginn), tag(b.vertrag.ende)].filter(Boolean).join(" bis ") },
          { titel: "Kündbar bis", wert: (b) => frist(b.vertrag.kuendigen_bis) },
          { titel: "Wiedervorlage", wert: (b) => frist(b.vertrag.erinnerung_am) },
          { titel: "Verantwortlich", wert: (b) => b.verantwortlich || "" },
        ],
        liste,
        { beiKlick: (b) => gehe(`beleg/${b.id}`), leertext: "Noch keine Verträge abgelegt" },
      ),
    ),
  );
}
