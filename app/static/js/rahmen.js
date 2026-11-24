import { adresse, euro, gehe, h, hat, hole, icon, kurzname, melde, merke, ruf, sende, siehtAlles, versuche, vorTagen, z, pfad } from "./kern.js";
import { ARTEN, feld, fenster, frage, knopf, leer, person, pille } from "./teile.js";

const zeichen = () => icon("logo");

export function anmeldeseite(danach) {
  const felder = [
    { name: "email", text: "E-Mail", art: "email", pflicht: true },
    { name: "passwort", text: "Passwort", art: "password", pflicht: true },
  ];
  const knoten = felder.map((f) => feld(f, ""));
  knoten[0].querySelector("input").autocomplete = "username";
  knoten[1].querySelector("input").autocomplete = "current-password";
  const geheim = knoten[1].querySelector("input");
  const auge = h("button.auge", { type: "button", "aria-label": "Passwort anzeigen", "aria-pressed": "false" }, icon("eye"));
  auge.onclick = () => {
    const offen = geheim.type === "password";
    geheim.type = offen ? "text" : "password";
    auge.setAttribute("aria-pressed", String(offen));
  };
  const huelle = h("span.geheimfeld");
  geheim.replaceWith(huelle);
  huelle.append(geheim, auge);
  knoten[0].querySelector("input").placeholder = "name@firma.at";
  geheim.placeholder = "Dein Passwort";
  const formular = h("form", h("div", h("h1", "Anmelden"), h("p.leise", "Mit der E-Mail, die deine Verwaltung eingetragen hat")), knoten, h("button.knopf.haupt", "Anmelden"), h("p.leise.klein", "Passwort vergessen? Deine Verwaltung setzt es neu"));
  const karte = (bild, titel, wer, text, zeitpunkt) => h("li", h("span.kachelbild", icon(bild)), h("div", h("strong", titel), h("span", wer), h("p", text)), h("time", zeitpunkt));
  const schaufenster = h(
    "aside.schaufenster",
    { "aria-hidden": "true" },
    h("div.logo", zeichen(), "Belegflow"),
    h(
      "div.szene",
      h("div.riesenbon", icon("logo")),
      h(
        "div.beispiele",
        h("div.titelzeile", h("strong", "Deine Rechnungen"), h("span.beispielmarke", "Beispiel")),
        h("ul", karte("check-circle", "Freigegeben", "Bernd Koller", "Papier Muster GmbH, € 671,30", "14:18"), karte("shield-check", "17 Prüfungen bestanden", "Automatisch", "Summe, UID, IBAN und Duplikat", "14:14"), karte("envelope-simple", "Rechnung eingegangen", "E-Mail", "Anhang gelesen und vorkontiert", "14:14")),
      ),
    ),
    h("div", h("h2", "Jede Rechnung. ", h("em", "Geprüft.")), h("p", "Belegflow liest Rechnungen, prüft sie und bringt sie zur richtigen Person.")),
  );
  formular.onsubmit = (e) => {
    e.preventDefault();
    versuche(async () => {
      await ruf("/api/anmeldung", "POST", { email: formular.elements.email.value, passwort: formular.elements.passwort.value });
      await danach();
    });
  };
  return h("main.anmeldung", h("section.anmeldeseite", h("div.logo", zeichen(), "Belegflow"), formular, h("p.leise.klein", "Demo mit erfundenen Firmen und Belegen")), schaufenster);
}

function gruppen() {
  const n = z.zaehler || {};
  const f = n.freigaben || {};
  const e = n.eingang || {};
  return [
    ["", [["uebersicht", "Dashboard", "house"], ["suche", "Suche", "magnifying-glass"]]],
    [
      "",
      [
        siehtAlles() ? ["eingang/rechnungen", "Eingang", "tray", (e.rechnungen || 0) + (e.vertraege || 0) + (e.dokumente || 0) + (e.erstattungen || 0)] : null,
        ["freigaben/beleg", "Freigaben", "check-circle", (f.beleg || 0) + (f.erstattung || 0) + (f.anforderung || 0)],
        siehtAlles() ? ["zahlungen", "Zahlungen", "coins", n.zahlungen?.offen] : null,
        siehtAlles() ? ["export", "Export", "paper-plane-tilt", n.export?.bereit] : null,
      ],
    ],
    [
      "",
      [
        ["archiv", "Archiv", "archive"],
        ["vertraege", "Verträge", "handshake", n.vertraege],
        ["erstattungen/meine", "Reisen + Auslagen", "airplane-tilt"],
        ["anforderungen/meine", "Bestellanforderungen", "shopping-cart"],
        ["karten", "Kreditkarten", "credit-card", e.transaktionen],
        siehtAlles() ? ["partner", "Geschäftspartner", "buildings"] : null,
        siehtAlles() ? ["nachrichten", "E-Mail Inbox", "envelope-simple"] : null,
      ],
    ],
  ];
}

function menue() {
  return gruppen().map(([titel, eintraege]) =>
    h(
      "div.gruppe",
      titel ? h("p", titel) : null,
      eintraege.filter(Boolean).map(([ziel, text, bild, zahl]) => ziel === "suche" ? h("button", { type: "button", onclick: suchpalette }, icon(bild), h("span", text), h("kbd", "Strg K")) : h("a", { href: adresse(ziel), "data-ziel": ziel.split("/")[0], title: text }, icon(bild), h("span", text), zahl ? h("span.marke2", String(zahl)) : null)),
    ),
  );
}

const VERWANDT = { beleg: "eingang", vergleich: "eingang", erstattung: "erstattungen", anforderung: "anforderungen" };

export function markiere(name) {
  const ziel = VERWANDT[name] || name;
  for (const a of document.querySelectorAll("nav.seitenleiste a[data-ziel]")) {
    const an = a.dataset.ziel === ziel;
    a.classList.toggle("an", an);
    an ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  }
  document.querySelector(".rahmen")?.classList.toggle("voll", name === "beleg");
  document.querySelector(".rahmen")?.classList.remove("offen");
}

export async function frischeZaehler() {
  try {
    z.zaehler = await hole("/zaehler");
  } catch {
    return;
  }
  const liste = document.getElementById("menue");
  if (!liste) return;
  const jetzt = document.querySelector("nav.seitenleiste a.an[data-ziel]")?.dataset.ziel;
  liste.replaceChildren(...menue());
  if (jetzt) markiereZiel(jetzt);
  const glocke = document.getElementById("glocke");
  glocke.querySelector(".marke2")?.remove();
  if (z.zaehler.mitteilungen) glocke.append(h("span.marke2", String(z.zaehler.mitteilungen)));
}

function markiereZiel(ziel) {
  for (const a of document.querySelectorAll("nav.seitenleiste a[data-ziel]")) a.classList.toggle("an", a.dataset.ziel === ziel);
}

async function mandantenwahl() {
  const suche = h("input", { type: "search", placeholder: "Mandant suchen", "aria-label": "Mandant suchen" });
  const liste = h("div.mandanten", h("p.leise", "Wird geladen"));
  const kasten = fenster("Mandanten", h("div.stapel", suche, liste), { breit: true });
  const alle = await ruf("/api/mandanten");
  let nur = "alle";
  const reiter = h("div.reihe");
  const zahlen = (m) => ({
    eingang: m.zaehler.eingang ? m.zaehler.eingang.rechnungen + m.zaehler.eingang.dokumente + m.zaehler.eingang.vertraege : 0,
    freigaben: m.zaehler.freigaben.beleg + m.zaehler.freigaben.erstattung + m.zaehler.freigaben.anforderung,
    zahlungen: m.zaehler.zahlungen?.offen || 0,
    export: m.zaehler.export?.bereit || 0,
  });
  const zeige = () => {
    reiter.replaceChildren(
      ...[["alle", "Alle"], ["eingang", "Eingang"], ["freigaben", "Freigaben"], ["zahlungen", "Zahlungen"], ["export", "Export"]].map(([art, text]) =>
        h("button.chip", { type: "button", class: nur === art ? "an" : "", onclick: () => { nur = art; zeige(); } }, text, h("span", String(art === "alle" ? alle.length : alle.filter((m) => zahlen(m)[art]).length))),
      ),
    );
    const passend = alle.filter((m) => m.name.toLowerCase().includes(suche.value.toLowerCase()) && (nur === "alle" || zahlen(m)[nur]));
    liste.replaceChildren(
      ...passend.map((m) => {
        const n = zahlen(m);
        return h(
          "button.mandant",
          { type: "button", class: m.id === z.m ? "an" : "", onclick: () => { kasten.close(); location.hash = `#/${m.id}/uebersicht`; } },
          person(m.name.replace(/^Muster /, "")),
          h("strong", m.name),
          h("span.reihe.klein", [["eingang", "Eingang"], ["freigaben", "Freigaben"], ["zahlungen", "Zahlungen"], ["export", "Export"]].map(([a, t]) => h("span", { class: n[a] ? "" : "leise" }, `${t} `, h("strong", String(n[a]))))),
        );
      }),
    );
  };
  suche.oninput = zeige;
  liste.before(reiter);
  zeige();
}

async function mitteilungen() {
  const liste = await hole("/mitteilungen");
  const kasten = fenster(
    "Mitteilungen",
    liste.length
      ? h(
          "ul.mitteilungen",
          liste.map((m) => h("li", { class: m.gelesen ? "" : "neu" }, h("a", { href: adresse(m.ziel), onclick: () => kasten.close() }, h("span", m.text), h("time.leise.klein", vorTagen(m.erstellt_am))))),
        )
      : leer("Keine Mitteilungen", "bell"),
  );
  await sende("/mitteilungen/gelesen", {});
  frischeZaehler();
}

export function hochladen() {
  const eingabe = h("input", { type: "file", multiple: true, accept: ".pdf,.png,.jpg,.jpeg,.xml", hidden: true });
  eingabe.onchange = () => versuche(() => lade([...eingabe.files]));
  eingabe.click();
}

export async function lade(dateien) {
  if (!dateien.length) return;
  melde(`${dateien.length} ${dateien.length === 1 ? "Datei wird" : "Dateien werden"} gelesen`);
  const daten = new FormData();
  for (const datei of dateien) daten.append("dateien", datei);
  const ergebnis = await ruf(pfad("/belege"), "POST", daten);
  const gut = ergebnis.filter((e) => !e.fehler);
  if (ergebnis.length === 1 && gut.length) {
    melde(`${ARTEN[gut[0].art]} erfasst`);
    gehe(`beleg/${gut[0].id}`);
    return;
  }
  fenster(
    "Ergebnis",
    h("ul.mitteilungen", ergebnis.map((e) => h("li", e.fehler ? pille("warnung", e.fehler) : pille("empfangen", ARTEN[e.art]), " ", e.id ? h("a", { href: adresse(`beleg/${e.id}`) }, e.dateiname) : e.dateiname))),
  );
  window.dispatchEvent(new Event("belegflow-neu"));
}

function erstellen() {
  const eintraege = [
    ["Beleg hochladen", "upload-simple", hochladen],
    ["Reise oder Auslage", "airplane-tilt", () => gehe("erstattungen/neu")],
    ["Bestellanforderung", "shopping-cart", () => gehe("anforderungen/neu")],
    ["Firmenkarte", "credit-card", () => gehe("karten/neu")],
    hat("buchhaltung", "admin") ? ["Geschäftspartner", "buildings", () => gehe("partner/neu")] : null,
  ].filter(Boolean);
  const kasten = fenster("Erstellen", h("div.auswahl", eintraege.map(([text, bild, tun]) => h("button", { type: "button", onclick: () => { kasten.close(); tun(); } }, icon(bild), text))));
}

function suchpalette() {
  if (document.querySelector("dialog.palette")) return;
  const eingabe = h("input", { type: "search", placeholder: "Belege, Partner, Bestellungen und Seiten suchen", "aria-label": "Suchen" });
  const liste = h("div.treffer");
  const kasten = h("dialog.palette", { "aria-label": "Suche" }, h("div.suchzeile", icon("magnifying-glass"), eingabe), liste);
  const seiten = gruppen()
    .flatMap(([, e]) => e.filter(Boolean))
    .filter(([ziel]) => ziel !== "suche")
    .map(([ziel, text, bild]) => [ziel, text, "", bild]);
  let uhr = null;
  const zeige = (gruppenliste) => {
    liste.replaceChildren(
      ...gruppenliste
        .filter(([, e]) => e.length)
        .flatMap(([titel, e]) => [h("p.leise.klein", titel), ...e.map(([ziel, text, neben, bild]) => h("a", { href: adresse(ziel), onclick: () => kasten.close() }, icon(bild), h("span", text), h("span.leise.klein", neben)))]),
    );
    if (!liste.children.length) liste.append(leer("Nichts gefunden", "magnifying-glass"));
  };
  const suche = async () => {
    const q = eingabe.value.trim();
    const passend = seiten.filter(([, text]) => text.toLowerCase().includes(q.toLowerCase()));
    if (q.length < 2) return zeige([["Seiten", passend]]);
    const t = await hole("/suche", { q });
    if (q !== eingabe.value.trim()) return undefined;
    return zeige([
      ["Belege", t.belege.map((b) => [`beleg/${b.id}`, `${b.partner || b.lieferant || b.dateiname} ${b.nummer || ""}`, `${ARTEN[b.art]} ${euro(b.brutto, b.waehrung)}`, "file-text"])],
      ["Geschäftspartner", t.partner.map((p) => [`partner/${p.id}`, p.name, p.kreditor || "", "buildings"])],
      ["Bestellungen", t.anforderungen.map((a) => [`anforderung/${a.id}`, a.titel, a.nummer || a.lieferant, "shopping-cart"])],
      ["Reisen und Auslagen", t.erstattungen.map((e) => [`erstattung/${e.id}`, e.titel, "", "airplane-tilt"])],
      ["Seiten", passend],
    ]);
  };
  eingabe.oninput = () => {
    clearTimeout(uhr);
    uhr = setTimeout(() => versuche(suche), 160);
  };
  kasten.onkeydown = (e) => {
    const ziele = [...liste.querySelectorAll("a")];
    const stelle = ziele.indexOf(document.activeElement);
    if (e.key === "ArrowDown") ziele[Math.min(stelle + 1, ziele.length - 1)]?.focus();
    else if (e.key === "ArrowUp") (ziele[stelle - 1] || eingabe).focus();
    else if (e.key === "Enter" && document.activeElement === eingabe) ziele[0]?.click();
    else return;
    e.preventDefault();
  };
  kasten.addEventListener("close", () => kasten.remove());
  kasten.onclick = (e) => {
    if (e.target === kasten) kasten.close();
  };
  document.body.append(kasten);
  kasten.showModal();
  versuche(suche);
}

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && z.ich) {
    e.preventDefault();
    suchpalette();
  }
});
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  if (z.ich && e.dataTransfer.files.length && !document.querySelector("dialog")) versuche(() => lade([...e.dataTransfer.files]));
});

async function abmelden() {
  await ruf("/api/anmeldung", "DELETE");
  z.ich = null;
  location.reload();
}

function farbe() {
  const neu = document.documentElement.dataset.farbe === "dunkel" ? "hell" : "dunkel";
  document.documentElement.dataset.farbe = neu;
  merke("farbe", neu);
}

export function baueRahmen() {
  const aktuell = z.ich.mandanten.find((m) => m.id === z.m);
  const mandant = h("button.mandantknopf", { type: "button", onclick: () => versuche(mandantenwahl) }, h("span.zeichen", kurzname(aktuell.name)), h("span", h("strong", aktuell.name)), icon("caret-down"));
  const rahmen = h(
    "div.rahmen",
    h("div.leiste", knopf("", () => rahmen.classList.toggle("offen"), { art: "rund", bild: "list-checks", titel: "Menü" }), h("strong", aktuell.name)),
    h(
      "nav.seitenleiste",
      { "aria-label": "Hauptmenü" },
      h("div.marke", zeichen(), "Belegflow"),
      mandant,
      h("div.oben", knopf("Erstellen", erstellen, { bild: "plus", art: "erstellen" })),
      h("div", { id: "menue" }, menue()),
      h(
        "div.unten",
        h("button", { type: "button", onclick: hochladen }, icon("upload-simple"), h("span", "Dokumente hochladen")),
        h("button", { type: "button", id: "glocke", onclick: () => versuche(mitteilungen) }, icon("bell"), h("span", "Mitteilungen")),
        siehtAlles() ? h("a", { href: adresse("einstellungen/mandant"), "data-ziel": "einstellungen" }, icon("gear"), h("span", "Einstellungen")) : null,
      ),
      h(
        "div.nutzer",
        h("a", { href: adresse("profil"), "data-ziel": "profil" }, person(z.ich.name), h("span", z.ich.name)),
        h("div.reihe", knopf("", farbe, { art: "rund leise", bild: "moon", titel: "Hell oder dunkel" }), knopf("", abmelden, { art: "rund leise", bild: "sign-out", titel: "Abmelden" })),
      ),
    ),
    h("main", { id: "inhalt", tabIndex: -1 }),
  );
  return rahmen;
}

export { frage };
