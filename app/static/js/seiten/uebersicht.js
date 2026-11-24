import { adresse, euro, h, hat, hole, icon, loesche, rund, sende, siehtAlles, z } from "../kern.js";
import { balken, fortschritt, frage, knopf, leer, monate, pille, sicher, stamm } from "../teile.js";

let jahr = new Date().getFullYear();
let basis = "brutto";
let nach = "kostenstelle";

function liste(name, gruppen, leertext) {
  const zeilen = gruppen.flatMap(([gruppe, eintraege]) => eintraege.filter(([, zahl]) => zahl).map(([text, zahl, ziel, art]) => h("li", h("a", { href: adresse(ziel), class: art || "" }, h("span.leise", gruppe), h("span", text), h("span.anzahl", String(zahl)), icon("caret-right")))));
  return h("section.karte.arbeit", h("h2", name), zeilen.length ? h("ul", zeilen) : h("p.leise", leertext));
}

function aufgaben(n) {
  const { freigaben: f, eingang: e } = n;
  return liste(
    "Zu erledigen",
    [
      ["Eingang", e ? [["Überfällige Rechnungen", e.ueberfaellig, "eingang/rechnungen", "faellig"], ["Rechnungen", e.rechnungen, "eingang/rechnungen"], ["Erstattungen", e.erstattungen, "erstattungen/pruefen"], ["Verträge", e.vertraege, "eingang/vertraege"], ["Sonstige Dokumente", e.dokumente, "eingang/dokumente"], ["Fehlende Rechnungen", e.transaktionen, "karten/transaktionen"]] : []],
      ["Freigaben", [["Überfällige Rechnungen", f.ueberfaellig, "freigaben/beleg", "faellig"], ["Rechnungen", f.beleg, "freigaben/beleg"], ["Erstattungen", f.erstattung, "freigaben/erstattung"], ["Bestellanforderungen", f.anforderung, "freigaben/anforderung"]]],
      ["Zahlungen", n.zahlungen ? [["Überfällige Zahlungen", n.zahlungen.ueberfaellig, "zahlungen", "faellig"], ["Offene Zahlungen", n.zahlungen.offen, "zahlungen"]] : []],
      ["Verträge", [["Frist oder Wiedervorlage", n.vertraege, "vertraege"]]],
      ["Export", n.export ? [["Bereit zum Export", n.export.bereit, "export"], ["Nicht bereit", n.export.nicht_bereit, "export"]] : []],
    ],
    "Nichts offen",
  );
}

function beobachten(b) {
  return liste(
    "Zu beobachten",
    [
      ["Eingang", [["Fehlende Rechnungen", b.belege_fehlen, "karten/transaktionen"], ["Erwähnungen", b.erwaehnt, "uebersicht"]]],
      ["Freigaben", [["Meine Anfragen", b.angefragt, "freigaben/beleg/angefragt"], ["Abgelehnt", b.abgelehnt, "freigaben/beleg/angefragt", "faellig"], ["Erstattungen", b.erstattungen, "erstattungen/meine"], ["Bestellanforderungen", b.anforderungen, "anforderungen/meine"]]],
    ],
    "Nichts zu beobachten",
  );
}

function kartenliste(karten) {
  return h(
    "section",
    h("div.titelzeile.abschnitttitel", h("h2", "Meine Kreditkarten"), h("a.knopf", { href: adresse("karten/neu") }, icon("plus"), "Karte anlegen")),
    h(
      "div.bankkarten",
      karten.map((k) =>
        h(
          "a.bankkarte",
          { href: adresse("karten/transaktionen") },
          h("div.titelzeile", h("span", k.name), k.fehlende_belege ? pille("fehlt", `${k.fehlende_belege} fehlt`) : pille(k.status)),
          h("i.chipfeld"),
          h("div.titelzeile", h("span.nummernfeld", `•••• ${k.letzte4 || "––––"}`), h("div.rechtsbuendig", h("small", "Verfügbar"), h("strong", euro(Number(k.limit_monat) - Number(k.ausgegeben))))),
        ),
      ),
    ),
  );
}

function kennzahlen(k) {
  const werte = [
    ["Freigegebene Belege", String(k.belege)],
    ["Ohne Korrektur gelesen", k.gelesen_prozent === null ? "–" : `${k.gelesen_prozent} %`],
    ["Automatisch verarbeitet", k.automatik_prozent === null ? "–" : `${k.automatik_prozent} %`],
    ["Durchlauf im Schnitt", k.durchlauf_tage === null ? "–" : `${k.durchlauf_tage.toLocaleString("de-AT")} Tage`],
  ];
  return h("section", h("h2.abschnitttitel", "Letzte 90 Tage"), h("dl.zahlenband", werte.map(([n, w]) => h("div", h("dt", n), h("dd", w)))));
}

const NAMEN = { kostenstelle: "Kostenstelle", konto: "Konto", partner: "Partner" };

async function budget(neu) {
  const art = await frage("Auswertung anlegen", [{ name: "art", text: "Nach", art: "wahl", pflicht: true, optionen: Object.entries(NAMEN) }], { art: "kostenstelle" }, { text: "Weiter" });
  if (!art) return;
  const optionen = art.art === "partner" ? z.stamm.partner.map((p) => [p.id, p.name]) : stamm(art.art);
  const fertig = await frage(
    `Budget für ${NAMEN[art.art]}`,
    [
      { name: "wert", text: NAMEN[art.art], art: "wahl", pflicht: true, optionen },
      { name: "budget", text: "Budget im Jahr", art: "geld", pflicht: true },
    ],
    {},
    { speichern: (w) => sende("/budgets", { art: art.art, ...w }) },
  );
  if (fertig) neu();
}

function budgetzeile(b, neu) {
  const anteil = Number(b.verbraucht) / Math.max(Number(b.budget), 0.01);
  const entferne = async () => {
    if (!(await sicher("Auswertung entfernen", `${b.name} wird nicht mehr angezeigt.`, "Entfernen"))) return;
    await loesche(`/budgets/${b.id}`);
    neu();
  };
  return h(
    "li.budgetzeile",
    h("div", h("span", b.name), h("small.leise", NAMEN[b.art])),
    fortschritt(anteil),
    h("span.betrag", `${rund(b.verbraucht)} von ${rund(b.budget)}`),
    h("span.betrag", { class: anteil > 1 ? "rot" : "leise" }, `${Math.round(anteil * 100)} %`),
    hat("buchhaltung", "admin") ? knopf("", entferne, { art: "rund leise", bild: "x", titel: "Auswertung entfernen" }) : null,
  );
}

const wahl = (name, wert, optionen, setze, neu) => {
  const auswahl = h("select.still", { "aria-label": name }, optionen.map(([w, t]) => h("option", { value: w, selected: w === wert }, t)));
  auswahl.onchange = () => { setze(auswahl.value); neu(); };
  return auswahl;
};

function ausgaben(d, neu) {
  const jetzt = new Date();
  const laufend = jahr === jetzt.getFullYear();
  const monat = laufend ? jetzt.getMonth() : 11;
  const davor = monat ? Number(d.monate[monat - 1]) : 0;
  const unterschied = davor ? Math.round((Number(d.monate[monat]) / davor - 1) * 100) : null;
  return h(
    "section.karte.ausgaben",
    h(
      "div.titelzeile",
      h("h2", "Ausgaben"),
      h("div.reihe", wahl("Jahr", String(jahr), [0, 1, 2].map((v) => [String(jetzt.getFullYear() - v), String(jetzt.getFullYear() - v)]), (w) => { jahr = Number(w); }, neu), wahl("Beträge", basis, [["brutto", "Brutto"], ["netto", "Netto"]], (w) => { basis = w; }, neu)),
    ),
    h("div.hauptzahl", h("strong", euro(d.monate[monat])), h("span.leise", unterschied === null ? monate[monat] : `${monate[monat]}${laufend ? " bisher" : ""}, ${Math.abs(unterschied)} % ${unterschied < 0 ? "weniger" : "mehr"} als im ${monate[monat - 1]}`)),
    balken(d.monate, monate, rund, monat),
  );
}

function verteilung(d, neu) {
  const hoechster = Math.max(...d.verteilung.map((v) => Number(v.summe)), 1);
  return h(
    "section.karte",
    h("div.titelzeile", h("h2", `Verteilung ${jahr}`), wahl("Nach", nach, Object.entries(NAMEN), (w) => { nach = w; }, neu)),
    d.verteilung.length ? h("ul.verteilung", d.verteilung.map((v) => h("li", h("div.titelzeile", h("span", v.name), h("span.betrag", rund(v.summe))), fortschritt(Number(v.summe) / hoechster, false)))) : leer("Noch keine Buchungen", "chart-bar"),
  );
}

function budgets(d, neu) {
  return h(
    "section.karte",
    h("div.titelzeile", h("h2", `Budgets ${jahr}`), hat("buchhaltung", "admin") ? knopf("Budget anlegen", () => budget(neu), { bild: "plus" }) : null),
    d.budgets.length ? h("ul.budgetliste", d.budgets.map((b) => budgetzeile(b, neu))) : leer("Noch keine Budgets", "chart-bar"),
  );
}

export async function seite() {
  const knoten = h("div.seite.uebersicht");
  const neu = async () => {
    const d = await hole("/uebersicht", { jahr, basis, nach });
    const firma = z.ich.mandanten.find((m) => m.id === z.m);
    const alles = siehtAlles();
    knoten.replaceChildren(
      h("header", h("h1", new Date().toLocaleDateString("de-AT", { month: "long", year: "numeric" })), h("p.leise", firma?.name || "")),
      alles ? h("div.hauptreihe", ausgaben(d, neu), aufgaben(d.zaehler)) : aufgaben(d.zaehler),
      alles ? h("div.nebenreihe", beobachten(d.beobachten), verteilung(d, neu)) : beobachten(d.beobachten),
      alles ? budgets(d, neu) : "",
      d.karten.length ? kartenliste(d.karten) : "",
      alles ? kennzahlen(d.kennzahlen) : "",
    );
  };
  await neu();
  return knoten;
}
