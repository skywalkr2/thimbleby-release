import { zoneChoices, zoneCity, zoneLabel, zoneOffset } from "./time-zones";

test("a zone is its city and its general name, never its id", () => {
  expect(zoneCity("America/Argentina/Buenos_Aires")).toBe("Buenos Aires");
  expect(zoneLabel("America/New_York")).toBe("New York (Eastern time)");
  expect(zoneLabel("America/Chicago")).toBe("Chicago (Central time)");
  expect(zoneLabel("Europe/Paris")).not.toMatch(/\//);
});

test("a zone with no city is shown as it is", () => {
  expect(zoneLabel("UTC")).toBe("UTC");
});

test("the choices are in the order of their labels, each zone once", () => {
  const found = zoneChoices(["Europe/Paris", "America/New_York", "Europe/Paris", "America/Chicago"]);
  expect(found.map((c) => c.id)).toEqual(["America/Chicago", "Europe/Paris", "America/New_York"].sort((a, b) => zoneLabel(a).localeCompare(zoneLabel(b), "en")));
  expect(new Set(found.map((c) => c.id)).size).toBe(found.length);
});

test("an offset is spaced, with a true minus sign, so it never reads as a code", () => {
  expect(zoneOffset("Asia/Kolkata")).toBe("UTC +5:30");
  expect(zoneOffset("Pacific/Honolulu")).toBe("UTC −10");
});
