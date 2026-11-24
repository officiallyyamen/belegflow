export const z = { ich: null, m: null, stamm: null, zaehler: null };

export function h(art, eigenschaften, ...kinder) {
  if (eigenschaften === null || typeof eigenschaften !== "object" || eigenschaften instanceof Node || Array.isArray(eigenschaften)) {
    if (eigenschaften !== undefined) kinder.unshift(eigenschaften);
    eigenschaften = {};
  }
  const [name, ...klassen] = art.split(".");
  const knoten = document.createElement(name || "div");
  if (klassen.length) knoten.className = klassen.join(" ");
  for (const [schluessel, wert] of Object.entries(eigenschaften)) {
    if (wert === null || wert === undefined || wert === false) continue;
    if (schluessel === "class") knoten.className = `${knoten.className} ${wert}`.trim();
    else if (schluessel.includes("-") || schluessel === "role") knoten.setAttribute(schluessel, wert);
    else knoten[schluessel] = wert;
  }
  knoten.append(...kinder.flat(3).filter((kind) => kind !== null && kind !== undefined && kind !== false));
  return knoten;
}

export function s(art, eigenschaften = {}, ...kinder) {
  const knoten = document.createElementNS("http://www.w3.org/2000/svg", art);
  for (const [name, wert] of Object.entries(eigenschaften)) knoten.setAttribute(name, wert);
  knoten.append(...kinder);
  return knoten;
}

export const icon = (name) => s("svg", { class: "icon", "aria-hidden": "true" }, s("use", { href: `/static/icons.svg#${name}` }));

export function melde(text, fehler = false) {
  document.querySelector(".meldung")?.remove();
  const box = h("div.meldung", { class: fehler ? "fehler" : "", role: fehler ? "alert" : "status" }, icon(fehler ? "warning-circle" : "check-circle"), text);
  document.body.append(box);
  setTimeout(() => box.remove(), fehler ? 6500 : 3200);
}

export async function ruf(pfad, methode = "GET", inhalt = null) {
  const optionen = { method: methode, headers: { "X-Belegflow": "1" } };
  if (inhalt instanceof FormData) optionen.body = inhalt;
  else if (inhalt !== null) {
    optionen.body = JSON.stringify(inhalt);
    optionen.headers["Content-Type"] = "application/json";
  }
  const antwort = await fetch(pfad, optionen);
  if (!antwort.ok) {
    const daten = await antwort.json().catch(() => ({}));
    const fehler = new Error(typeof daten.detail === "string" ? daten.detail : "Das hat nicht geklappt");
    Object.assign(fehler, { status: antwort.status, daten });
    throw fehler;
  }
  return antwort.status === 204 ? null : antwort.headers.get("content-type")?.includes("json") ? antwort.json() : antwort;
}

export const pfad = (teil) => `/api/m/${z.m}${teil}`;
export const hole = (teil, abfrage) => ruf(pfad(teil) + frageteil(abfrage));
export const sende = (teil, inhalt = {}, methode = "POST") => ruf(pfad(teil), methode, inhalt);
export const loesche = (teil) => ruf(pfad(teil), "DELETE");

function frageteil(abfrage) {
  if (!abfrage) return "";
  const gefuellt = Object.entries(abfrage).filter(([, wert]) => wert !== null && wert !== undefined && wert !== "" && wert !== false);
  return gefuellt.length ? `?${new URLSearchParams(gefuellt)}` : "";
}

export async function versuche(aufgabe) {
  try {
    return await aufgabe();
  } catch (fehler) {
    if (fehler.status === 401 && z.ich) {
      z.ich = null;
      location.reload();
      return undefined;
    }
    melde(fehler.message, true);
    return undefined;
  }
}

export const hat = (...rollen) => rollen.some((rolle) => z.stamm?.rollen.includes(rolle));
export const siehtAlles = () => hat("admin", "buchhaltung", "einsicht");
export const euro = (wert, waehrung = "EUR") =>
  wert === null || wert === undefined ? "" : Number(wert).toLocaleString("de-AT", { style: "currency", currency: waehrung });
export const rund = (wert) => Number(wert).toLocaleString("de-AT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
export const tag = (wert) => (wert ? new Date(wert.length === 10 ? `${wert}T00:00` : wert).toLocaleDateString("de-AT") : "");
export const zeit = (wert) => (wert ? new Date(wert).toLocaleString("de-AT", { dateStyle: "short", timeStyle: "short" }) : "");
export const heute = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

export function vorTagen(wert) {
  const tage = Math.round((new Date(`${heute()}T00:00`) - new Date(`${wert.slice(0, 10)}T00:00`)) / 86400000);
  if (tage === 0) return "heute";
  if (tage === 1) return "gestern";
  if (tage === -1) return "morgen";
  return tage > 0 ? `vor ${tage} Tagen` : `in ${-tage} Tagen`;
}

export function zahlwert(text) {
  const sauber = String(text ?? "").replace(/[\s€]/g, "");
  return sauber.includes(",") ? sauber.replaceAll(".", "").replace(",", ".") : sauber;
}

export const kurzname = (name) =>
  (name || "?")
    .split(/\s+/)
    .map((teil) => teil[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

export function gehe(ziel) {
  const neu = `#/${z.m}/${ziel}`;
  if (location.hash === neu) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = neu;
}

export const adresse = (ziel) => `#/${z.m}/${ziel}`;

export function merke(name, wert) {
  try {
    if (wert === undefined) return localStorage.getItem(`belegflow-${name}`);
    localStorage.setItem(`belegflow-${name}`, wert);
  } catch {
    return null;
  }
  return wert;
}

export const name = (art, code) => {
  const eintrag = z.stamm?.werte[art]?.find((w) => w.code === code);
  return eintrag ? `${code} ${eintrag.name}` : code || "";
};
