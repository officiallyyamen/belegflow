import { adresse, euro, gehe, h, hat, hole, icon, loesche, melde, pfad, ruf, sende, siehtAlles, tag, versuche, z, zahlwert } from "../kern.js";
import { anfordern, begruende, bildansicht, entscheide, feld, fenster, frage, knopf, kommentarfeld, kopf, leer, lies, pille, reiter, schritte, sicher, sofort, stamm, tabelle, verlauf } from "../teile.js";

const ARTEN = { auslage: ["Auslage", "receipt"], bewirtung: ["Bewirtung", "fork-knife"], taggeld: ["Verpflegung und Nächtigung", "bed"], kilometer: ["Kilometergeld", "car"] };
let saetze = null;

export async function seite([sicht = "meine"]) {
  if (sicht === "neu") {
    const neu = await frage("Reise oder Auslage", [{ name: "titel", text: "Titel", pflicht: true, platz: "Kundentermin Linz" }, { name: "hinweis", text: "Hinweis", art: "lang" }], {}, { text: "Anlegen", speichern: (w) => sende("/erstattungen", w) });
    gehe(neu ? `erstattung/${neu.id}` : "erstattungen/meine");
    return h("div.seite");
  }
  const liste = await hole("/erstattungen", { sicht });
  const gruppe = (...arten) => liste.filter((e) => arten.includes(e.status));
  const summe = (eintraege) => euro(eintraege.reduce((s, e) => s + Number(e.summe), 0));
  const entwuerfe = gruppe("entwurf", "zurueck");
  const offen = gruppe("pruefung", "freigabe");
  const fertig = gruppe("freigegeben", "exportiert");
  const rest = liste.filter((e) => ![...entwuerfe, ...offen, ...fertig].includes(e));
  const ueberblick = (text, betrag, farbe) => h("div.karte.ueberblick", h("span", text), h("strong.gross", { class: farbe }, betrag));
  const karte = (e) =>
    h("a.karte.erstattung", { href: adresse(`erstattung/${e.id}`), class: e.status === "zurueck" ? "rotkarte" : "" }, h("div", pille(e.status)), h("p.leise.klein", sicht === "meine" ? tag(e.erstellt_am) : `${e.person}, ${tag(e.erstellt_am)}`), h("span.titelunten", e.titel), h("strong.mittel", euro(e.summe)));
  const abschnitt = (bild, text, eintraege, neu) =>
    eintraege.length || neu ? h("section", h("h2.abschnittstitel", icon(bild), text, h("span.leise", String(eintraege.length))), h("div.kachelreihe.schmal", neu ? h("a.neukachel", { href: adresse("erstattungen/neu") }, icon("plus"), "Erstattung erstellen") : null, eintraege.map(karte))) : null;
  return h(
    "div.seite",
    kopf("Erstattungen"),
    reiter([["erstattungen/meine", "Meine"], siehtAlles() ? ["erstattungen/pruefen", "Zu prüfen", z.zaehler?.eingang?.erstattungen] : null, siehtAlles() ? ["erstattungen/alle", "Alle"] : null], `erstattungen/${sicht}`),
    sicht === "pruefen"
      ? null
      : h("section", h("h2.abschnittstitel", icon("chart-bar"), "Überblick"), h("div.kachelreihe.schmal", ueberblick(entwuerfe.length === 1 ? "1 Entwurf" : `${entwuerfe.length} Entwürfe`, summe(entwuerfe), ""), ueberblick(offen.length === 1 ? "1 offene Erstattung" : `${offen.length} offene Erstattungen`, summe(offen), "warntext"), ueberblick(fertig.length === 1 ? "1 freigegebene Erstattung" : `${fertig.length} freigegebene Erstattungen`, summe(fertig), "gut"))),
    abschnitt("pencil-simple", "Entwürfe", entwuerfe, sicht === "meine"),
    abschnitt("clock", "Offen", offen),
    abschnitt("check-circle", "Freigegeben", fertig),
    abschnitt("archive", "Weitere", rest),
    liste.length || sicht === "meine" ? null : leer("Nichts offen", "check-circle"),
  );
}

function dateifeld() {
  const eingabe = h("input", { type: "file", name: "datei", accept: ".pdf,.png,.jpg,.jpeg" });
  return { eingabe, knoten: h("label.feld.breit", h("span", "Beleg (PDF oder Foto)"), eingabe) };
}

async function auslage(nummer, art, fertig, vorher = null) {
  const datei = dateifeld();
  const d = vorher?.daten || {};
  const felder = [
    ...(vorher ? [] : [{ knoten: datei.knoten }]),
    { name: "titel", text: "Bezeichnung", hinweis: vorher ? "" : "Leer lassen, um den Beleg auszulesen" },
    { name: "datum", text: "Datum", art: "date" },
    { name: "betrag", text: "Betrag brutto", art: "geld" },
    { name: "ust", text: "USt", art: "geld" },
    { name: "waehrung", text: "Währung", platz: "EUR" },
    { name: "kurs", text: "Kurs", art: "zahl", hinweis: "Leer: Kurs der EZB" },
    { name: "grund", text: "Anlass", breit: true },
    ...(art === "bewirtung" ? [{ name: "extern", text: "Bewirtete Personen (extern)", breit: true }, { name: "intern", text: "Teilnehmende (intern)", breit: true }, { name: "trinkgeld", text: "Trinkgeld", art: "geld" }, { name: "ort", text: "Lokal" }] : []),
    { name: "eigenbeleg", text: "Kein Beleg? Begründung für den Eigenbeleg", breit: true },
  ];
  const ergebnis = await frage(ARTEN[art][0], felder, { ...d, titel: vorher?.titel, datum: vorher?.datum }, {
    breit: true,
    speichern: (w) => speichere(nummer, art, w, datei.eingabe.files[0], vorher),
  });
  if (ergebnis) fertig(ergebnis);
}

function speichere(nummer, art, w, datei, vorher) {
  const { titel, datum, ...angaben } = w;
  const sauber = Object.fromEntries(Object.entries(angaben).filter(([, wert]) => wert !== null && wert !== ""));
  if (vorher) return ruf(pfad(`/erstattungen/${nummer}/posten/${vorher.id}`), "PATCH", { titel: titel || "", datum, daten: sauber });
  const daten = new FormData();
  daten.append("art", art);
  daten.append("titel", titel || "");
  if (datum) daten.append("datum", datum);
  daten.append("angaben", JSON.stringify(sauber));
  if (datei) daten.append("datei", datei);
  return ruf(pfad(`/erstattungen/${nummer}/posten`), "POST", daten);
}

async function kilometer(nummer, fertig) {
  const felder = [
    { name: "start", text: "Start", pflicht: true },
    { name: "ziel", text: "Ziel", pflicht: true },
    { name: "stopp", text: "Zwischenstopps, mit Komma getrennt", breit: true },
    { name: "datum", text: "Datum", art: "date", pflicht: true },
    { name: "km", text: "Kilometer (eine Strecke)", art: "zahl", pflicht: true },
    { name: "fahrzeug", text: "Fahrzeug", art: "wahl", leer: "PKW", optionen: [["motorrad", "Motorrad"], ["fahrrad", "Fahrrad"]] },
    { name: "mitfahrer", text: "Mitfahrende", art: "zahl", zahlen: true },
    { name: "hin_zurueck", text: "Hin und zurück", art: "haken" },
    { name: "grund", text: "Anlass", breit: true },
  ];
  const ergebnis = await frage("Kilometergeld", felder, {}, {
    breit: true,
    speichern: ({ stopp, fahrzeug, ...w }) => speichere(nummer, "kilometer", { ...w, titel: "", fahrzeug: fahrzeug || "pkw", stopps: stopp ? stopp.split(",").map((s) => s.trim()) : [] }),
  });
  if (ergebnis) fertig(ergebnis);
}

async function taggeld(nummer, fertig) {
  saetze ||= await hole("/erstattungen/laender");
  const etappen = h("div.stapel");
  const mahlzeiten = h("div.mahlzeiten");
  const ergebnis = h("div.karte.vorschau", h("p.leise", "Trage Beginn und Ende ein"));
  const laenderwahl = (wert = "Österreich") => h("select", { "aria-label": "Land", onchange: rechne }, saetze.laender.map((l) => h("option", { value: l, selected: l === wert }, l)));
  const etappe = (land, erste = false) => {
    const zeile = h("div.reihe", laenderwahl(land), h("input", { type: "datetime-local", "aria-label": "Beginn der Etappe", onchange: rechne }), erste ? null : knopf("", () => { zeile.remove(); rechne(); }, { art: "rund leise", bild: "x", titel: "Entfernen" }));
    return zeile;
  };
  const ende = h("input", { type: "datetime-local", "aria-label": "Ende der Reise", onchange: rechne });
  const nacht = h("input", { type: "number", min: 0, max: 60, value: 0, "aria-label": "Nächte", onchange: rechne });
  const nachtland = laenderwahl();
  const grund = h("input", { type: "text", "aria-label": "Anlass" });
  const los = h("button.knopf.haupt", { type: "button", disabled: true, textContent: "Übernehmen" });
  function werte() {
    const liste = [...etappen.children].map((e) => ({ land: e.querySelector("select").value, von: e.querySelector("input").value })).filter((e) => e.von);
    const gewaehlt = {};
    for (const feldchen of mahlzeiten.querySelectorAll("input:checked")) (gewaehlt[feldchen.dataset.tag] ||= []).push(feldchen.value);
    return { etappen: liste, ende: ende.value, mahlzeiten: gewaehlt, naechte: Number(nacht.value) ? [{ land: nachtland.value, anzahl: Number(nacht.value) }] : [], ...(grund.value.trim() ? { grund: grund.value.trim() } : {}) };
  }
  function tage() {
    const w = werte();
    if (!w.etappen.length || !w.ende) return;
    const liste = [];
    for (let t = new Date(w.etappen[0].von); t < new Date(w.ende) && liste.length < 60; t = new Date(t.getTime() + 86400000)) liste.push(new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 10));
    const schluessel = liste.join();
    if (mahlzeiten.dataset.tage === schluessel) return;
    mahlzeiten.dataset.tage = schluessel;
    mahlzeiten.replaceChildren(
      h("p.leise.klein", "Vom Arbeitgeber bezahlte Mahlzeiten"),
      ...liste.map((t) => h("div.reihe", h("span", tag(t)), [["mittag", "Mittag"], ["abend", "Abend"]].map(([m, n]) => h("label.haken", h("input", { type: "checkbox", value: m, "data-tag": t, onchange: rechne }), n)))),
    );
  }
  async function rechne() {
    tage();
    const w = werte();
    if (!w.etappen.length || !w.ende) return;
    try {
      const p = await ruf(pfad("/erstattungen/rechnen"), "POST", { art: "taggeld", daten: w });
      ergebnis.replaceChildren(h("div.titelzeile", h("strong", "Ergebnis"), h("strong.mittel", euro(p.betrag))), ...p.zeilen.map((x) => h("p.titelzeile.klein", h("span", `${x.tag.length === 10 && x.tag[4] === "-" ? tag(x.tag) : x.tag} ${x.zwoelftel ? `${x.zwoelftel}/12 ${x.land}` : ""}`), h("span", euro(x.betrag)))));
      los.disabled = false;
    } catch (fehler) {
      ergebnis.replaceChildren(h("p.rot", fehler.message));
      los.disabled = true;
    }
  }
  etappen.append(etappe("Österreich", true));
  const kasten = fenster(
    "Verpflegung und Nächtigung",
    h(
      "div.stapel",
      h("p.leise.klein", "Jede Etappe beginnt mit dem Grenzübertritt."),
      etappen,
      knopf("Weitere Etappe", () => etappen.append(etappe("Deutschland")), { bild: "plus", art: "leise" }),
      h("label.feld", h("span", "Ende der Reise"), ende),
      h("div.reihe", h("label.feld", h("span", "Nächte (pauschal)"), nacht), h("label.feld", h("span", "Land der Nächte"), nachtland)),
      mahlzeiten,
      h("label.feld", h("span", "Anlass"), grund),
      ergebnis,
      h("p.leise.klein", `Sätze: ${saetze.quelle}, Stand ${tag(saetze.abgerufen)}`),
      h("div.ende", los),
    ),
    { breit: true },
  );
  los.onclick = () =>
    versuche(async () => {
      const antwort = await speichere(nummer, "taggeld", { titel: "", ...werte() });
      kasten.close();
      fertig(antwort);
    });
}

function postenzeile(e, p, neu) {
  const [name, bild] = ARTEN[p.art];
  const pruefen = e.darf_pruefen;
  return h(
    "article.posten",
    { class: p.ausgeschlossen ? "aus" : "" },
    h("span.bild", icon(bild)),
    h(
      "div",
      h("strong", p.titel || name),
      h("p.leise.klein", [name, tag(p.datum), p.daten.grund, p.daten.extern, p.daten.waehrung && p.daten.waehrung !== "EUR" ? `${p.daten.betrag} ${p.daten.waehrung}` : null].filter(Boolean).join(" · ")),
      p.art === "taggeld" && p.rechnung.length ? h("details.klein", h("summary", "Rechnung"), p.rechnung.map((x) => h("p.titelzeile", h("span", `${x.tag}${x.land ? `: ${x.zwoelftel}/12 ${x.land}` : ""}`), h("span", euro(x.betrag))))) : null,
      p.daten.eigenbeleg ? h("p.klein", icon("warning"), ` Eigenbeleg: ${p.daten.eigenbeleg}`) : null,
      pruefen
        ? h(
            "div.reihe",
            feld({ name: "konto", text: "Konto", art: "wahl", optionen: stamm("konto") }, p.konto, async (w) => versuche(async () => neu(await ruf(pfad(`/erstattungen/${e.id}/posten/${p.id}`), "PATCH", { konto: w || null })))),
            feld({ name: "kostenstelle", text: "Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") }, p.kostenstelle, async (w) => versuche(async () => neu(await ruf(pfad(`/erstattungen/${e.id}/posten/${p.id}`), "PATCH", { kostenstelle: w || null })))),
          )
        : null,
    ),
    h("strong", euro(p.betrag)),
    h(
      "div.reihe",
      p.dateityp ? knopf("", () => fenster(p.dateiname, bildansicht(pfad(`/erstattungen/${e.id}/posten/${p.id}/bild`), { datei: pfad(`/erstattungen/${e.id}/posten/${p.id}/datei`) }), { breit: true }), { art: "rund leise", bild: "eye", titel: "Beleg ansehen" }) : null,
      e.darf_aendern && ["auslage", "bewirtung"].includes(p.art) ? knopf("", () => auslage(e.id, p.art, neu, p), { art: "rund leise", bild: "pencil-simple", titel: "Ändern" }) : null,
      e.darf_aendern ? knopf("", async () => neu(await loesche(`/erstattungen/${e.id}/posten/${p.id}`)), { art: "rund leise", bild: "trash", titel: "Entfernen" }) : null,
      pruefen ? knopf(p.ausgeschlossen ? "Aufnehmen" : "Ausschließen", async () => neu(await ruf(pfad(`/erstattungen/${e.id}/posten/${p.id}`), "PATCH", { ausgeschlossen: !p.ausgeschlossen })), { art: "leise" }) : null,
    ),
  );
}

export async function einzeln([nummer]) {
  let e = await hole(`/erstattungen/${nummer}`);
  const wurzel = h("div.seite");
  const frisch = async () => neu(await hole(`/erstattungen/${nummer}`));
  function neu(d) {
    if (d?.id) e = d;
    const knoepfe = [h("a.knopf", { href: pfad(`/erstattungen/${e.id}/pdf`), target: "_blank", rel: "noopener" }, icon("file-text"), "PDF")];
    if (e.darf_aendern) {
      knoepfe.push(
        knopf("Verwerfen", async () => {
          if (!(await sicher("Erstattung verwerfen", "Alle Posten werden entfernt.", "Verwerfen"))) return;
          await loesche(`/erstattungen/${e.id}`);
          gehe("erstattungen/meine");
        }, { bild: "trash" }),
        knopf("Einreichen", async () => { neu(await sende(`/erstattungen/${e.id}/einreichen`)); melde("Eingereicht"); }, { art: "haupt", bild: "paper-plane-tilt", gesperrt: e.maengel.length > 0 }),
      );
    }
    if (e.darf_pruefen) {
      knoepfe.push(
        knopf("Zurückgeben", async () => {
          const grund = await begruende("Zurück an die Person", "Was soll geändert werden?");
          if (grund) neu(await sende(`/erstattungen/${e.id}/zurueckgeben`, { grund }));
        }, { bild: "arrow-u-up-left" }),
        hat("freigabe") ? knopf("Sofort freigeben", async () => { if (await sofort("erstattung", e.id)) await frisch(); }, { bild: "check" }) : null,
        knopf("Freigabe anfordern", async () => { if (await anfordern("erstattung", e.id, e.workflow, false)) await frisch(); }, { art: "haupt", bild: "paper-plane-tilt" }),
      );
    }
    if (e.freigabe_moeglich) {
      knoepfe.push(
        knopf("Ablehnen", async () => { if (await entscheide("erstattung", e.id, false)) await frisch(); }, { art: "gefahr", bild: "x" }),
        knopf("Freigeben", async () => { if (await entscheide("erstattung", e.id, true)) await frisch(); }, { art: "haupt", bild: "check" }),
      );
    }
    wurzel.replaceChildren(
      kopf(e.titel, knoepfe),
      h("div.reihe", pille(e.status), h("span.leise", e.person), e.zahlstatus === "bezahlt" ? pille("bezahlt") : null),
      h(
        "div.zweispaltig.breitlinks",
        h(
          "section.stapel",
          e.darf_aendern
            ? h("div.karte.auswahl", Object.entries(ARTEN).map(([art, [name, bild]]) => h("button", { type: "button", onclick: () => versuche(() => (art === "kilometer" ? kilometer(e.id, neu) : art === "taggeld" ? taggeld(e.id, neu) : auslage(e.id, art, neu))) }, icon(bild), name)))
            : null,
          h("div.karte.eng", e.eintraege.length ? e.eintraege.map((p) => postenzeile(e, p, neu)) : leer("Noch keine Posten", "receipt"), h("footer.fuss", h("span", "Summe"), h("strong.mittel", euro(e.summe)))),
          e.warnungen.map((w) => h("p.hinweis", icon("warning"), w)),
        ),
        h(
          "aside.stapel",
          e.maengel.length && e.darf_aendern ? h("div.karte", h("h3", "Noch offen"), h("ul.probleme", e.maengel.map((m) => h("li", icon("warning-circle"), m)))) : null,
          e.freigabe.length ? h("div.karte", h("h3", "Freigabe"), schritte(e.freigabe)) : null,
          h(
            "div.karte.stapel",
            h("h3", "Angaben"),
            h("fieldset", { disabled: !e.darf_aendern }, feld({ name: "iban", text: "Auszahlung an IBAN", breit: true }, e.iban, (w) => versuche(async () => neu(await sende(`/erstattungen/${e.id}`, { iban: w || null }, "PATCH")))), feld({ name: "hinweis", text: "Hinweis", art: "lang" }, e.hinweis, (w) => versuche(async () => neu(await sende(`/erstattungen/${e.id}`, { hinweis: w || null }, "PATCH"))))),
            siehtAlles() ? h("fieldset", { disabled: !e.darf_pruefen }, feld({ name: "konto", text: "Konto", art: "wahl", optionen: stamm("konto") }, e.konto, (w) => versuche(async () => neu(await sende(`/erstattungen/${e.id}`, { konto: w || null }, "PATCH")))), feld({ name: "kostenstelle", text: "Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") }, e.kostenstelle, (w) => versuche(async () => neu(await sende(`/erstattungen/${e.id}`, { kostenstelle: w || null }, "PATCH"))))) : null,
          ),
          h("div.karte", h("h3", "Verlauf"), kommentarfeld(async (text) => neu(await sende(`/erstattungen/${e.id}/kommentar`, { text }))), verlauf(e.verlauf)),
        ),
      ),
    );
  }
  neu();
  return wurzel;
}

export { lies, zahlwert };
