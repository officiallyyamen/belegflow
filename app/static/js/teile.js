import { adresse, euro, h, heute, hole, icon, kurzname, melde, s, sende, tag, versuche, z, zahlwert, zeit } from "./kern.js";

export const ARTEN = {
  rechnung: "Rechnung",
  gutschrift: "Gutschrift",
  angebot: "Angebot",
  auftragsbestaetigung: "Auftragsbestätigung",
  bestellung: "Bestellung",
  lieferschein: "Lieferschein",
  vertrag: "Vertrag",
  ausgangsrechnung: "Ausgangsrechnung",
  sonstiges: "Sonstiges",
};
export const STATUS = {
  neu: ["Offen", "info", "tray"],
  freigabe: ["In Freigabe", "warn", "clock"],
  freigegeben: ["Freigegeben", "gut", "check"],
  exportiert: ["Exportiert", "ruhig", "download-simple"],
  abgelehnt: ["Abgelehnt", "fehler", "x"],
  abgelegt: ["Abgelegt", "ruhig", "archive"],
  papierkorb: ["Papierkorb", "ruhig", "trash"],
  entwurf: ["Entwurf", "ruhig", "pencil-simple"],
  pruefung: ["Wird geprüft", "info", "eye"],
  zurueck: ["Zurückgegeben", "fehler", "arrow-u-up-left"],
  verworfen: ["Verworfen", "ruhig", "trash"],
  teilweise: ["Teilweise erfüllt", "info", "package"],
  erfuellt: ["Erfüllt", "gut", "check-circle"],
  beantragt: ["Beantragt", "warn", "clock"],
  aktiv: ["Aktiv", "gut", "check"],
  gesperrt: ["Gesperrt", "fehler", "lock"],
  fehlt: ["Beleg fehlt", "fehler", "warning-circle"],
  zugeordnet: ["Beleg da", "gut", "check"],
  ohne_beleg: ["Ohne Beleg", "ruhig", "minus"],
  empfangen: ["Empfangen", "gut", "check"],
  warnung: ["Warnung", "warn", "warning"],
  offen: ["Offen", "warn", "clock"],
  wartet: ["Wartet", "ruhig", "clock"],
  entfallen: ["Entfallen", "ruhig", "minus"],
  bezahlt: ["Bezahlt", "gut", "check"],
  keine: ["Keine Zahlung", "ruhig", "minus"],
  karte: ["Mit Karte", "info", "credit-card"],
};

export function pille(status, text) {
  const [name, farbe, bild] = STATUS[status] || [status, "ruhig", "minus"];
  return h(`span.pille.${farbe}`, icon(bild), text || name);
}

export function knopf(text, aufgabe, { art = "", bild = null, gesperrt = false, titel = "" } = {}) {
  const knoten = h("button.knopf", { type: "button", class: art, disabled: gesperrt, title: titel, "aria-label": titel || null });
  knoten.onclick = async (ereignis) => {
    ereignis.stopPropagation();
    knoten.disabled = true;
    await versuche(() => aufgabe(ereignis));
    if (knoten.isConnected) knoten.disabled = gesperrt;
  };
  if (bild) knoten.append(icon(bild));
  if (text) knoten.append(h("span", text));
  return knoten;
}

export const leer = (text, bild = "check-circle") => h("div.leer", icon(bild), h("p", text));

export function kopf(titel, ...rechts) {
  return h("header.kopf", h("h1", titel), h("div.reihe", rechts));
}

export function reiter(eintraege, aktiv) {
  return h(
    "nav.reiter",
    { "aria-label": "Ansichten" },
    eintraege
      .filter(Boolean)
      .map(([ziel, text, zahl]) =>
        h("a", { href: adresse(ziel), class: ziel === aktiv ? "an" : "", "aria-current": ziel === aktiv ? "page" : null }, text, zahl ? h("span.marke2", String(zahl)) : null),
      ),
  );
}

export function tabelle(spalten, zeilen, { beiKlick = null, leertext = "Hier ist gerade nichts zu tun", wahl = null } = {}) {
  if (!zeilen.length) return leer(leertext);
  const alle = wahl
    ? h("input", {
        type: "checkbox",
        "aria-label": "Alle auswählen",
        onchange: (e) => {
          for (const feld of koerper.querySelectorAll("input[data-wahl]")) {
            if (feld.disabled) continue;
            feld.checked = e.target.checked;
            feld.checked ? wahl.gewaehlt.add(feld.eintrag) : wahl.gewaehlt.delete(feld.eintrag);
          }
          wahl.geaendert();
        },
      })
    : null;
  const koerper = h(
    "tbody",
    zeilen.map((zeile) => {
      const feld = wahl
        ? h("input", {
            type: "checkbox",
            "data-wahl": "1",
            "aria-label": "Auswählen",
            disabled: wahl.sperre?.(zeile),
            checked: wahl.gewaehlt.has(zeile),
            onclick: (e) => e.stopPropagation(),
            onchange: (e) => {
              e.target.checked ? wahl.gewaehlt.add(zeile) : wahl.gewaehlt.delete(zeile);
              wahl.geaendert();
            },
          })
        : null;
      if (feld) feld.eintrag = zeile;
      const reihe = h(
        "tr",
        { class: beiKlick ? "klickbar" : "", tabIndex: beiKlick ? 0 : -1 },
        feld ? h("td.wahl", { onclick: (e) => e.stopPropagation() }, feld) : null,
        spalten.map((sp) => h("td", { class: sp.klasse || "" }, sp.wert(zeile))),
      );
      if (beiKlick) {
        reihe.onclick = (e) => {
          if (!e.target.closest("button, a, input, select")) beiKlick(zeile);
        };
        reihe.onkeydown = (e) => {
          if (e.key === "Enter" && e.target === reihe) beiKlick(zeile);
        };
      }
      return reihe;
    }),
  );
  return h(
    "div.rollen",
    h("table", h("thead", h("tr", wahl ? h("th.wahl", alle) : null, spalten.map((sp) => h("th", { class: sp.klasse || "" }, sp.titel)))), koerper),
  );
}

export function feld(angabe, wert, beiAenderung = null) {
  const { name, text, art = "text", optionen = [], pflicht = false, hinweis = "", muster = null, platz = "" } = angabe;
  let eingabe;
  if (art === "wahl") {
    eingabe = h("select", { name, required: pflicht }, [["", angabe.leer ?? "–"], ...optionen].map(([w, t]) => h("option", { value: w, selected: String(w) === String(wert ?? "") }, t)));
  } else if (art === "mehr") {
    const gewaehlt = new Set((wert || []).map(String));
    eingabe = h(
      "div.mehrfach",
      { role: "group", "aria-label": text },
      optionen.map(([w, t]) => h("label.haken", h("input", { type: "checkbox", value: w, name, checked: gewaehlt.has(String(w)) }), t)),
    );
  } else if (art === "haken") {
    eingabe = h("input", { type: "checkbox", name, checked: Boolean(wert) });
    if (beiAenderung) eingabe.onchange = () => beiAenderung(eingabe.checked);
    return h("label.haken", { class: angabe.breit ? "breit" : "" }, eingabe, text);
  } else if (art === "lang") {
    eingabe = h("textarea", { name, required: pflicht, value: wert ?? "", rows: 3, placeholder: platz });
  } else {
    eingabe = h("input", {
      name,
      required: pflicht,
      type: art === "geld" || art === "zahl" ? "text" : art,
      inputMode: art === "geld" || art === "zahl" ? "decimal" : "",
      value: art === "geld" && wert ? Number(wert).toLocaleString("de-AT", { minimumFractionDigits: 2, useGrouping: false }) : (wert ?? ""),
      placeholder: platz,
      autocomplete: art === "password" ? "new-password" : "off",
    });
    if (muster) eingabe.pattern = muster;
    if (angabe.vorschlaege?.length) {
      const nummer = `v${Math.random().toString(36).slice(2)}`;
      eingabe.setAttribute("list", nummer);
      eingabe.after(h("datalist", { id: nummer }));
      const liste = h("datalist", { id: nummer }, angabe.vorschlaege.map((v) => h("option", { value: v })));
      return h("label.feld", { class: angabe.breit ? "breit" : "" }, h("span", text), eingabe, liste, hinweis ? h("small", hinweis) : null);
    }
  }
  if (beiAenderung && art !== "mehr") eingabe.onchange = () => beiAenderung(art === "geld" || art === "zahl" ? zahlwert(eingabe.value) : eingabe.value);
  return h(art === "mehr" ? "div.feld" : "label.feld", { class: angabe.breit || art === "lang" || art === "mehr" ? "breit" : "" }, h("span", text), eingabe, hinweis ? h("small", hinweis) : null);
}

export function lies(formular, felder) {
  const werte = {};
  for (const angabe of felder) {
    const { name, art } = angabe;
    if (!name) continue;
    if (art === "mehr") werte[name] = [...formular.querySelectorAll(`input[name="${name}"]:checked`)].map((e) => (angabe.zahlen ? Number(e.value) : e.value));
    else if (art === "haken") werte[name] = formular.elements[name].checked;
    else {
      const roh = formular.elements[name].value.trim();
      const text = art === "geld" || art === "zahl" ? zahlwert(roh) : roh;
      werte[name] = text === "" ? null : angabe.zahlen ? Number(text) : text;
    }
  }
  return werte;
}

export function fenster(titel, inhalt, { breit = false } = {}) {
  const kasten = h("dialog", { class: breit ? "breit" : "", "aria-label": titel }, h("div.fensterkopf", h("h2", titel), knopf("", () => kasten.close(), { art: "rund leise", bild: "x", titel: "Schließen" })), inhalt);
  kasten.addEventListener("close", () => kasten.remove());
  document.body.append(kasten);
  kasten.showModal();
  return kasten;
}

export function frage(titel, felder, werte = {}, { text = "Speichern", hinweis = "", art = "haupt", speichern = null, breit = false } = {}) {
  return new Promise((fertig) => {
    let ergebnis = null;
    const abbruch = h("button.knopf", { type: "button", textContent: "Abbrechen" });
    const los = h("button.knopf", { class: art, textContent: text });
    const formular = h("form", hinweis ? h("p.leise", hinweis) : null, h("div.felder", felder.map((f) => (f.knoten ? f.knoten : feld(f, werte[f.name] ?? f.wert)))), h("div.ende", abbruch, los));
    const kasten = fenster(titel, formular, { breit });
    abbruch.onclick = () => kasten.close();
    formular.onsubmit = async (e) => {
      e.preventDefault();
      const gelesen = lies(formular, felder);
      if (speichern) {
        los.disabled = true;
        try {
          ergebnis = (await speichern(gelesen)) ?? true;
        } catch (fehler) {
          melde(fehler.message, true);
          los.disabled = false;
          return;
        }
      } else ergebnis = gelesen;
      kasten.close();
    };
    kasten.addEventListener("close", () => fertig(ergebnis));
  });
}

export const begruende = async (titel, hinweis, art = "haupt") =>
  (await frage(titel, [{ name: "grund", text: "Begründung", art: "lang", pflicht: true }], {}, { text: "Bestätigen", hinweis, art }))?.grund ?? null;

export const sicher = (titel, hinweis, text = "Löschen") => frage(titel, [], {}, { text, hinweis, art: "gefahr" });

export const person = (name) => h("span.person", { title: name, "aria-hidden": "true" }, kurzname(name));

const TATEN = {
  hochgeladen: "hat hochgeladen",
  erkannt: "hat gelesen",
  partner_erkannt: "hat den Geschäftspartner erkannt",
  geprueft: "hat geprüft",
  geaendert: "hat geändert",
  kommentar: "hat kommentiert",
  freigabe_angefordert: "hat Freigabe angefordert",
  schritt_freigegeben: "hat den Schritt freigegeben",
  freigegeben: "hat freigegeben",
  abgelehnt: "hat abgelehnt",
  zurueckgezogen: "hat die Anfrage zurückgezogen",
  wieder_geoeffnet: "hat wieder geöffnet",
  weitergeleitet: "hat weitergeleitet",
  exportiert: "hat exportiert",
  bezahlt: "hat die Zahlung angelegt",
  keine_zahlung: "hat die Zahlung abgewählt",
  iban_bestaetigt: "hat die neue IBAN bestätigt",
  kein_duplikat: "hat das Duplikat ausgeschlossen",
  papierkorb: "hat in den Papierkorb gelegt",
  wiederhergestellt: "hat wiederhergestellt",
  abgelegt: "hat im Archiv abgelegt",
  klaerung: "hat zur Klärung gelegt",
  klaerung_beendet: "hat die Klärung beendet",
  sichtbarkeit: "hat die Sichtbarkeit geändert",
  schlagwoerter: "hat Schlagwörter gesetzt",
  anhang: "hat eine Datei angehängt",
  verknuepft: "hat verknüpft",
  verknuepfung_geloest: "hat eine Verknüpfung gelöst",
  vertrag_geaendert: "hat Vertragsdaten geändert",
  karte_zugeordnet: "hat die Kartenzahlung zugeordnet",
  karte_geloest: "hat die Kartenzahlung gelöst",
  rueckgestellt: "hat eine Rückstellung gebucht",
  aufgeloest: "hat die Rückstellung aufgelöst",
  automatik_fehler: "konnte die Regel nicht anwenden",
  angelegt: "hat angelegt",
  beantragt: "hat beantragt",
  eingereicht: "hat eingereicht",
  zurueckgegeben: "hat zurückgegeben",
  verworfen: "hat verworfen",
  posten_angelegt: "hat einen Posten hinzugefügt",
  posten_geaendert: "hat einen Posten geändert",
  posten_geloescht: "hat einen Posten entfernt",
  wareneingang: "hat Ware angenommen",
  ohne_beleg: "hat ohne Beleg abgeschlossen",
};
const FELDNAMEN = {
  lieferant: "Lieferant",
  nummer: "Nummer",
  datum: "Datum",
  faellig_am: "Fällig",
  leistung_von: "Leistung",
  netto: "Netto",
  ust: "USt",
  brutto: "Brutto",
  iban: "IBAN",
  bestellnummer: "Bestellung",
  konto: "Konto",
  kostenstelle: "Kostenstelle",
};

export const tat = (aktion) => TATEN[aktion] || aktion.replaceAll("_", " ");

function einzelheiten(eintrag) {
  const d = eintrag.details;
  const zeilen = [];
  if (d.text) return h("blockquote", d.text);
  if (d.werte) zeilen.push(h("dl.werte", Object.entries(d.werte).map(([n, w]) => [h("dt", FELDNAMEN[n] || n), h("dd", w)])));
  if (d.probleme?.length) zeilen.push(h("ul.probleme", d.probleme.map((p) => h("li", icon("warning-circle"), p))));
  if (d.probleme && !d.probleme.length) zeilen.push(h("p.gut", icon("check-circle"), "Keine Probleme gefunden"));
  if (d.neu && typeof d.neu === "object") {
    zeilen.push(h("p.leise.klein", Object.entries(d.neu).map(([n, w]) => `${FELDNAMEN[n] || n.replaceAll("_", " ")}: ${Array.isArray(w) ? `${w.length} Zeilen` : (w ?? "leer")}`).join(" · ")));
  }
  if (d.partner) zeilen.push(h("p.leise.klein", d.partner));
  if (d.workflow) zeilen.push(h("p.leise.klein", `Workflow: ${d.workflow}`));
  if (d.regel) zeilen.push(h("p.leise.klein", `Regel: ${d.regel}`));
  if (d.format) zeilen.push(h("p.leise.klein", d.format));
  if (d.datei) zeilen.push(h("p.leise.klein", d.datei));
  if (d.vertretung) zeilen.push(h("p.leise.klein", `in Vertretung für ${d.vertretung}`));
  if (d.grund) zeilen.push(h("blockquote", d.grund));
  return zeilen;
}

const MASCHINEN = ["Regeln", "Sprachmodell", "E-Rechnung", "Erkennung", "Prüfung", "Automatik"];

export function verlauf(eintraege) {
  return h(
    "ol.verlauf",
    eintraege.map((e) =>
      h(
        "li",
        MASCHINEN.includes(e.wer) ? h("span.person.maschine", icon("gear")) : person(e.wer),
        h("div", h("p", h("strong", e.wer), ` ${tat(e.aktion)}`), einzelheiten(e), h("time.leise.klein", { dateTime: e.zeitpunkt }, zeit(e.zeitpunkt))),
      ),
    ),
  );
}

export function kommentarfeld(speichern) {
  const eingabe = h("textarea", { rows: 2, placeholder: "Kommentar schreiben, mit @Name erwähnen", "aria-label": "Kommentar", maxLength: 1000 });
  const liste = h("div.vorschlaege", { hidden: true });
  eingabe.oninput = () => {
    const treffer = eingabe.value.slice(0, eingabe.selectionStart).match(/@([\p{L} ]{0,20})$/u);
    const passend = treffer ? z.stamm.personen.filter((p) => p.name.toLowerCase().startsWith(treffer[1].toLowerCase())).slice(0, 5) : [];
    liste.hidden = !passend.length;
    liste.replaceChildren(
      ...passend.map((p) =>
        h("button", {
          type: "button",
          textContent: p.name,
          onclick: () => {
            const ende = eingabe.selectionStart;
            eingabe.value = `${eingabe.value.slice(0, ende - treffer[0].length)}@${p.name} ${eingabe.value.slice(ende)}`;
            liste.hidden = true;
            eingabe.focus();
          },
        }),
      ),
    );
  };
  const formular = h("form.kommentar", eingabe, liste, h("button.knopf", "Senden"));
  formular.onsubmit = (e) => {
    e.preventDefault();
    if (eingabe.value.trim()) versuche(() => speichern(eingabe.value.trim()));
  };
  return formular;
}

export function schritte(liste) {
  if (!liste.length) return null;
  return h(
    "ol.schritte",
    liste.map((schritt) =>
      h(
        "li",
        { class: schritt.status },
        h("span.punkt", icon((STATUS[schritt.status] || ["", "", "clock"])[2])),
        h(
          "div",
          h("strong", schritt.ziel),
          h("p.leise.klein", schritt.von ? `${STATUS[schritt.status][0]} von ${schritt.von}${schritt.in_vertretung ? ` für ${schritt.in_vertretung}` : ""}, ${zeit(schritt.am)}` : schritt.hinweis || STATUS[schritt.status][0]),
        ),
      ),
    ),
  );
}

export const freigeber = () => [
  ...z.stamm.teams.filter((t) => t.mitglieder.length).map((t) => [`team-${t.id}`, `Team ${t.name}`]),
  ...z.stamm.personen.filter((p) => p.rollen.some((r) => ["freigabe", "admin"].includes(r))).map((p) => [`person-${p.id}`, `${p.name}${p.abwesend ? " (abwesend)" : ""}`]),
];

export function zielwahl(anfang = [""]) {
  const reihe = h("div.zielwahl");
  const neu = (wert = "") => {
    const auswahl = h("select", { "aria-label": "Zuständig" }, [["", "Person oder Team wählen"], ...freigeber()].map(([w, t]) => h("option", { value: w, selected: w === wert }, t)));
    const zeile = h("div.reihe", h("span.nummer"), auswahl, knopf("", () => zeile.remove(), { art: "rund leise", bild: "x", titel: "Schritt entfernen" }));
    return zeile;
  };
  reihe.append(...anfang.map((wert) => neu(wert)));
  const mehr = knopf("Weiterer Schritt", () => reihe.append(neu()), { bild: "plus", art: "leise" });
  return {
    knoten: h("div.breit", h("p.leise.klein", "Die Schritte werden der Reihe nach freigegeben."), reihe, mehr),
    werte: () =>
      [...reihe.querySelectorAll("select")]
        .map((a) => a.value)
        .filter(Boolean)
        .map((wert) => ({ art: wert.split("-")[0], id: Number(wert.split("-")[1]) })),
  };
}

export async function anfordern(art, nummer, vorschlag, mitGrund) {
  const wahl = zielwahl();
  const felder = [
    { name: "weg", text: "Weg", art: "wahl", leer: "Person oder Team wählen", optionen: z.stamm.workflows.map((w) => [w.id, `Workflow: ${w.name}`]) },
    { knoten: wahl.knoten },
    ...(mitGrund ? [{ name: "grund", text: "Begründung für die Prüfergebnisse", art: "lang", pflicht: true }] : []),
  ];
  const ergebnis = frage("Freigabe anfordern", felder, { weg: vorschlag?.id }, {
    text: "Anfordern",
    speichern: (w) => sende(`/freigaben/${art}/${nummer}/anfordern`, { workflow_id: w.weg ? Number(w.weg) : null, ziele: w.weg ? [] : wahl.werte(), grund: w.grund ?? null }),
  });
  const auswahl = document.querySelector('dialog select[name="weg"]');
  const zeige = () => {
    wahl.knoten.hidden = Boolean(auswahl.value);
  };
  auswahl.addEventListener("change", zeige);
  zeige();
  const fertig = await ergebnis;
  if (fertig) {
    const offen = (await hole("/freigaben", { art, sicht: "angefragt" })).find((e) => e.id === nummer);
    const wer = offen?.freigabe?.filter((s) => s.status === "offen").map((s) => (s.hinweis ? `${s.ziel} (${s.hinweis})` : s.ziel)).join(", ");
    melde(wer ? `Angefragt, wartet auf ${wer}` : "Freigabe angefragt");
  }
  return fertig;
}

export async function sofort(art, nummer) {
  try {
    await sende(`/freigaben/${art}/${nummer}/sofort`, {});
  } catch (fehler) {
    if (!fehler.daten?.grund_noetig) throw fehler;
    const grund = await begruende("Trotz Prüfergebnis freigeben", fehler.message);
    if (!grund) return false;
    await sende(`/freigaben/${art}/${nummer}/sofort`, { grund });
  }
  melde("Freigegeben");
  return true;
}

export async function entscheide(art, nummer, ja) {
  let grund = null;
  if (!ja) {
    grund = await begruende("Ablehnen", "Die anfragende Person sieht diese Begründung.", "gefahr");
    if (!grund) return false;
  }
  await sende(`/freigaben/${art}/${nummer}/entscheidung`, { ja, grund });
  melde(ja ? "Freigegeben" : "Abgelehnt");
  return true;
}

export async function weiterleiten(art, nummer) {
  return frage(
    "Weiterleiten",
    [
      { name: "ziel", text: "An", art: "wahl", pflicht: true, optionen: freigeber() },
      { name: "grund", text: "Grund", art: "lang", pflicht: true },
    ],
    {},
    {
      text: "Weiterleiten",
      speichern: (w) => {
        const [a, n] = w.ziel.split("-");
        return sende(`/freigaben/${art}/${nummer}/weiterleiten`, { ziel: { art: a, id: Number(n) }, grund: w.grund });
      },
    },
  );
}

export function ring(anteil, text, unten) {
  const umfang = 2 * Math.PI * 42;
  const bogen = s("circle", { cx: 50, cy: 50, r: 42, "stroke-width": 9, class: "bogen", transform: "rotate(-90 50 50)", "stroke-dasharray": umfang, "stroke-dashoffset": umfang * (1 - Math.min(anteil, 1)) });
  return h("div.ring", s("svg", { viewBox: "0 0 100 100", role: "img", "aria-label": `${text} ${unten}` }, s("circle", { cx: 50, cy: 50, r: 42, "stroke-width": 9, class: "bahn" }), bogen), h("div", h("strong", text), h("span.leise.klein", unten)));
}

export function balken(werte, namen, anzeige = euro, betont = -1) {
  const hoechster = Math.max(...werte.map(Number), 1);
  const stufe = 10 ** Math.floor(Math.log10(hoechster));
  const schritt = [0.25, 0.5, 1, 2.5].map((f) => f * stufe).find((w) => hoechster / w <= 4) || stufe * 2.5;
  const oben = Math.ceil(hoechster / schritt) * schritt;
  const marken = Array.from({ length: Math.round(oben / schritt) + 1 }, (_, i) => oben - i * schritt);
  return h(
    "div.diagramm",
    { role: "img", "aria-label": namen.map((n, i) => `${n}: ${anzeige(werte[i])}`).join(", ") },
    h("div.achse", marken.map((m) => h("span", m.toLocaleString("de-AT")))),
    h("div.linien", marken.map(() => h("i"))),
    h(
      "div.saeulen",
      werte.map((wert, i) => {
        const stab = h("span.stab");
        stab.style.height = `${Math.max((Number(wert) / oben) * 100, Number(wert) > 0 ? 1 : 0)}%`;
        return h("div.saeule", { title: `${namen[i]}: ${anzeige(wert)}`, class: i === betont ? "betont" : "" }, stab);
      }),
    ),
    h("div.monate", namen.map((n, i) => h("span", { class: i === betont ? "betont" : "" }, n))),
  );
}

export function fortschritt(anteil, warnen = true) {
  const innen = h("span");
  innen.style.width = `${Math.min(Math.max(anteil, 0), 1) * 100}%`;
  return h("div.fortschritt", { class: !warnen ? "" : anteil > 1 ? "ueber" : anteil > 0.85 ? "knapp" : "" }, innen);
}

export function bildansicht(adr, { typ = "application/pdf", datei = null } = {}) {
  let seite = 1;
  let seiten = 1;
  let breite = 100;
  const bild = h("img", { alt: "Beleg" });
  const anzeige = h("span.klein");
  const flaeche = h("div.blatt", bild);
  const zurueck = knopf("", () => lade(seite - 1), { art: "rund", bild: "caret-left", titel: "Vorherige Seite" });
  const weiter = knopf("", () => lade(seite + 1), { art: "rund", bild: "caret-right", titel: "Nächste Seite" });
  const zoome = (faktor) => {
    breite = Math.min(250, Math.max(50, breite + faktor));
    bild.style.width = `${breite}%`;
  };
  async function lade(nummer) {
    if (nummer < 1 || nummer > seiten) return;
    const antwort = await fetch(`${adr}?seite=${nummer}`);
    if (!antwort.ok) {
      flaeche.replaceChildren(leer("Vorschau ist nicht möglich", "file-text"));
      return;
    }
    seiten = Number(antwort.headers.get("x-seiten") || 1);
    seite = nummer;
    const alt = bild.src;
    bild.src = URL.createObjectURL(await antwort.blob());
    if (alt.startsWith("blob:")) URL.revokeObjectURL(alt);
    anzeige.textContent = `${seite} / ${seiten}`;
  }
  versuche(() => lade(1));
  return h(
    "div.ansicht",
    h("div.werkzeug", zurueck, anzeige, weiter, knopf("", () => zoome(-15), { art: "rund", bild: "minus", titel: "Kleiner" }), knopf("", () => zoome(15), { art: "rund", bild: "plus", titel: "Größer" }), datei ? h("a.knopf.rund", { href: datei, target: "_blank", rel: "noopener", title: "Original öffnen", "aria-label": "Original öffnen" }, icon("download-simple")) : null),
    flaeche,
  );
}

export const monate = ["Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
export const stamm = (art) => (z.stamm.werte[art] || []).map((w) => [w.code, `${w.code} ${w.name}`]);
export const personen = () => z.stamm.personen.map((p) => [p.id, p.name]);
export { heute, tag };
