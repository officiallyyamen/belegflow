import { h, hole, melde, merke, ruf, versuche, z } from "./kern.js";
import { anmeldeseite, baueRahmen, frischeZaehler, markiere } from "./rahmen.js";
import * as anforderungen from "./seiten/anforderungen.js";
import * as archiv from "./seiten/archiv.js";
import * as beleg from "./seiten/beleg.js";
import * as eingang from "./seiten/eingang.js";
import * as einstellungen from "./seiten/einstellungen.js";
import * as erstattungen from "./seiten/erstattungen.js";
import * as exporte from "./seiten/exporte.js";
import * as freigaben from "./seiten/freigaben.js";
import * as karten from "./seiten/karten.js";
import * as partner from "./seiten/partner.js";
import * as uebersicht from "./seiten/uebersicht.js";
import * as zahlungen from "./seiten/zahlungen.js";
import { leer } from "./teile.js";

const wurzel = document.getElementById("app");
const SEITEN = {
  uebersicht: uebersicht.seite,
  eingang: eingang.seite,
  beleg: beleg.seite,
  vergleich: beleg.vergleich,
  freigaben: freigaben.seite,
  zahlungen: zahlungen.seite,
  export: exporte.seite,
  archiv: archiv.seite,
  vertraege: archiv.vertraege,
  erstattungen: erstattungen.seite,
  erstattung: erstattungen.einzeln,
  anforderungen: anforderungen.seite,
  anforderung: anforderungen.einzeln,
  karten: karten.seite,
  partner: partner.seite,
  nachrichten: partner.nachrichten,
  einstellungen: einstellungen.seite,
  profil: einstellungen.profil,
};
let lauf = 0;

async function zeige() {
  const meiner = ++lauf;
  if (!z.ich) {
    wurzel.replaceChildren(anmeldeseite(beginne));
    return;
  }
  const [mandant, name = "uebersicht", ...teile] = decodeURI(location.hash.replace(/^#\/?/, "")).split("/");
  const nummer = Number(mandant);
  const bekannt = z.ich.mandanten.some((m) => m.id === nummer);
  if (!bekannt) {
    if (!z.ich.mandanten.length) {
      wurzel.replaceChildren(leer("Du bist noch keinem Mandanten zugeordnet", "buildings"));
      return;
    }
    const letzter = Number(merke("mandant"));
    const ziel = z.ich.mandanten.find((m) => m.id === letzter) || z.ich.mandanten.toSorted((a, b) => a.id - b.id)[0];
    location.replace(`#/${ziel.id}/uebersicht`);
    return;
  }
  if (z.m !== nummer || !z.stamm) {
    z.m = nummer;
    z.stamm = await hole("/stammdaten");
    merke("mandant", String(nummer));
    wurzel.replaceChildren(baueRahmen());
  }
  if (meiner !== lauf) return;
  markiere(name, teile);
  const flaeche = document.getElementById("inhalt");
  frischeZaehler();
  const seite = SEITEN[name] || SEITEN.uebersicht;
  try {
    const knoten = await seite(teile);
    if (meiner !== lauf) return;
    flaeche.replaceChildren(knoten);
    flaeche.scrollTop = 0;
  } catch (fehler) {
    if (fehler.status === 401) {
      z.ich = null;
      zeige();
      return;
    }
    if (meiner === lauf) flaeche.replaceChildren(h("div.seite", leer(fehler.message, "warning-circle")));
  }
}

async function beginne() {
  z.ich = await ruf("/api/ich");
  z.stamm = null;
  await zeige();
}

window.addEventListener("hashchange", () => versuche(zeige));
window.addEventListener("belegflow-neu", () => versuche(zeige));
window.addEventListener("belegflow-stamm", async () => {
  z.stamm = await hole("/stammdaten");
});
document.documentElement.dataset.farbe = merke("farbe") || "hell";
ruf("/api/ich").then(
  (ich) => {
    z.ich = ich;
    versuche(zeige);
  },
  (fehler) => {
    if (fehler.status !== 401) melde(fehler.message, true);
    zeige();
  },
);
