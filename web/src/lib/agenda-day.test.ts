import type { S } from "./api";
import { hasEnded, layOutDay } from "./agenda-day";

const entry = (title: string, start: string, end?: string, extra: Partial<S["AgendaItemView"]> = {}): S["AgendaItemView"] =>
  ({ snapshot: title, source: "", title, start, end, all_day: false, cancelled: false, own: false, open_items: 0, days: ["2026-11-10"], ...extra }) as S["AgendaItemView"];

const NOW = new Date("2026-11-10T16:05:00");

test("a day's entries are in the order they start, the app's own among a calendar's, with what has ended apart (S-0342)", () => {
  const day = layOutDay(
    [
      entry("Class", "2026-11-10T17:00:00", "2026-11-10T18:00:00", { own: true }),
      entry("All day", "2026-11-10", undefined, { all_day: true }),
      entry("Review", "2026-11-10T15:30:00", "2026-11-10T16:30:00"),
      entry("Tablets", "2026-11-10T08:00:00", "2026-11-10T08:15:00", { own: true }),
    ],
    NOW,
  );
  expect(day.allDay.map((e) => e.title)).toEqual(["All day"]);
  expect(day.past.map((e) => e.title)).toEqual(["Tablets"]);
  expect(day.upcoming.map((e) => e.title)).toEqual(["Review", "Class"]);
  expect(hasEnded(entry("Review", "2026-11-10T15:30:00", "2026-11-10T16:30:00"), NOW)).toBe(false);
  expect(hasEnded(entry("Day", "2026-11-10", undefined, { all_day: true }), NOW)).toBe(false);
});
