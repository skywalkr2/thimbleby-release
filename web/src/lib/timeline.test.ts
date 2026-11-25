import { LABEL_MAX, LABEL_PAD, labelMaxFor, labelWidth, packLane, TOUCH } from "./timeline";

const one = (title: string, start: string) => ({ title, start, end: start });

test("a mark on one day takes room for its title, so a neighbor goes to the next row", () => {
  const { placed, rows } = packLane([one("Send the quote", "2026-11-03"), one("Pay the deposit", "2026-11-04")], "2026-11-02", 14, 40, (i) => i.title);
  expect(placed[0].w).toBe(TOUCH + LABEL_PAD + labelWidth("Send the quote"));
  expect(placed[0].point).toBe(true);
  expect(rows).toBe(2);
});

test("a title that has no room on the right goes on the mark's left", () => {
  const { placed } = packLane([one("Last day of the quarter", "2026-11-15")], "2026-11-02", 14, 40, (i) => i.title);
  expect(placed[0].flip).toBe(true);
  expect(placed[0].x + placed[0].w).toBeLessThanOrEqual(14 * 40);
});

test("with no titles asked for, a one-day mark is only its own day's width", () => {
  const { placed } = packLane([one("Send the quote", "2026-11-03")], "2026-11-02", 14, 10);
  expect(placed[0].w).toBe(TOUCH);
  expect(placed[0].point).toBeUndefined();
});

test("the room a title may take widens with the page: 172 px at 1024 and below, 240 px at 1440 and above", () => {
  expect([labelMaxFor(null), labelMaxFor(800), labelMaxFor(1024)]).toEqual([LABEL_MAX, LABEL_MAX, 172]);
  expect(labelMaxFor(1440)).toBe(240);
  expect(labelMaxFor(2000)).toBe(240);
  expect(labelMaxFor(1232)).toBeGreaterThan(172);
  expect(labelMaxFor(1232)).toBeLessThan(240);
});

test("a long title takes the room it is given and the rest is a second line, never a wider label", () => {
  const long = "Quarterly planning review with the whole leadership group";
  expect(labelWidth(long, 240)).toBe(240);
  const { placed } = packLane([one(long, "2026-11-03")], "2026-11-02", 28, 40, (i) => i.title, 240);
  expect(placed[0].w).toBe(TOUCH + LABEL_PAD + 240);
});

test("past items, all held at one place, stack by the date they were due, earliest on top, whatever their words' widths", () => {
  const titles = ["A rather long title for the middle one", "Short", "A title of middling length", "Tiny"];
  const dues = ["2026-10-21", "2026-10-14", "2026-10-19", "2026-10-16"];
  // Each is held at today (the stack), and says its own day in `detail`.
  const items = titles.map((title, n) => ({ ...one(title, "2026-11-02"), detail: dues[n] }));
  const { placed } = packLane(items, "2026-11-02", 14, 40, (i) => i.title, undefined, (i) => i.detail);
  expect([...placed].sort((a, b) => a.row - b.row).map((p) => p.item.detail)).toEqual([...dues].sort());
});
