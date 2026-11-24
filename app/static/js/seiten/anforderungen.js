import { adresse, euro, gehe, h, hat, heute, hole, icon, pfad, sende, siehtAlles, tag, versuche, zahlwert } from "../kern.js";
import { STATUS, anfordern, entscheide, feld, frage, knopf, kommentarfeld, kopf, lies, pille, reiter, schritte, sofort, stamm, tabelle, verlauf, zielwahl } from "../teile.js";

const ANGABEN = [
  { name: "lieferant", text: "Lieferant", pflicht: true, breit: true },
  { name: "titel", text: "Was wird gebraucht?", pflicht: true, breit: true },
  { name: "beschreibung", text: "Beschreibung und Grund", art: "lang" },
  { name: "leistung_am", text: "Gebraucht bis", art: "date" },
  { name: "kostenstelle", text: "Kostenstelle", art: "wahl" },
  { name: "konto", text: "Konto", art: "wahl" },
  { name: "netto", text: "Betrag netto (ohne Positionen)", art: "geld" },
  { name: "notiz", text: "Notiz für die Buchhaltung", art: "lang" },
];

function positionen(anfang = []) {
  const liste = h("div.stapel");
  const summe = h("strong");
  const rechne = () => {
    summe.textContent = euro(werte().reduce((s, p) => s + Number(p.menge) * Number(p.einzelpreis), 0));
  };
  const zeile = (p = {}) => {
    const knoten = h(
      "div.teilzeile",
      [["nummer", "Nr.", p.nummer], ["text", "Bezeichnung", p.text], ["menge", "Menge", p.menge], ["einzelpreis", "Einzelpreis", p.einzelpreis]].map(([n, t, w]) => h("label.feld", h("span", t), h("input", { name: n, value: w ?? "", inputMode: n === "menge" || n === "einzelpreis" ? "decimal" : "", oninput: rechne }))),
      knopf("", () => { knoten.remove(); rechne(); }, { art: "rund leise", bild: "x", titel: "Entfernen" }),
    );
    return knoten;
  };
  const werte = () =>
    [...liste.children]
      .map((k) => Object.fromEntries([...k.querySelectorAll("input")].map((e) => [e.name, e.name === "menge" || e.name === "einzelpreis" ? zahlwert(e.value) : e.value.trim()])))
      .filter((p) => p.text)
      .map((p) => ({ ...p, nummer: p.nummer || null }));
  liste.append(...(anfang.length ? anfang : [{}]).map(zeile));
  rechne();
  return { knoten: h("div.breit.stapel", h("div.titelzeile", h("h3", "Positionen"), summe), liste, knopf("Position", () => liste.append(zeile()), { bild: "plus", art: "leise" })), werte };
}

async function neuanlage() {
  const pos = positionen();
  const ziele = zielwahl();
  const felder = ANGABEN.map((a) => (a.art === "wahl" ? { ...a, optionen: stamm(a.name) } : a));
  const schritt1 = h("div.felder", felder.map((f) => feld(f, "")));
  const formular = h("form.karte.stapel", h("h2", "1. Was wird bestellt?"), schritt1, pos.knoten, h("h2", "2. Wer soll freigeben?"), h("p.leise", "Ohne Auswahl gilt der passende Workflow."), ziele.knoten, h("div.ende", h("a.knopf", { href: adresse("anforderungen/meine") }, "Abbrechen"), h("button.knopf.haupt", "Bestellung anfordern")));
  formular.elements.lieferant.addEventListener("change", () =>
    versuche(async () => {
      const lieferant = formular.elements.lieferant.value.trim();
      if (lieferant.length < 2) return;
      const v = await hole("/anforderungen/vorschlag", { lieferant });
      for (const n of ["konto", "kostenstelle"]) if (v[n] && !formular.elements[n].value) formular.elements[n].value = v[n];
    }),
  );
  formular.onsubmit = (e) => {
    e.preventDefault();
    versuche(async () => {
      const w = lies(formular, felder);
      const zeilen = pos.werte();
      const d = await sende("/anforderungen", { ...w, beschreibung: w.beschreibung || "", netto: zeilen.length ? null : w.netto, positionen: zeilen, ziele: ziele.werte() });
      gehe(`anforderung/${d.id}`);
    });
  };
  return h("div.seite.schmal", kopf("Neue Bestellanforderung"), formular);
}

export async function seite([sicht = "meine", status = ""]) {
  if (sicht === "neu") return neuanlage();
  const d = await hole("/anforderungen", { sicht, status });
  return h(
    "div.seite",
    kopf("Bestellanforderungen", knopf("Bestellung anfordern", () => gehe("anforderungen/neu"), { art: "haupt", bild: "plus" })),
    reiter([["anforderungen/meine", "Meine"], siehtAlles() ? ["anforderungen/alle", "Alle"] : null], `anforderungen/${sicht}`),
    h(
      "div.kacheln",
      ["freigabe", "freigegeben", "teilweise", "erfuellt", "abgelehnt"].map((s) => {
        const k = d.kacheln[s] || { anzahl: 0, summe: "0" };
        return h("a.karte.kachel", { href: adresse(`anforderungen/${sicht}/${status === s ? "" : s}`), class: status === s ? "an" : "" }, h("p.leise", STATUS[s][0]), h("strong.gross", String(k.anzahl)), h("p.leise.klein", euro(k.summe)));
      }),
    ),
    h(
      "div.karte.eng",
      tabelle(
        [
          { titel: "Bestellung", wert: (a) => h("div", h("strong", a.titel), h("p.leise.klein", [a.nummer, a.lieferant, a.person].filter(Boolean).join(" · "))) },
          { titel: "Status", wert: (a) => pille(a.status) },
          { titel: "Bis", wert: (a) => tag(a.leistung_am) },
          { titel: "Verrechnet", wert: (a) => euro(a.verrechnet), klasse: "zahl breitab" },
          { titel: "Netto", wert: (a) => h("strong", euro(a.netto)), klasse: "zahl" },
        ],
        d.eintraege,
        { beiKlick: (a) => gehe(`anforderung/${a.id}`), leertext: "Noch keine Bestellungen" },
      ),
    ),
  );
}

export async function einzeln([nummer]) {
  let a = await hole(`/anforderungen/${nummer}`);
  const wurzel = h("div.seite");
  const frisch = async () => neu(await hole(`/anforderungen/${nummer}`));
  async function annehmen() {
    const felder = [
      { name: "datum", text: "Datum", art: "date", pflicht: true },
      { name: "lieferschein", text: "Lieferschein" },
      ...a.positionen.map((p, i) => ({ name: `m${i}`, text: `${p.text} (bestellt ${p.menge}, da ${a.geliefert[i]})`, art: "zahl", breit: true })),
    ];
    const d = await frage("Wareneingang", felder, { datum: heute() }, {
      speichern: (w) => sende(`/anforderungen/${a.id}/wareneingang`, { datum: w.datum, lieferschein: w.lieferschein, mengen: Object.fromEntries(a.positionen.map((_, i) => [String(i), w[`m${i}`]]).filter(([, m]) => m)) }),
    });
    if (d) neu(d);
  }
  async function aendern() {
    const pos = positionen(a.positionen);
    const felder = [...ANGABEN.map((f) => (f.art === "wahl" ? { ...f, optionen: stamm(f.name) } : f)), { knoten: pos.knoten }];
    const d = await frage("Bestellung ändern", felder, a, { breit: true, speichern: (w) => sende(`/anforderungen/${a.id}`, { ...w, positionen: pos.werte(), netto: pos.werte().length ? null : w.netto }, "PATCH") });
    if (d) neu(d);
  }
  function neu(d) {
    if (d?.id) a = d;
    const bestellt = ["freigegeben", "teilweise", "erfuellt"].includes(a.status);
    const anteil = Number(a.verrechnet) / Math.max(Number(a.netto), 0.01);
    wurzel.replaceChildren(
      kopf(
        a.titel,
        h("a.knopf", { href: pfad(`/anforderungen/${a.id}/pdf`), target: "_blank", rel: "noopener" }, icon("file-text"), "PDF"),
        a.darf_aendern ? knopf("Ändern", aendern, { bild: "pencil-simple" }) : null,
        a.status === "neu" && (a.eigen || hat("buchhaltung", "admin")) ? knopf("Freigabe anfordern", async () => { if (await anfordern("anforderung", a.id, a.workflow, false)) await frisch(); }, { art: "haupt", bild: "paper-plane-tilt" }) : null,
        a.status === "neu" && hat("freigabe") && !a.eigen ? knopf("Sofort freigeben", async () => { if (await sofort("anforderung", a.id)) await frisch(); }, { bild: "check" }) : null,
        a.status === "freigabe" && (a.eigen || hat("buchhaltung", "admin")) ? knopf("Zurückziehen", async () => { await sende(`/freigaben/anforderung/${a.id}/zurueckziehen`); await frisch(); }, { bild: "arrow-u-up-left" }) : null,
        a.freigabe_moeglich
          ? [
              knopf("Ablehnen", async () => { if (await entscheide("anforderung", a.id, false)) await frisch(); }, { art: "gefahr", bild: "x" }),
              knopf("Freigeben", async () => { if (await entscheide("anforderung", a.id, true)) await frisch(); }, { art: "haupt", bild: "check" }),
            ]
          : null,
        bestellt && a.positionen.length && (a.eigen || hat("buchhaltung", "admin")) ? knopf("Wareneingang", annehmen, { bild: "package", art: "haupt" }) : null,
        a.status === "abgelehnt" && (a.eigen || hat("buchhaltung", "admin")) ? knopf("Wieder öffnen", async () => { await sende(`/freigaben/anforderung/${a.id}/oeffnen`); await frisch(); }, { bild: "arrow-u-up-left" }) : null,
      ),
      h("div.reihe", pille(a.status), a.nummer ? h("strong", a.nummer) : null, h("span.leise", `${a.lieferant} · ${a.person}`)),
      h(
        "div.zweispaltig.breitlinks",
        h(
          "section.stapel",
          h("div.kacheln", h("div.karte.kachel", h("p.leise", "Bestellt netto"), h("strong.mittel", euro(a.netto))), h("div.karte.kachel", h("p.leise", "Verrechnet"), h("strong.mittel", euro(a.verrechnet))), h("div.karte.kachel", { class: anteil > 1 ? "rot" : "" }, h("p.leise", "Offen"), h("strong.mittel", euro(Number(a.netto) - Number(a.verrechnet))))),
          a.beschreibung ? h("div.karte", h("p.vorformat", a.beschreibung)) : null,
          a.positionen.length
            ? h("div.karte.eng", tabelle([
                { titel: "Nr.", wert: (p) => p.nummer || "" },
                { titel: "Bezeichnung", wert: (p) => p.text },
                { titel: "Menge", wert: (p) => p.menge, klasse: "zahl" },
                { titel: "Geliefert", wert: (p) => a.geliefert[a.positionen.indexOf(p)], klasse: "zahl" },
                { titel: "Preis", wert: (p) => euro(p.einzelpreis), klasse: "zahl" },
                { titel: "Summe", wert: (p) => euro(Number(p.menge) * Number(p.einzelpreis)), klasse: "zahl" },
              ], a.positionen))
            : null,
          h("h2", "Rechnungen"),
          h("div.karte.eng", tabelle([{ titel: "Rechnung", wert: (r) => r.nummer || `Beleg ${r.id}` }, { titel: "Datum", wert: (r) => tag(r.datum) }, { titel: "Status", wert: (r) => pille(r.status) }, { titel: "Netto", wert: (r) => euro(r.netto), klasse: "zahl" }], a.rechnungen, { beiKlick: (r) => (siehtAlles() ? gehe(`beleg/${r.id}`) : null), leertext: "Noch keine Rechnung verknüpft" })),
        ),
        h(
          "aside.stapel",
          a.freigabe.length ? h("div.karte", h("h3", "Freigabe"), schritte(a.freigabe)) : null,
          h("div.karte", h("h3", "Angaben"), h("dl.paare", [["Kostenstelle", a.kostenstelle], ["Konto", a.konto], ["Gebraucht bis", tag(a.leistung_am)], ["Notiz", a.notiz]].filter(([, w]) => w).map(([n, w]) => [h("dt", n), h("dd", w)]))),
          a.wareneingaenge.length ? h("div.karte", h("h3", "Wareneingänge"), a.wareneingaenge.map((w) => h("p.klein", `${tag(w.datum)} ${w.lieferschein || ""}: ${Object.values(w.mengen).join(", ")} von ${w.von}`))) : null,
          h("div.karte", h("h3", "Verlauf"), kommentarfeld(async (text) => neu(await sende(`/anforderungen/${a.id}/kommentar`, { text }))), verlauf(a.verlauf)),
        ),
      ),
    );
  }
  neu();
  return wurzel;
}
