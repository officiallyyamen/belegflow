import { euro, gehe, h, hat, hole, melde, sende, siehtAlles, tag, vorTagen, z } from "../kern.js";
import { entscheide, knopf, kopf, leer, pille, reiter, schritte } from "../teile.js";
import { merkmale } from "./eingang.js";

const ARTEN = [["beleg", "Rechnungen"], ["erstattung", "Erstattungen"], ["anforderung", "Bestellungen"]];
const ZIEL = { beleg: "beleg", erstattung: "erstattung", anforderung: "anforderung" };

function angaben(e) {
  if (e.beleg) {
    return { titel: e.beleg.partner || e.beleg.lieferant, neben: [e.beleg.nummer, e.beleg.buchungstext].filter(Boolean).join(" · "), betrag: euro(e.beleg.brutto, e.beleg.waehrung), rest: e.beleg.faellig_am ? `fällig ${vorTagen(e.beleg.faellig_am)}` : "", zeichen: merkmale(e.beleg) };
  }
  return { titel: e.titel, neben: [e.person, e.lieferant].filter(Boolean).join(" · "), betrag: euro(e.summe), rest: e.leistung_am ? `bis ${tag(e.leistung_am)}` : e.hinweis || "", zeichen: null };
}

export async function seite([art = "beleg", gewaehlt = ""]) {
  const sicht = gewaehlt || (hat("freigabe") ? "meine" : siehtAlles() ? "alle" : "angefragt");
  const inhalt = h("div.freigabeliste");
  const f = z.zaehler?.freigaben || {};
  async function neu() {
    const liste = await hole("/freigaben", { art, sicht });
    alle.hidden = true;
    if (!liste.length) {
      const andere = sicht === "meine" ? (await hole("/freigaben", { art, sicht: siehtAlles() ? "alle" : "angefragt" })).filter((e) => e.status === "freigabe").length : 0;
      inhalt.replaceChildren(h("div.karte", leer(sicht === "meine" ? "Nichts wartet auf deine Freigabe" : "Keine Einträge"), andere ? h("p.mittig", h("a", { href: `#/${z.m}/freigaben/${art}/${siehtAlles() ? "alle" : "angefragt"}` }, `${andere} ${andere === 1 ? "wartet" : "warten"} bei anderen Personen`)) : null));
      return;
    }
    inhalt.replaceChildren(
      ...liste.map((e) => {
        const a = angaben(e);
        return h(
          "article.karte.freigabe",
          { onclick: (ereignis) => { if (!ereignis.target.closest("button, a")) gehe(`${ZIEL[art]}/${e.id}`); } },
          h("div.freigabekopf", h("div", h("a", { href: `#/${z.m}/${ZIEL[art]}/${e.id}` }, h("strong", a.titel || "Ohne Namen")), h("p.leise.klein", a.neben)), a.zeichen, h("div.zahl", h("strong.mittel", a.betrag), h("p.leise.klein", a.rest))),
          h("div.freigabefuss", schritte(e.freigabe), h("p.leise.klein", e.angefragt_von ? `Angefragt von ${e.angefragt_von}, ${vorTagen(e.angefragt_am)}` : ""), sicht === "meine" ? null : pille(e.status)),
          e.kann
            ? h(
                "div.reihe.rechtsan",
                knopf("Ablehnen", async () => { if (await entscheide(art, e.id, false)) await neu(); }, { art: "gefahr", bild: "x" }),
                knopf("Freigeben", async () => { if (await entscheide(art, e.id, true)) await neu(); }, { art: "haupt", bild: "check" }),
              )
            : null,
        );
      }),
    );
    const offen = liste.filter((e) => e.kann);
    alle.hidden = offen.length < 2;
    alle.onclick = async () => {
      const antwort = await sende("/freigaben/sammel", { eintraege: offen.map((e) => ({ art, id: e.id })) });
      melde(`${antwort.fertig.length} freigegeben${antwort.fehler.length ? `, ${antwort.fehler.length} nicht: ${antwort.fehler[0].grund}` : ""}`, antwort.fehler.length > 0);
      await neu();
    };
  }
  const alle = knopf("Alle freigeben", () => {}, { bild: "check" });
  await neu();
  return h(
    "div.seite",
    kopf("Freigaben", alle),
    reiter(ARTEN.map(([a, t]) => [`freigaben/${a}/${sicht}`, t, f[a]]), `freigaben/${art}/${sicht}`),
    h("div.umschalter", [["meine", "Mir zugewiesen"], ["angefragt", "Von mir angefragt"], siehtAlles() ? ["alle", "Alle"] : null].filter(Boolean).map(([s, t]) => h("a", { href: `#/${z.m}/freigaben/${art}/${s}`, class: s === sicht ? "an" : "" }, t))),
    inhalt,
  );
}
