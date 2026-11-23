import { calendarNames, addMonths, foldIdentical, clashGroups, type ClashLink, gridHours, hourLabel, hourOf, minutesOf, withoutAddress, mergeClashSpans, moveBy, placeOverlaps, rangeOf, rememberView, startOfMonth, startOfWeek, storedView, weekdayIndex } from "./calendar";

const MON = [0, 1, 2, 3, 4];

test("a week starts on the configured day and counts weekdays from Monday", () => {
  // The 28th of that month is a Wednesday.
  expect(weekdayIndex("2026-10-28")).toBe(2);
  expect(startOfWeek("2026-10-28", 0)).toBe("2026-10-26");
  expect(startOfWeek("2026-10-26", 0)).toBe("2026-10-26");
  expect(startOfWeek("2026-10-28", 6)).toBe("2026-10-25");
  expect(startOfWeek("2026-10-25", 6)).toBe("2026-10-25");
  expect(startOfMonth("2026-10-28")).toBe("2026-10-01");
});

test("each view's range: a day, the week's working days, the whole week, and six weeks for a month", () => {
  expect(rangeOf("day", "2026-10-28", 0, MON)).toEqual({ first: "2026-10-28", days: 1, shown: ["2026-10-28"] });
  const work = rangeOf("work_week", "2026-10-28", 0, MON);
  expect([work.first, work.days, work.shown[0], work.shown.length, work.shown.at(-1)]).toEqual(["2026-10-26", 7, "2026-10-26", 5, "2026-10-30"]);
  const week = rangeOf("week", "2026-10-28", 6, MON);
  expect([week.first, week.shown.length, week.shown[0], week.shown.at(-1)]).toEqual(["2026-10-25", 7, "2026-10-25", "2026-10-31"]);
  // Working days that don't start on the week's first day are still the working days.
  expect(rangeOf("work_week", "2026-10-28", 6, MON).shown).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]);
  const month = rangeOf("month", "2026-10-28", 0, MON);
  expect([month.first, month.days, month.shown.length, month.shown.at(-1)]).toEqual(["2026-09-28", 42, 42, "2026-11-08"]);
});

test("the arrows move a day, a week or a month, keeping the day of the month where the month has it", () => {
  expect(moveBy("day", "2026-10-28", 1)).toBe("2026-10-29");
  expect(moveBy("day", "2026-10-28", -7)).toBe("2026-10-21");
  expect(moveBy("week", "2026-10-28", 1)).toBe("2026-11-04");
  expect(moveBy("work_week", "2026-10-28", -1)).toBe("2026-10-21");
  expect(moveBy("month", "2026-10-28", 1)).toBe("2026-11-28");
  expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
  expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
  expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
});

test("times on the person's clock and the hours of a setting", () => {
  expect(minutesOf("2026-10-26T09:30:00+00:00")).toBe(570);
  expect(minutesOf("2026-10-26")).toBeNull();
  expect(minutesOf(undefined)).toBeNull();
  expect(hourOf("07:00")).toBe(7);
  expect(hourOf("18:30", true)).toBe(19);
  expect(hourOf("19:00", true)).toBe(19);
});

test("the grid shows the working day, grown to the earliest entry's hour and the hour after the last, with the hour now when today is in view", () => {
  // With nothing timed and no now, the configured hours.
  expect(gridHours([], "07:00", "19:00")).toEqual({ from: 7, to: 19 });
  // Entries inside the working day change nothing: the whole day is shown, not only the hours around the entries.
  expect(gridHours([{ start: 12 * 60, end: 13 * 60 }], "07:00", "19:00")).toEqual({ from: 7, to: 19 });
  // Entries from 6 PM to 9 PM: the day grows to the last entry's end.
  expect(gridHours([{ start: 18 * 60, end: 21 * 60 }], "07:00", "19:00")).toEqual({ from: 7, to: 21 });
  // An entry cut off by an hour boundary is whole: 9:15 PM rounds the end up.
  expect(gridHours([{ start: 21 * 60, end: 22 * 60 + 15 }], "07:00", "19:00")).toEqual({ from: 7, to: 23 });
  // An early entry grows it at the start.
  expect(gridHours([{ start: 5 * 60 + 30, end: 6 * 60 }], "07:00", "19:00")).toEqual({ from: 5, to: 19 });
  // A short working day keeps at least 8 hours.
  expect(gridHours([], "09:00", "12:00")).toEqual({ from: 4, to: 12 });
  // Today in view: the hour now is in the range.
  expect(gridHours([], "07:00", "19:00", 21 * 60 + 20)).toEqual({ from: 7, to: 22 });
});


test("entries that overlap share the width side by side, and ones that don't keep all of it", () => {
  const at = (name: string, start: number, end: number) => ({ item: name, start, end });
  const placed = placeOverlaps([at("c", 9 * 60 + 45, 11 * 60), at("a", 9 * 60, 10 * 60), at("b", 9 * 60 + 15, 9 * 60 + 30), at("alone", 13 * 60, 14 * 60)]);
  const by = Object.fromEntries(placed.map((p) => [p.item, [p.col, p.cols]]));
  // a overlaps b and c; b and c don't overlap each other, so they share a column and the cluster has two.
  expect(by).toEqual({ a: [0, 2], b: [1, 2], c: [1, 2], alone: [0, 1] });
  expect(placeOverlaps([])).toEqual([]);
});

test("the view is remembered, and a browser that won't keep it gives the default", () => {
  window.localStorage.clear();
  expect(storedView()).toBe("work_week");
  rememberView("month");
  expect(storedView()).toBe("month");
  window.localStorage.setItem("cockpit:schedule-view", "fortnight");
  expect(storedView()).toBe("work_week");
  const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(storedView()).toBe("work_week");
  expect(() => rememberView("day")).not.toThrow();
  blocked.mockRestore();
  set.mockRestore();
});

describe("clashGroups", () => {
  const at = (title: string, start: number, end: number) => ({ item: title, start, end });
  const pairs = (...named: Array<[string, string, ClashLink]>) => (a: string, b: string) => named.find(([x, y]) => x === a && y === b)?.[2];
  const overlap = (minutes: number): ClashLink => ({ kind: "overlap", minutes, travel: 30 });

  test("entries the engine links are one group, from the first start to the last end, with the overlap it names", () => {
    const [group, ...rest] = clashGroups([at("a", 9 * 60, 10 * 60), at("b", 9 * 60 + 30, 10 * 60 + 30), at("lone", 13 * 60, 14 * 60)], pairs(["a", "b", overlap(30)]));
    expect(rest).toEqual([]);
    expect(group.items).toEqual(["a", "b"]);
    expect([group.start, group.end, group.overlap, group.travel]).toEqual([9 * 60, 10 * 60 + 30, 30, 0]);
  });

  test("two entries that overlap on the screen are no group unless the engine links them", () => {
    expect(clashGroups([at("a", 9 * 60, 10 * 60), at("b", 9 * 60 + 30, 10 * 60 + 30)], () => undefined)).toEqual([]);
  });

  test("a run of links through a middle entry is one group, in either order of the pair", () => {
    const [chain] = clashGroups([at("a", 60, 120), at("b", 90, 150), at("c", 140, 200)], pairs(["b", "a", overlap(30)], ["b", "c", overlap(10)]));
    expect(chain.items).toEqual(["a", "b", "c"]);
    expect(chain.overlap).toBe(30);
  });

  test("a group that clashes only for want of travel time says how long the places need", () => {
    const [group] = clashGroups([at("a", 60, 120), at("b", 130, 180)], pairs(["a", "b", { kind: "travel", minutes: 20, travel: 30 }]));
    expect([group.overlap, group.travel]).toEqual([0, 30]);
  });
});

describe("mergeClashSpans", () => {
  const at = (item: string, start: number, end: number) => ({ item, start, end });
  const group = (items: string[], start: number, end: number) => ({ items, start, end, overlap: 20, travel: 0, short: 0 });

  test("an entry that overlaps the start of a clash group is laid out with it, and one that overlaps nothing stays alone", () => {
    // The picture: a meeting from 2:08 into a group that starts at 2:30, whose members overlap in a chain.
    const spans = [at("walk", 128 + 720, 190 + 720), at("budget", 150 + 720, 210 + 720), at("supplier", 180 + 720, 240 + 720), at("fitting", 200 + 720, 260 + 720), at("later", 20 * 60, 21 * 60)];
    const { blocks, rest } = mergeClashSpans(spans, [group(["budget", "supplier", "fitting"], 150 + 720, 260 + 720)]);
    expect(rest).toEqual(["later"]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].items).toEqual(["walk", "budget", "supplier", "fitting"]);
    expect(blocks[0].others).toEqual(["walk"]);
    expect([blocks[0].start, blocks[0].end]).toEqual([128 + 720, 260 + 720]);
  });

  test("a block that grows to take one entry takes the next one it then overlaps, and two groups that overlap are one block", () => {
    const spans = [at("a", 60, 120), at("b", 100, 160), at("c", 150, 200), at("x", 110, 130), at("y", 190, 230)];
    const { blocks, rest } = mergeClashSpans(spans, [group(["a", "b"], 60, 160), group(["c", "y"], 150, 230)]);
    expect(rest).toEqual([]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].items.sort()).toEqual(["a", "b", "c", "x", "y"]);
  });

  test("a block grown to hold its titles takes the next block, and keeps the entries it had absorbed", () => {
    const spans = [at("walk", 60, 130), at("a", 90, 150), at("b", 100, 160), at("c", 200, 260), at("d", 210, 270)];
    const first = mergeClashSpans(spans, [group(["a", "b"], 90, 160), group(["c", "d"], 200, 270)]);
    expect(first.blocks.map((b) => [b.start, b.end, b.others])).toEqual([[60, 160, ["walk"]], [200, 270, []]]);
    // The first block needs until 210 to name its meetings whole: it now reaches the second one.
    const grown = mergeClashSpans(spans, [{ ...first.blocks[0], end: 210 }, first.blocks[1]]);
    expect(grown.blocks).toHaveLength(1);
    expect(grown.blocks[0].items.sort()).toEqual(["a", "b", "c", "d", "walk"]);
    expect(grown.blocks[0].others).toEqual(["walk"]);
  });

  test("a group nothing overlaps is returned as it is, and with no groups every entry is ordinary", () => {
    const spans = [at("a", 60, 120), at("b", 90, 150), at("z", 300, 360)];
    const { blocks, rest } = mergeClashSpans(spans, [group(["a", "b"], 60, 150)]);
    expect(blocks.map((b) => [b.items, b.others])).toEqual([[["a", "b"], []]]);
    expect(rest).toEqual(["z"]);
    expect(mergeClashSpans(spans, [])).toEqual({ blocks: [], rest: ["a", "b", "z"] });
  });
});

test("an hour on the grid's edge drops its empty minutes", () => {
  expect(hourLabel("10:00 AM")).toBe("10 AM");
  expect(hourLabel("12:00 PM")).toBe("12 PM");
  expect(hourLabel("09:00")).toBe("09");
  expect(hourLabel("10:30 AM")).toBe("10:30 AM");
});

test("a calendar's label never says the account's address or the start of it", () => {
  expect(withoutAddress("Your calendar, avery.lane@example.com", "avery.lane@example.com")).toBe("Your calendar");
  expect(withoutAddress("Your calendar, avery.lane", "avery.lane@example.com")).toBe("Your calendar");
  expect(withoutAddress("Work, a@example.com")).toBe("Work");
  expect(withoutAddress("avery.lane@example.com", "avery.lane@example.com")).toBe("");
  expect(withoutAddress("Holidays", "x@example.com")).toBe("Holidays");
});

test("identical entries fold into one with a count, in the order each first appears", () => {
  const items = [
    { title: "Holiday", id: 1 },
    { title: "Offsite", id: 2 },
    { title: "Holiday", id: 3 },
    { title: "Holiday", id: 4 },
  ];
  const folded = foldIdentical(items, (i) => i.title);
  expect(folded.map((f) => [f.item.id, f.count])).toEqual([
    [1, 3],
    [2, 1],
  ]);
  expect(foldIdentical([], () => "x")).toEqual([]);
});

describe("calendarNames", () => {
  const side = (id: string) => ({ "SIDE-P": "Personal", "SIDE-W": "Studio" })[id];
  const cal = (id: string, label: string, account: string, sides: string[]) => ({ id, label, account, sides });
  const words = { numbered: (name: string, n: number) => `${name} (${n})`, fallback: "Calendar" };
  const all = (m: Map<string, string>) => [...m.values()].join(" | ");

  test("a calendar linked to one side is called that side, not its account's label", () => {
    const names = calendarNames([cal("a", "Your calendar, avery.lane", "avery.lane@example.com", ["SIDE-P"]), cal("b", "Your calendar, studio", "studio@example.com", ["SIDE-W"])], side, words);
    expect([names.get("a"), names.get("b")]).toEqual(["Personal", "Studio"]);
  });

  test("two calendars on the same side are told apart by a number, never by a part of an address", () => {
    const names = calendarNames([cal("a", "Your calendar, avery.lane", "avery.lane@example.com", ["SIDE-P"]), cal("b", "Your calendar, avery.lane.home", "avery.lane.home@example.com", ["SIDE-P"])], side, words);
    expect([names.get("a"), names.get("b")]).toEqual(["Personal", "Personal (2)"]);
    expect(all(names)).not.toMatch(/avery|home|@/);
  });

  test("a name the person gave is kept, and a calendar with no side keeps its label without its address", () => {
    const names = calendarNames([cal("a", "Family", "avery.lane@example.com", ["SIDE-P"]), cal("b", "Your calendar, avery.lane.home", "avery.lane.home@example.com", ["SIDE-P"]), cal("c", "Holidays", "x@example.com", []), cal("d", "Calendar, x@example.com", "x@example.com", [])], side, words);
    expect([names.get("a"), names.get("b"), names.get("c"), names.get("d")]).toEqual(["Family", "Personal", "Holidays", "Calendar"]);
  });
});

test("a work week holds the whole week when today is a day off, so no day is skipped and today is in it", () => {
  const week = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"];
  // A Saturday and a Sunday; the week starts on Monday (0) and the working days are Monday to Friday.
  expect(rangeOf("work_week", "2026-11-14", 0, MON, "2026-11-14").shown).toEqual(week);
  expect(rangeOf("work_week", "2026-11-15", 0, MON, "2026-11-15").shown).toEqual(week);
  // Another week, or a working day, is the working days alone.
  expect(rangeOf("work_week", "2026-11-21", 0, MON, "2026-11-14").shown).toHaveLength(5);
  expect(rangeOf("work_week", "2026-11-12", 0, MON, "2026-11-12").shown).toHaveLength(5);
});
