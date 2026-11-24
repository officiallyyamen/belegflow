import { adresse, euro, gehe, h, hat, hole, icon, loesche, melde, pfad, ruf, sende, tag, z } from "../kern.js";
import { begruende, fortschritt, frage, knopf, kopf, leer, personen, pille, reiter, stamm, tabelle } from "../teile.js";
import { eingangsreiter } from "./eingang.js";
import { schicke, waehleDatei } from "./beleg.js";

const felder = (verwaltet) => [
  { name: "name", text: "Name der Karte", pflicht: true },
  { name: "art", text: "Art", art: "wahl", leer: "Virtuell", optionen: [["physisch", "Physisch"], ["einmalig", "Einmalig"]] },
  { name: "limit_monat", text: "Limit pro Monat", art: "geld", pflicht: true },
  { name: "limit_zahlung", text: "Limit pro Zahlung", art: "geld" },
  ...(verwaltet
    ? [
        { name: "inhaber_id", text: "Inhaber:in", art: "wahl", zahlen: true, optionen: personen() },
        { name: "letzte4", text: "Letzte vier Stellen", muster: "\\d{4}" },
        { name: "gueltig_bis", text: "Gültig bis", art: "date" },
        { name: "konto", text: "Buchungsregel: Konto", art: "wahl", optionen: stamm("konto") },
        { name: "kostenstelle", text: "Buchungsregel: Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") },
      ]
    : []),
  { name: "grund", text: "Wofür?", breit: true },
];

async function neueKarte() {
  const verwaltet = hat("buchhaltung", "admin");
  const k = await frage(verwaltet ? "Karte anlegen" : "Karte beantragen", felder(verwaltet), {}, {
    speichern: (w) => sende("/karten", { ...w, art: w.art || "virtuell", grund: w.grund || "" }),
    hinweis: verwaltet ? "Die Karte selbst gibt die Bank aus, hier wird sie verwaltet." : "",
  });
  if (k) melde(verwaltet ? "Karte angelegt" : "Karte beantragt");
}

function kartenbild(k, neu) {
  const aendern = (werte) => async () => {
    await sende(`/karten/${k.id}`, werte, "PATCH");
    await neu();
  };
  return h(
    "article.karte.firmenkarte",
    h("div.plastik.gross", h("div.titelzeile", h("strong", k.name), icon("credit-card")), h("p.nummer", `•••• •••• •••• ${k.letzte4 || "––––"}`), h("div.titelzeile.klein", h("span", k.inhaber), h("span", k.gueltig_bis ? `bis ${tag(k.gueltig_bis)}` : ""))),
    h("div.titelzeile", pille(k.status), k.fehlende_belege ? pille("fehlt", `${k.fehlende_belege} ${k.fehlende_belege === 1 ? "Beleg fehlt" : "Belege fehlen"}`) : null),
    h("p", h("strong", euro(k.ausgegeben)), h("span.leise", ` von ${euro(k.limit_monat)}`)),
    fortschritt(Number(k.ausgegeben) / Math.max(Number(k.limit_monat), 0.01)),
    k.grund ? h("p.leise.klein", k.grund) : null,
    hat("buchhaltung", "admin")
      ? h(
          "div.reihe",
          k.status === "beantragt" ? knopf("Freischalten", async () => {
            const w = await frage("Karte freischalten", [{ name: "letzte4", text: "Letzte vier Stellen", muster: "\\d{4}", pflicht: true }]);
            if (w) await aendern({ status: "aktiv", letzte4: w.letzte4 })();
          }, { art: "haupt" }) : null,
          k.status === "beantragt" ? knopf("Ablehnen", aendern({ status: "abgelehnt" })) : null,
          k.status === "aktiv" ? knopf("Sperren", aendern({ status: "gesperrt" }), { bild: "lock" }) : null,
          k.status === "gesperrt" ? knopf("Entsperren", aendern({ status: "aktiv" }), { bild: "lock-open" }) : null,
          knopf("", async () => {
            const w = await frage("Karte ändern", felder(true).filter((f) => !["art", "inhaber_id", "grund"].includes(f.name)), k, { speichern: (werte) => sende(`/karten/${k.id}`, werte, "PATCH") });
            if (w) await neu();
          }, { art: "rund leise", bild: "pencil-simple", titel: "Ändern" }),
        )
      : null,
  );
}

async function transaktionen(filter) {
  const kasten = h("div.karte.eng");
  async function neu() {
    const liste = await hole("/transaktionen", { status: filter === "alle" ? "" : "fehlt" });
    kasten.replaceChildren(
      tabelle(
        [
          { titel: "Händler", wert: (t) => h("div", h("strong", t.haendler), h("p.leise.klein", `${t.karte} •••• ${t.letzte4} · ${t.inhaber}`)) },
          { titel: "Datum", wert: (t) => tag(t.datum) },
          { titel: "Status", wert: (t) => h("div.stapel.eng", pille(t.status), t.hinweise.map((x) => h("span.rot.klein", x))) },
          {
            titel: "Beleg",
            wert: (t) =>
              t.beleg
                ? h("a", { href: adresse(`beleg/${t.beleg.id}`) }, `${t.beleg.lieferant || "Beleg"} ${t.beleg.nummer || ""}`)
                : h("div.reihe", t.vorschlaege.map((v) => knopf(`${v.lieferant} ${v.nummer || ""}`, async () => { await sende(`/transaktionen/${t.id}/beleg`, { beleg_id: v.id }); await neu(); }, { bild: v.sicher ? "check" : "link" }))),
          },
          { titel: "Betrag", wert: (t) => h("strong", euro(t.betrag, t.waehrung)), klasse: "zahl" },
          {
            titel: "",
            wert: (t) =>
              t.status === "fehlt"
                ? h(
                    "div.reihe",
                    knopf("", () => waehleDatei(async (d) => { await schicke(`/transaktionen/${t.id}/datei`, d); await neu(); }), { art: "rund", bild: "upload-simple", titel: "Beleg hochladen" }),
                    knopf("", async () => {
                      const grund = await begruende("Ohne Beleg abschließen", "Warum gibt es keinen Beleg?");
                      if (!grund) return;
                      await sende(`/transaktionen/${t.id}/ohne-beleg`, { grund });
                      await neu();
                    }, { art: "rund leise", bild: "minus", titel: "Ohne Beleg" }),
                  )
                : t.beleg && hat("buchhaltung", "admin") ? knopf("", async () => { await loesche(`/transaktionen/${t.id}/beleg`); await neu(); }, { art: "rund leise", bild: "x", titel: "Zuordnung lösen" }) : "",
          },
        ],
        liste,
        { leertext: filter === "alle" ? "Noch keine Transaktionen" : "Alle Belege sind da" },
      ),
    );
  }
  await neu();
  return [kasten, neu];
}

export async function seite([welche = "karten", filter = ""]) {
  if (welche === "neu") {
    await neueKarte();
    gehe("karten");
    return h("div.seite");
  }
  const oben = reiter([["karten", "Karten"], ["karten/transaktionen", "Fehlende Belege", z.zaehler?.eingang?.transaktionen], ["karten/transaktionen/alle", "Alle Transaktionen"]], welche === "karten" ? "karten" : `karten/transaktionen${filter ? `/${filter}` : ""}`);
  if (welche === "transaktionen") {
    const [kasten, neu] = await transaktionen(filter);
    const einlesen = knopf("CSV einlesen", () => waehleDatei(async (datei) => {
      const e = await schicke("/transaktionen/import", datei);
      melde(`${e.neu} neu, ${e.zugeordnet} zugeordnet, ${e.bekannt} schon bekannt${e.uebersprungen.length ? `, übersprungen: ${e.uebersprungen.join("; ")}` : ""}`, e.uebersprungen.length > 0);
      await neu();
    }, ".csv"), { bild: "upload-simple", art: "haupt" });
    return h("div.seite", kopf("Kreditkarten", hat("buchhaltung", "admin") ? einlesen : null), oben, kasten);
  }
  const kasten = h("div.kartenraster");
  const neu = async () => {
    const liste = await hole("/karten");
    kasten.replaceChildren(...(liste.length ? liste.map((k) => kartenbild(k, neu)) : [leer("Noch keine Karten", "credit-card")]));
  };
  await neu();
  return h("div.seite", kopf("Kreditkarten", knopf(hat("buchhaltung", "admin") ? "Karte anlegen" : "Karte beantragen", async () => { await neueKarte(); await neu(); }, { art: "haupt", bild: "plus" })), oben, kasten);
}

export { eingangsreiter, pfad, ruf };
