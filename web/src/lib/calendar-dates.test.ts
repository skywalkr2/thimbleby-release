// A calendar date is a date with no time and no zone: a due day or an all-day event stays on its day whatever zone the
// computer is set to, and a time typed for an event is on the person's own clock, not the computer's.
import { afterEach, expect, it } from "vitest";
import { clockDay, day, momentOf, monthDay, setClockZone, shortDay, shortRange } from "./dates";

const was = process.env.TZ;
afterEach(() => {
  if (was === undefined) delete process.env.TZ;
  else process.env.TZ = was;
  setClockZone(undefined);
});

const ZONES = ["Pacific/Honolulu", "America/New_York", "America/Chicago", "America/Los_Angeles", "Pacific/Auckland"];

it("a due day made at Eastern is the same day when the computer moves to Central, Pacific or anywhere else", () => {
  process.env.TZ = "America/New_York";
  const made = { due: "2030-03-23" };
  for (const zone of ZONES) {
    process.env.TZ = zone;
    expect(monthDay(made.due), zone).toBe("Mar 23");
    expect(day(made.due), zone).toMatch(/Mar 23/);
    expect(shortDay(made.due), zone).toMatch(/23/);
    expect(shortRange("2030-03-23", "2030-03-25"), zone).toEqual({ start: "Mar 23", end: "25" });
  }
});

it("an all-day event and a day written with no zone keep their day in every zone of the computer", () => {
  for (const zone of ZONES) {
    process.env.TZ = zone;
    expect(clockDay("2030-03-23"), zone).toBe("2030-03-23");
    expect(clockDay("2030-03-23T00:00:00"), zone).toBe("2030-03-23");
  }
});

it("a time typed for an event is on the person's own clock whatever zone the computer is in", () => {
  setClockZone("America/New_York");
  for (const zone of ZONES) {
    process.env.TZ = zone;
    expect(momentOf("2030-03-23T09:00")?.toISOString(), zone).toBe("2030-03-23T13:00:00.000Z");
  }
});
