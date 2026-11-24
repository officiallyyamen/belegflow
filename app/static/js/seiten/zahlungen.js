import { euro, gehe, h, hat, heute, hole, icon, melde, pfad, sende, tag, vorTagen } from "../kern.js";
import { feld, knopf, pille, tabelle } from "../teile.js";

export async function seite() {
  const gewaehlt = new Set();
  const mitSkonto = new Set();
  const datum = feld({ name: "tag", text: "Ausführung am", art: "date" }, heute());
  const offenKasten = h("div.karte.eng");
  const verlaufKasten = h("div");
  const offenZahl = h("strong.mittel");
  const wieviele = h("p.klein");
  const summe = h("strong.mittel");
  const los = knopf("SEPA-Datei erstellen", zahlen, { art: "haupt", bild: "bank", gesperrt: true });
  const schluessel = (p) => `${p.art}-${p.id}`;
  const betrag = (p) => (mitSkonto.has(schluessel(p)) ? p.skonto_betrag : p.betrag);
  const geaendert = () => {
    wieviele.textContent = gewaehlt.size === 1 ? "1 Posten ausgewählt" : `${gewaehlt.size} Posten ausgewählt`;
    summe.textContent = euro([...gewaehlt].reduce((s, p) => s + Number(betrag(p)), 0));
    los.disabled = !gewaehlt.size;
  };

  async function zahlen() {
    const lauf = await sende("/zahlungen", {
      posten: [...gewaehlt].map((p) => ({ art: p.art, id: p.id, skonto: mitSkonto.has(schluessel(p)) })),
      ausfuehrung: datum.querySelector("input").value || heute(),
    });
    melde(`Zahlung über ${euro(lauf.summe)} angelegt`);
    gewaehlt.clear();
    mitSkonto.clear();
    location.assign(pfad(`/zahlungen/${lauf.id}/datei`));
    await neu();
  }

  async function neu() {
    const [offen, fertig] = await Promise.all([hole("/zahlungen/offen"), hole("/zahlungen")]);
    offenKasten.replaceChildren(
      tabelle(
        [
          { titel: "Empfänger", wert: (p) => h("div", h("strong", p.name), h("p.leise.klein", [p.art === "erstattung" ? "Erstattung" : "Rechnung", p.nummer].join(" "))) },
          { titel: "IBAN", wert: (p) => (p.hindernis ? pille("warnung", p.hindernis) : h("span.leise", p.iban)), klasse: "breitab" },
          { titel: "Fällig", wert: (p) => (p.faellig_am ? h("span", { class: p.faellig_am < heute() ? "rot" : "", title: tag(p.faellig_am) }, vorTagen(p.faellig_am)) : "") },
          {
            titel: "Skonto",
            wert: (p) =>
              p.skonto_betrag
                ? h("label.haken", h("input", { type: "checkbox", checked: mitSkonto.has(schluessel(p)), onclick: (e) => e.stopPropagation(), onchange: (e) => { e.target.checked ? mitSkonto.add(schluessel(p)) : mitSkonto.delete(schluessel(p)); geaendert(); } }), `${euro(p.skonto_betrag)} bis ${tag(p.skonto_bis)}`)
                : "",
          },
          { titel: "Betrag", wert: (p) => h("strong", euro(p.betrag)), klasse: "zahl" },
        ],
        offen,
        {
          leertext: "Nichts zu bezahlen",
          beiKlick: (p) => gehe(`${p.art}/${p.id}`),
          wahl: hat("buchhaltung", "admin") ? { gewaehlt, geaendert, sperre: (p) => Boolean(p.hindernis) } : null,
        },
      ),
    );
    offenZahl.textContent = euro(offen.reduce((s, p) => s + Number(p.betrag), 0));
    verlaufKasten.replaceChildren(
      ...(fertig.length
        ? fertig.map((l) => h("a.historie", { href: pfad(`/zahlungen/${l.id}/datei`), title: "SEPA-Datei laden" }, icon("check-circle"), h("div", h("strong", `${l.von}, ${tag(l.ausfuehrung)}`), h("div.titelzeile", h("span", `${l.posten.length} Posten`), h("span", euro(l.summe))))))
        : [h("p.leise.klein", "Noch keine Zahlungen")]),
    );
    geaendert();
  }
  await neu();
  const darf = hat("buchhaltung", "admin");
  return h(
    "div.zweiteiler",
    h("div.seite", h("header", h("h1", "Zahlungen"), h("p.leise", "Noch nicht bezahlt: ", offenZahl)), offenKasten, h("section", h("h2.abschnitttitel", "Bisherige Zahlungen"), verlaufKasten)),
    darf ? h("aside.teilrechts", h("h2", "SEPA-Datei"), h("p.leise.klein", "Für den Upload im Onlinebanking"), datum, h("div.summenkarte", wieviele, h("div.titelzeile", h("span", "Zahlungssumme"), summe)), h("p.leise.klein", "Nach dem Erstellen gelten die Posten als bezahlt"), los) : null,
  );
}
