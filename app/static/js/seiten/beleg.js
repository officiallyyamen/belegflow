import { adresse, euro, gehe, h, hat, hole, icon, loesche, melde, pfad, ruf, sende, siehtAlles, tag, versuche, z, zahlwert, zeit } from "../kern.js";
import { ARTEN, anfordern, begruende, bildansicht, entscheide, feld, frage, knopf, kommentarfeld, leer, lies, person, personen, pille, schritte, sicher, sofort, stamm, tabelle, verlauf, weiterleiten } from "../teile.js";

let blatt = "angaben";
let ansicht = "pdf";

const RECHNUNG = ["rechnung", "gutschrift"];

function pruefung(b, neu) {
  const schlecht = b.pruefbericht.filter((e) => e.stufe !== "ok");
  if (!b.pruefbericht.length) return leer("Für diese Belegart gibt es keine Prüfung", "shield-check");
  const gruppen = [...new Set(b.pruefbericht.map((e) => e.gruppe))];
  const zeile = (e) =>
    h(
      "li",
      { class: e.stufe },
      icon({ ok: "check-circle", warnung: "warning", fehler: "warning-circle", sperre: "lock" }[e.stufe]),
      h(
        "div",
        h("p", e.text),
        e.erwartet ? h("dl.werte", h("dt", "Erwartet"), h("dd", e.erwartet), h("dt", "Vorhanden"), h("dd", e.vorhanden)) : null,
        e.code === "iban_neu" && e.stufe === "sperre" && hat("freigabe", "admin")
          ? knopf("IBAN bestätigen", async () => {
              const grund = await begruende("Neue IBAN bestätigen", "Hast du die IBAN über einen bekannten Kontakt geprüft?");
              if (grund) neu(await sende(`/belege/${b.id}/aktion`, { aktion: "iban_bestaetigen", grund }));
            })
          : null,
        e.code === "duplikat" ? h("a.knopf", { href: adresse(`vergleich/${b.id}/${b.duplikat_von}`) }, icon("copy"), "Vergleichen") : null,
      ),
    );
  return h(
    "div.pruefung",
    h("p", { class: schlecht.length ? "rot" : "gut" }, schlecht.length ? `${schlecht.length} von ${b.pruefbericht.length} Punkten brauchen Aufmerksamkeit` : `Alle ${b.pruefbericht.length} Punkte in Ordnung`),
    schlecht.length ? h("ul.pruefliste", schlecht.map(zeile)) : null,
    h(
      "details",
      h("summary", "Gesamte Prüfung"),
      gruppen.map((g) => [h("h3", g), h("ul.pruefliste", b.pruefbericht.filter((e) => e.gruppe === g).map(zeile))]),
    ),
  );
}

function verweise(b, neu) {
  const zeile = (v, knopfteil) => h("li", h("a", { href: adresse(`${v.art === "beleg" ? "beleg" : "anforderung"}/${v.id}`) }, icon(v.art === "beleg" ? "file-text" : "shopping-cart"), h("span", v.name)), h("span.leise.klein", v.hinweis), knopfteil);
  const abgleich = b.abgleich.length
    ? [
        h("h3", "Abgleich mit der Bestellung"),
        h(
          "div.rollen",
          h(
            "table.klein",
            h("thead", h("tr", ["Position", "Bestellt", "Geliefert", "Berechnet", "Preis"].map((t) => h("th", t)))),
            h("tbody", b.abgleich.map((a) => h("tr", h("td", a.text), h("td", a.bestellt), h("td", a.geliefert ?? "–"), h("td", { class: a.menge_ok ? "gut" : "rot" }, a.berechnet ?? "fehlt"), h("td", { class: a.preis_ok ? "gut" : "rot" }, `${a.preis_berechnet ?? "fehlt"} / ${a.preis_bestellt}`)))),
          ),
        ),
      ]
    : null;
  return h(
    "div.stapel",
    abgleich,
    h("h3", "Verknüpft"),
    b.verknuepfungen.length ? h("ul.verweise", b.verknuepfungen.map((v) => zeile(v, hat("buchhaltung", "admin") ? knopf("", async () => neu(await loesche(`/belege/${b.id}/verknuepfung/${v.art}/${v.id}`)), { art: "rund leise", bild: "x", titel: "Lösen" }) : null))) : h("p.leise", "Noch nichts verknüpft"),
    b.verknuepfung_vorschlaege.length
      ? [h("h3", "Vorschläge"), h("ul.verweise", b.verknuepfung_vorschlaege.map((v) => zeile(v, knopf("", async () => neu(await sende(`/belege/${b.id}/verknuepfung`, { art: v.art, id: v.id })), { art: "rund", bild: "plus", titel: "Verknüpfen" }))))]
      : null,
    h("h3", "Anhänge"),
    b.anhaenge.length ? h("ul.verweise", b.anhaenge.map((a) => h("li", h("a", { href: pfad(`/anhaenge/${a.id}/datei`), target: "_blank", rel: "noopener" }, icon("paperclip"), h("span", a.dateiname)), h("span.leise.klein", a.von)))) : h("p.leise", "Keine Anhänge"),
    knopf("Datei anhängen", () => waehleDatei(async (datei) => neu(await schicke(`/belege/${b.id}/anhaenge`, datei))), { bild: "paperclip" }),
    hat("buchhaltung", "admin")
      ? knopf(
          "Verknüpfung suchen",
          async () => {
            const w = await frage("Verknüpfen", [
              { name: "art", text: "Art", art: "wahl", pflicht: true, optionen: [["beleg", "Beleg"], ["anforderung", "Bestellanforderung"]] },
              { name: "id", text: "Nummer in Belegflow", art: "zahl", pflicht: true, zahlen: true },
            ], { art: "beleg" });
            if (w) neu(await sende(`/belege/${b.id}/verknuepfung`, w));
          },
          { bild: "link" },
        )
      : null,
  );
}

export function waehleDatei(fertig, annehmen = ".pdf,.png,.jpg,.jpeg,.xml") {
  const eingabe = h("input", { type: "file", accept: annehmen });
  eingabe.onchange = () => eingabe.files[0] && versuche(() => fertig(eingabe.files[0]));
  eingabe.click();
}

export async function schicke(teil, datei) {
  const daten = new FormData();
  daten.append("datei", datei);
  return ruf(pfad(teil), "POST", daten);
}

function blaetter(b, neu, aendere) {
  const reiter = [
    ["angaben", "Angaben", null],
    ["pruefung", "Prüfung", null],
    ["verlauf", "Historie", b.kommentare?.length || null],
    ["verweise", "Verknüpft", b.verknuepfungen.length + b.anhaenge.length || null],
  ];
  const koerper = {
    angaben: () => felder(b, aendere),
    verlauf: () => h("div.inhalt", kommentarfeld(async (text) => neu(await sende(`/belege/${b.id}/kommentar`, { text }))), b.nachricht ? nachricht(b.nachricht) : null, verlauf(b.verlauf)),
    pruefung: () => h("div.inhalt", pruefung(b, neu)),
    verweise: () => h("div.inhalt", verweise(b, neu)),
  };
  return [
    h("div.reiterzeile", { role: "tablist" }, reiter.map(([art, text, zahl]) => h("button", { type: "button", role: "tab", class: blatt === art ? "an" : "", "aria-selected": String(blatt === art), onclick: () => { blatt = art; neu(); } }, text, zahl ? h("span.marke2", String(zahl)) : null))),
    koerper[blatt](),
  ];
}

function abdruecke(b) {
  const letzter = (aktion) => b.verlauf.filter((e) => e.aktion === aktion).toSorted((x, y) => (x.zeitpunkt < y.zeitpunkt ? 1 : -1))[0];
  const liste = [["Eingegangen", tag(b.erstellt_am), ""]];
  const frei = ["freigegeben", "exportiert"].includes(b.status) ? letzter("freigegeben") : null;
  const ab = b.status === "abgelehnt" ? letzter("abgelehnt") : null;
  if (frei) liste.push(["Freigegeben", `${frei.wer}, ${tag(frei.zeitpunkt)}`, ""]);
  if (ab) liste.push(["Abgelehnt", `${ab.wer}, ${tag(ab.zeitpunkt)}`, "rotstempel"]);
  if (b.zahlstatus === "bezahlt") liste.push(["Bezahlt", letzter("bezahlt") ? tag(letzter("bezahlt").zeitpunkt) : "", ""]);
  return h("div.stempelfeld", { title: "Stand in Belegflow, nicht Teil des Originals" }, liste.map(([wort, zusatz, art]) => h("div.stempel", { class: art }, h("strong", wort), h("span", zusatz))));
}

function nachricht(n) {
  return h("details.nachricht", h("summary", icon("envelope-simple"), n.betreff || "E-Mail"), h("p.leise.klein", `${n.absender}, ${zeit(n.empfangen_am)}`), h("p.vorformat", n.text));
}

function datenblatt(b, mitStempel = false) {
  return h(
    "div.blatt",
    h(
      "article.erechnung",
      h("p.leise.klein", `${b.e_rechnung} · aus den strukturierten Daten dargestellt`),
      h("div.zweispaltig", h("div", h("strong", b.lieferant), h("p", b.lieferant_adresse), h("p.leise.klein", b.lieferant_uid)), h("div", h("strong", b.empfaenger), h("p", b.empfaenger_adresse), h("p.leise.klein", b.empfaenger_uid))),
      h("h2", `${ARTEN[b.art]} ${b.nummer || ""}`),
      h("dl.paare", [["Datum", tag(b.datum)], ["Leistung", [tag(b.leistung_von), tag(b.leistung_bis)].filter(Boolean).join(" bis ")], ["Fällig", tag(b.faellig_am)], ["Bestellung", b.bestellnummer], ["IBAN", b.iban]].filter(([, w]) => w).map(([n, w]) => [h("dt", n), h("dd", w)])),
      h("table", h("thead", h("tr", ["Nr.", "Bezeichnung", "Menge", "Preis", "Netto"].map((t, i) => h("th", { class: i > 1 ? "zahl" : "" }, t)))), h("tbody", b.positionen.map((p) => h("tr", h("td", p.nummer || ""), h("td", p.text), h("td.zahl", `${p.menge ?? ""} ${p.einheit ?? ""}`), h("td.zahl", euro(p.einzelpreis, b.waehrung)), h("td.zahl", euro(p.netto, b.waehrung)))))),
      h("dl.summen", b.steuerzeilen.map((t) => [h("dt", `${t.satz} % USt von ${euro(t.netto, b.waehrung)}`), h("dd", euro(t.ust, b.waehrung))]), h("dt", "Netto"), h("dd", euro(b.netto, b.waehrung)), h("dt", "Gesamt"), h("dd", h("strong", euro(b.brutto, b.waehrung)))),
      mitStempel ? abdruecke(b) : null,
    ),
  );
}

function mitte(b, neu) {
  const beides = b.e_rechnung && b.dateityp === "application/pdf";
  const daten = b.dateityp === "application/xml" || (beides && ansicht === "daten");
  const kopf = beides ? h("div.umschalter", h("button", { type: "button", class: daten ? "" : "an", onclick: () => { ansicht = "pdf"; neu(); } }, "PDF"), h("button", { type: "button", class: daten ? "an" : "", onclick: () => { ansicht = "daten"; neu(); } }, "XML")) : null;
  return h("section.spalte.mitte", kopf, daten ? null : abdruecke(b), daten ? datenblatt(b, true) : bildansicht(pfad(`/belege/${b.id}/bild`), { datei: pfad(`/belege/${b.id}/datei`) }));
}

function partnerfeld(b, aendere) {
  return feld({ name: "partner_id", text: "Geschäftspartner", art: "wahl", leer: b.lieferant ? `${b.lieferant} (neu)` : "–", optionen: (z.stamm.partner || []).map((p) => [p.id, p.name]), breit: true }, b.partner?.id, (w) => aendere({ partner_id: w ? Number(w) : null }));
}

function felder(b, aendere) {
  const gruppe = (titel, liste) =>
    h(
      "fieldset",
      { disabled: !b.darf_aendern },
      titel ? h("legend", titel) : null,
      liste.filter(Boolean).map((f) => {
        if (f instanceof Node) return f;
        const knoten = feld(f, b[f.name], (w) => aendere({ [f.name]: w === "" ? null : w }));
        if (b.erkannt[f.name]) knoten.querySelector("span").append(h("i.punkt2", { title: `Erkannt: ${b.erkannt[f.name]}`, role: "img", "aria-label": `Automatisch erkannt: ${b.erkannt[f.name]}` }));
        return knoten;
      }),
    );
  const rechnung = RECHNUNG.includes(b.art);
  return h(
    "div.inhalt",
    gruppe("", [{ name: "art", text: "Art", art: "wahl", leer: ARTEN[b.art], optionen: Object.entries(ARTEN).filter(([a]) => a !== b.art) }, z.stamm.partner ? partnerfeld(b, aendere) : null]),
    gruppe("Dokument", [
      { name: "nummer", text: "Nummer" },
      { name: "datum", text: "Datum", art: "date" },
      rechnung ? { name: "leistung_von", text: "Leistung von", art: "date" } : null,
      rechnung ? { name: "leistung_bis", text: "Leistung bis", art: "date" } : null,
      { name: "bestellnummer", text: "Bestellnummer" },
      { name: "waehrung", text: "Währung" },
    ]),
    rechnung || b.brutto ? gruppe("Beträge", [{ name: "netto", text: "Netto", art: "geld" }, { name: "ust", text: "USt", art: "geld" }, { name: "brutto", text: "Brutto", art: "geld" }]) : null,
    rechnung ? steuer(b, aendere) : null,
    rechnung ? gruppe("Zahlung", [{ name: "faellig_am", text: "Fällig am", art: "date" }, { name: "iban", text: "IBAN", breit: true }, { name: "skonto_prozent", text: "Skonto %", art: "zahl" }, { name: "skonto_bis", text: "Skonto bis", art: "date" }]) : null,
    rechnung
      ? gruppe("Vorkontierung", [
          { name: "konto", text: "Konto", art: "wahl", optionen: stamm("konto") },
          { name: "kostenstelle", text: "Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") },
          { name: "kostentraeger", text: "Kostenträger", art: "wahl", optionen: stamm("kostentraeger") },
          { name: "steuerschluessel", text: "Steuer", art: "wahl", optionen: stamm("steuerschluessel") },
          { name: "buchungstext", text: "Buchungstext", breit: true },
          { name: "notiz", text: "Notiz für die Buchhaltung", art: "lang" },
        ])
      : null,
    rechnung && b.darf_aendern ? knopf(b.aufteilung.length ? `Aufteilung (${b.aufteilung.length})` : "Beleg aufteilen", () => teile(b, aendere), { bild: "arrows-split" }) : null,
    b.vertrag ? vertrag(b, aendere) : null,
    schlagwoerter(b, aendere),
    h("details", h("summary", "Adressen"), gruppe("", [{ name: "lieferant", text: "Lieferant", breit: true }, { name: "lieferant_adresse", text: "Anschrift", breit: true }, { name: "lieferant_uid", text: "UID" }, { name: "empfaenger", text: "Empfänger", breit: true }, { name: "empfaenger_adresse", text: "Anschrift", breit: true }, { name: "empfaenger_uid", text: "Eigene UID" }])),
  );
}

function steuer(b, aendere) {
  if (!b.steuerzeilen.length && !b.darf_aendern) return null;
  return h(
    "fieldset",
    { disabled: !b.darf_aendern },
    h("legend", "Steuerzeilen"),
    h("div.breit", b.steuerzeilen.map((t) => h("p.titelzeile.klein", h("span", `${t.satz} % von ${euro(t.netto, b.waehrung)}`), h("strong", euro(t.ust, b.waehrung))))),
    b.darf_aendern
      ? knopf("Ändern", async () => {
          const texte = b.steuerzeilen.map((t) => `${t.satz}; ${t.netto}; ${t.ust}`).join("\n");
          const w = await frage("Steuerzeilen", [{ name: "zeilen", text: "Pro Zeile: Satz; Netto; USt", art: "lang" }], { zeilen: texte });
          if (!w) return;
          const zeilen = (w.zeilen || "").split("\n").filter((t) => t.trim()).map((t) => t.split(";").map((teil) => zahlwert(teil)));
          await aendere({ steuerzeilen: zeilen.map(([satz, netto, ust]) => ({ satz, netto, ust: ust || "0" })) });
        }, { art: "leise", bild: "pencil-simple" })
      : null,
  );
}

async function teile(b, aendere) {
  const liste = h("div.stapel");
  const zeile = (t = {}) => {
    const angaben = [
      { name: "konto", text: "Konto", art: "wahl", optionen: stamm("konto") },
      { name: "kostenstelle", text: "Kostenstelle", art: "wahl", optionen: stamm("kostenstelle") },
      { name: "netto", text: "Netto", art: "geld" },
      { name: "satz", text: "USt %", art: "zahl" },
    ];
    const knoten = h("form.teilzeile", angaben.map((a) => feld(a, t[a.name] ?? (a.name === "satz" ? "20" : ""))), knopf("", () => knoten.remove(), { art: "rund leise", bild: "x", titel: "Entfernen" }));
    knoten.angaben = angaben;
    return knoten;
  };
  liste.append(...(b.aufteilung.length ? b.aufteilung : [{ konto: b.konto, kostenstelle: b.kostenstelle, netto: b.netto }, { konto: b.konto }]).map(zeile));
  const kasten = h("div.breit.stapel", liste, knopf("Zeile", () => liste.append(zeile()), { bild: "plus", art: "leise" }), h("p.leise.klein", `Summe muss ${euro(b.netto, b.waehrung)} netto ergeben`));
  await frage("Beleg aufteilen", [{ knoten: kasten }], {}, {
    breit: true,
    speichern: async () => {
      const zeilen = [...liste.children].map((f) => lies(f, f.angaben)).filter((w) => w.netto);
      await aendere({ aufteilung: zeilen }, true);
    },
  });
}

function vertrag(b, aendere) {
  const speichere = (name, wert) => aendere({ [name]: wert === "" ? null : wert }, false, "vertrag");
  const v = b.vertrag;
  return h(
    "fieldset",
    { disabled: !b.darf_aendern },
    h("legend", "Vertrag"),
    feld({ name: "typ", text: "Typ", art: "wahl", optionen: stamm("vertragstyp").map(([c]) => [c, c]) }, v.typ, (w) => speichere("typ", w)),
    ...[["beginn", "Beginn"], ["ende", "Ende"], ["kuendigen_bis", "Kündbar bis"], ["erinnerung_am", "Wiedervorlage"]].map(([n, t]) => feld({ name: n, text: t, art: "date" }, v[n], (w) => speichere(n, w))),
    feld({ name: "verantwortlich_id", text: "Verantwortlich", art: "wahl", optionen: personen() }, v.verantwortlich_id, (w) => speichere("verantwortlich_id", w ? Number(w) : null)),
    knopf(`Zu informieren (${v.informieren.length})`, async () => {
      const w = await frage("Zu informieren", [{ name: "informieren", text: "Personen", art: "mehr", zahlen: true, optionen: personen() }], v);
      if (w) await aendere(w, false, "vertrag");
    }, { art: "leise", bild: "bell" }),
  );
}

function schlagwoerter(b, aendere) {
  const setze = (namen) => aendere({ namen }, false, "schlagwoerter");
  const darf = hat("buchhaltung", "admin");
  if (!darf && !b.schlagwoerter.length) return null;
  return h(
    "fieldset",
    h("legend", "Schlagwörter"),
    h(
      "div.breit.reihe",
      b.schlagwoerter.map((n) => h("span.chip.an", n, darf ? h("button", { type: "button", "aria-label": `${n} entfernen`, onclick: () => versuche(() => setze(b.schlagwoerter.filter((m) => m !== n))) }, "×") : null)),
      darf ? b.schlagwort_vorschlaege.map((n) => h("button.chip", { type: "button", title: "Vorschlag übernehmen", onclick: () => versuche(() => setze([...b.schlagwoerter, n])) }, `+ ${n}`)) : null,
      darf ? knopf("", async () => {
        const w = await frage("Schlagwort", [{ name: "name", text: "Name", pflicht: true, vorschlaege: z.stamm.schlagwoerter }]);
        if (w) await setze([...b.schlagwoerter, w.name]);
      }, { art: "rund leise", bild: "tag", titel: "Schlagwort hinzufügen" }) : null,
    ),
  );
}

function naechster(b, neu, frisch) {
  const tue = (aktion) => async () => {
    if ((await aktion()) !== false) await frisch();
  };
  const aktion = (name, mitGrund = null) => async () => {
    const grund = mitGrund ? await begruende(...mitGrund) : "";
    if (grund !== null) neu(await sende(`/belege/${b.id}/aktion`, { aktion: name, grund }));
  };
  const buch = hat("buchhaltung", "admin");
  const oben = schritte(b.freigabe);
  const knoepfe = [];
  if (b.status === "neu" && RECHNUNG.includes(b.art)) {
    const gesperrt = b.stufe === "sperre";
    const unkontiert = !(b.konto && b.kostenstelle) && !b.aufteilung.length;
    if (gesperrt) knoepfe.push(h("p.rot.klein", icon("lock"), "Gesperrt, bitte zuerst die Prüfung klären"));
    else if (unkontiert) knoepfe.push(h("p.leise.klein", "Konto und Kostenstelle wählen"));
    else if (b.regel) knoepfe.push(h("p.hinweis.klein", icon("lightning"), `Regel „${b.regel.name}“ passt`));
    if (b.workflow && !gesperrt) knoepfe.push(h("p.leise.klein", `Workflow: ${b.workflow.name}`));
    if (hat("freigabe")) knoepfe.push(knopf("Sofort freigeben", tue(() => sofort("beleg", b.id)), { bild: "check", gesperrt: gesperrt || unkontiert }));
    if (buch) knoepfe.push(knopf("Freigabe anfordern", tue(() => anfordern("beleg", b.id, b.workflow, b.stufe === "fehler")), { art: "haupt", bild: "paper-plane-tilt", gesperrt: gesperrt || unkontiert }));
  } else if (b.status === "neu" && buch) knoepfe.push(knopf("Im Archiv ablegen", aktion("ablegen"), { art: "haupt", bild: "archive" }));
  if (b.status === "freigabe") {
    if (b.freigabe_moeglich) {
      knoepfe.push(
        knopf("Ablehnen", tue(() => entscheide("beleg", b.id, false)), { art: "gefahr", bild: "x" }),
        knopf("Freigeben", tue(() => entscheide("beleg", b.id, true)), { art: "haupt", bild: "check" }),
        knopf("Weiterleiten", tue(() => weiterleiten("beleg", b.id)), { art: "leise ganz", bild: "arrow-right" }),
      );
    }
    if (buch) knoepfe.push(knopf("Anfrage zurückziehen", tue(() => sende(`/freigaben/beleg/${b.id}/zurueckziehen`)), { art: "leise ganz", bild: "arrow-u-up-left" }));
  }
  if (b.status === "freigegeben" && buch) {
    knoepfe.push(h("a.knopf", { href: adresse("export") }, icon("paper-plane-tilt"), "Export"));
    if (b.zahlstatus === "offen") knoepfe.push(h("a.knopf.haupt", { href: adresse("zahlungen") }, icon("bank"), "Bezahlen"), knopf("Keine Zahlung nötig", aktion("keine_zahlung", ["Keine Zahlung nötig", "Warum muss dieser Beleg nicht bezahlt werden?"]), { art: "leise ganz" }));
  }
  if (b.status === "abgelehnt" && buch) knoepfe.push(knopf("Wieder öffnen", tue(() => sende(`/freigaben/beleg/${b.id}/oeffnen`)), { art: "haupt ganz", bild: "arrow-u-up-left" }));
  if (b.status === "papierkorb" && buch) knoepfe.push(knopf("Wiederherstellen", aktion("wiederherstellen"), { art: "haupt ganz", bild: "arrow-u-up-left" }));
  if (!knoepfe.length && !oben) return null;
  return h("footer.naechster", h("h3", "Nächster Schritt"), oben, h("div.knoepfe", knoepfe));
}

function menue(b, neu) {
  const buch = hat("buchhaltung", "admin");
  if (!buch) return null;
  const aktion = (name) => async () => {
    const d = await sende(`/belege/${b.id}/aktion`, { aktion: name });
    name === "papierkorb" ? (melde("In den Papierkorb gelegt"), history.back()) : neu(d);
  };
  return [
    knopf("", async () => {
      const w = await frage("Sichtbarkeit", [
        { name: "eingeschraenkt", text: "Nur für ausgewählte Personen sichtbar", art: "haken", breit: true },
        { name: "personen", text: "Personen", art: "mehr", zahlen: true, optionen: personen() },
      ], { eingeschraenkt: b.eingeschraenkt, personen: b.sichtbar });
      if (w) neu(await sende(`/belege/${b.id}/sichtbarkeit`, w, "PUT"));
    }, { art: "rund leise", bild: b.eingeschraenkt ? "lock" : "lock-open", titel: "Sichtbarkeit" }),
    b.darf_aendern ? knopf("", aktion(b.klaerung ? "klaerung_ende" : "klaerung"), { art: "rund leise", bild: "question", titel: b.klaerung ? "Klärung beenden" : "Zur Klärung legen" }) : null,
    b.darf_aendern ? knopf("", async () => ((await sicher("In den Papierkorb", "Der Beleg lässt sich später wiederherstellen.", "In den Papierkorb")) ? aktion("papierkorb")() : null), { art: "rund leise", bild: "trash", titel: "Papierkorb" }) : null,
  ];
}

function ergebnis(b, neu) {
  if (!b.pruefbericht.length) return null;
  const schlecht = b.pruefbericht.filter((e) => ["fehler", "sperre"].includes(e.stufe));
  const warnungen = b.pruefbericht.filter((e) => e.stufe === "warnung").length;
  const text = schlecht.length ? schlecht[0].text : warnungen ? `${warnungen} ${warnungen === 1 ? "Hinweis" : "Hinweise"} bei ${b.pruefbericht.length} Prüfungen` : `${b.pruefbericht.length} Prüfungen bestanden`;
  return h("button.ergebnis", { type: "button", class: schlecht.length ? "schlecht" : warnungen ? "mittelgut" : "", onclick: () => { blatt = "pruefung"; neu(); } }, icon(schlecht.length ? "warning-circle" : warnungen ? "warning" : "check-circle"), h("span", text), schlecht.length > 1 ? h("span", `+ ${schlecht.length - 1} weitere`) : null, icon("caret-right"));
}

export async function seite([nummer]) {
  let b = await hole(`/belege/${nummer}`);
  const wurzel = h("div.belegseite");
  const bau = { mitte: null, fuer: "" };
  const neu = (frisch) => {
    if (frisch?.id === b.id) b = frisch;
    const schluessel = `${b.id}|${ansicht}|${JSON.stringify([b.brutto, b.positionen.length, b.status, b.zahlstatus])}`;
    if (bau.fuer !== schluessel) Object.assign(bau, { mitte: mitte(b, neu), fuer: schluessel });
    const alt = wurzel.querySelector(".rechts .inhalt")?.scrollTop || 0;
    wurzel.replaceChildren(
      h(
        "header.belegkopf",
        knopf("", () => history.back(), { art: "rund", bild: "caret-left", titel: "Zurück" }),
        h("div", h("h1", b.partner?.name || b.lieferant || b.dateiname), h("p.leise.klein", [ARTEN[b.art], b.nummer, `hochgeladen von ${b.hochgeladen_name}`].filter(Boolean).join(", "))),
        h("strong.belegsumme", euro(b.brutto, b.waehrung)),
        pille(b.status, b.status === "neu" ? "Neu" : undefined),
        b.zahlstatus !== "offen" ? pille(b.zahlstatus) : null,
        b.klaerung ? pille("warnung", "Klärung") : null,
        b.e_rechnung ? h("span.chip", b.e_rechnung) : null,
        menue(b, neu),
      ),
      h("div.belegraster", bau.mitte, h("aside.spalte.rechts", ergebnis(b, neu), blaetter(b, neu, aendere), naechster(b, neu, frischHolen))),
    );
    const inhalt = wurzel.querySelector(".rechts .inhalt");
    if (inhalt) inhalt.scrollTop = alt;
  };
  const frischHolen = async () => neu(await hole(`/belege/${nummer}`));
  const aendere = async (werte, werfen = false, teil = "") => {
    const wege = { "": "PATCH", vertrag: "PATCH", schlagwoerter: "PUT" };
    try {
      neu(await ruf(pfad(`/belege/${nummer}${teil ? `/${teil}` : ""}`), wege[teil], werte));
      if (werte.partner_id !== undefined || werte.art) window.dispatchEvent(new Event("belegflow-stamm"));
    } catch (fehler) {
      if (werfen) throw fehler;
      melde(fehler.message, true);
      neu();
    }
  };
  blatt = "angaben";
  neu();
  return wurzel;
}

export async function vergleich([nummer, anderer]) {
  const [a, b] = await Promise.all([hole(`/belege/${nummer}`), hole(`/belege/${anderer}`)]);
  const zeilen = [["Nummer", "nummer"], ["Datum", "datum"], ["Netto", "netto"], ["Brutto", "brutto"], ["IBAN", "iban"], ["Fällig", "faellig_am"], ["Status", "status"]];
  const aktion = (daten, ziel) => async () => {
    await daten();
    gehe(ziel);
  };
  const seitenteil = (x, titel) => h("section.karte", h("div.titelzeile", h("h2", titel), h("a", { href: adresse(`beleg/${x.id}`) }, `Beleg ${x.id}`)), x.dateityp === "application/xml" ? datenblatt(x) : bildansicht(pfad(`/belege/${x.id}/bild`)));
  return h(
    "div.seite",
    h("header.kopf", h("h1", "Duplikat prüfen"), h("div.reihe",
      knopf("Ist kein Duplikat", async () => {
        const grund = await begruende("Kein Duplikat", "Warum sind das zwei verschiedene Belege?");
        if (grund) await aktion(() => sende(`/belege/${a.id}/aktion`, { aktion: "kein_duplikat", grund }), `beleg/${a.id}`)();
      }, { bild: "check" }),
      knopf("An den ersten anhängen", aktion(() => sende(`/belege/${a.id}/anhaengen`, { ziel: b.id }), `beleg/${b.id}`), { bild: "paperclip" }),
      knopf("Duplikat löschen", aktion(() => sende(`/belege/${a.id}/aktion`, { aktion: "papierkorb", grund: `Duplikat von Beleg ${b.id}` }), "eingang/rechnungen"), { art: "gefahr", bild: "trash" }),
    )),
    h("div.karte.eng", tabelle([{ titel: "", wert: ([t]) => t }, { titel: "Neuer Beleg", wert: ([, f]) => h("span", { class: a[f] === b[f] ? "" : "rot" }, a[f] ?? "–") }, { titel: "Vorhandener Beleg", wert: ([, f]) => b[f] ?? "–" }], zeilen)),
    h("div.zweispaltig", seitenteil(a, "Neu"), seitenteil(b, "Vorhanden")),
  );
}

export { person, siehtAlles };
