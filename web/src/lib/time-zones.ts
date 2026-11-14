// A time zone by its city, as a person says it: "New York (Eastern time)", never the id the settings hold
// ("America/New_York"). The city is the last part of the id; the zone's general name is the browser's own.

/** The city of a time zone id, with spaces for underscores. */
export function zoneCity(id: string): string {
  const last = id.split("/").pop() ?? id;
  return last.replace(/_/g, " ");
}

// What the browser says about a zone is worked out once: asking it for each of the four hundred zones is slow (it is most of
// what a screen with the list costs to draw), and the answer does not change.
const names = new Map<string, string>();

/** The zone's general name in English ("Eastern time"), or empty where the browser has none. */
function zoneName(id: string): string {
  const known = names.get(id);
  if (known !== undefined) return known;
  const name = workOutName(id);
  names.set(id, name);
  return name;
}

function workOutName(id: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: id, timeZoneName: "longGeneric" }).formatToParts(new Date(0));
    return (parts.find((p) => p.type === "timeZoneName")?.value ?? "").replace(/ (Standard|Daylight|Summer) /, " ").replace(/ Time$/, " time");
  } catch {
    return "";
  }
}

/** "New York (Eastern time)". A zone whose general name is its city's (or that has none) shows the city alone. */
export function zoneLabel(id: string): string {
  if (!id.includes("/")) return id; // UTC and the like name no city
  const city = zoneCity(id);
  const name = zoneName(id);
  return name && name !== city && name !== id ? `${city} (${name})` : city;
}

/** The zones with their labels, in the order a person looks them up: by label. */
export function zoneChoices(ids: string[]): { id: string; label: string }[] {
  const seen = new Set<string>();
  return ids
    .filter((id) => id && !seen.has(id) && !!seen.add(id))
    .map((id) => ({ id, label: zoneLabel(id) }))
    .sort((a, b) => a.label.localeCompare(b.label, "en"));
}

// An offset is the zone's offset now, so what is worked out is kept for the hour it was asked in.
const offsets = new Map<string, string>();
let offsetsHour = -1;

/** The zone's offset from UTC now, as a person writes it, with a space and a true minus sign so it never reads as a
 * code ("UTC −8", "UTC +5:30", "UTC"). */
export function zoneOffset(id: string): string {
  const hour = Math.floor(Date.now() / 3_600_000);
  if (hour !== offsetsHour) {
    offsets.clear();
    offsetsHour = hour;
  }
  const known = offsets.get(id);
  if (known !== undefined) return known;
  const offset = workOutOffset(id);
  offsets.set(id, offset);
  return offset;
}

function workOutOffset(id: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: id, timeZoneName: "shortOffset" }).formatToParts(new Date());
    return (parts.find((p) => p.type === "timeZoneName")?.value ?? "").replace(/^GMT(?=[+\u2212-])/, "UTC ").replace("GMT", "UTC").replace("-", "\u2212");
  } catch {
    return "";
  }
}
