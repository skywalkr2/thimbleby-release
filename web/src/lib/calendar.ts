// The calendar page's arithmetic (design 7.7): which days each view shows, how far an arrow moves, where an entry sits on
// the time grid and how entries that overlap share a column. Plain functions of dates and numbers, so the screen only draws.
// Days are yyyy-mm-dd text on the person's own calendar; weekdays count from Monday as 0.
import { addDays } from "./dates";

export type CalendarView = "day" | "work_week" | "week" | "month" | "timeline";
export const VIEWS: readonly CalendarView[] = ["day", "work_week", "week", "month", "timeline"];

const KEY = "cockpit:schedule-view";
/** What a person who has never chosen sees: the working days of the week, as a desktop calendar starts. */
export const DEFAULT_VIEW: CalendarView = "work_week";
const isView = (v: unknown): v is CalendarView => typeof v === "string" && (VIEWS as readonly string[]).includes(v);

/** The view remembered on this browser; the default when none is kept or storage can't be read. */
export function storedView(): CalendarView {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (isView(saved)) return saved;
  } catch {
    // Storage can be blocked.
  }
  return DEFAULT_VIEW;
}

/** Remembers the view on this browser; when storage is blocked the pick lasts until the page is closed. */
export function rememberView(view: CalendarView): void {
  try {
    window.localStorage.setItem(KEY, view);
  } catch {
    // Storage can be blocked.
  }
}

const parts = (iso: string): [number, number, number] => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
};

/** The weekday of a day, Monday as 0 through Sunday as 6. */
export function weekdayIndex(iso: string): number {
  const [y, m, d] = parts(iso);
  return (new Date(y, m - 1, d).getDay() + 6) % 7;
}

/** The first day of the week a day is in, for a week that starts on `startsOn` (Monday as 0). */
export function startOfWeek(iso: string, startsOn: number): string {
  return addDays(iso, -((weekdayIndex(iso) - startsOn + 7) % 7));
}

/** The first day of the month a day is in. */
export function startOfMonth(iso: string): string {
  const [y, m] = parts(iso);
  return `${y}-${String(m).padStart(2, "0")}-01`;
}

/** The day `n` months from a day, the same day of the month or the month's last day when it has no such day. */
export function addMonths(iso: string, n: number): string {
  const [y, m, d] = parts(iso);
  const target = new Date(y, m - 1 + n, 1);
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
}

export interface Range {
  /** The first day to ask the server for, and how many days from it. */
  first: string;
  days: number;
  /** The days the view draws, in order: the week's working days for a work week, six weeks for a month. */
  shown: string[];
}

/** The days a view shows around the day the person is looking at. A work week whose week holds today on a day off (a weekend)
 * shows the whole week, so the view that opens by default has today in it and no day between is skipped. */
export function rangeOf(view: CalendarView, date: string, startsOn: number, workDays: readonly number[], today?: string): Range {
  // The timeline has its own answer, which says its days.
  if (view === "day" || view === "timeline") return { first: date, days: 1, shown: [date] };
  if (view === "month") {
    const first = startOfWeek(startOfMonth(date), startsOn);
    return { first, days: 42, shown: Array.from({ length: 42 }, (_, n) => addDays(first, n)) };
  }
  const first = startOfWeek(date, startsOn);
  const week = Array.from({ length: 7 }, (_, n) => addDays(first, n));
  const todayOff = today !== undefined && week.includes(today) && !workDays.includes(weekdayIndex(today));
  return { first, days: 7, shown: view === "week" || todayOff ? week : week.filter((d) => workDays.includes(weekdayIndex(d))) };
}

/** Where an arrow press `n` steps (negative: back) takes the day being looked at: a day, a week or a month, by the view. */
export function moveBy(view: CalendarView, date: string, n: number): string {
  return view === "day" ? addDays(date, n) : view === "month" ? addMonths(date, n) : addDays(date, 7 * n);
}

/** The minutes after midnight of a time written on the person's own clock ("...T09:30:00..."), or null when it has none. */
export function minutesOf(iso: string | null | undefined): number | null {
  const found = iso ? /T(\d{2}):(\d{2})/.exec(iso) : null;
  return found ? Number(found[1]) * 60 + Number(found[2]) : null;
}

/** The hour in a setting written as a time of day ("07:00"): rounded down for a start and up for an end. */
export function hourOf(setting: string, up = false): number {
  const [h, m] = setting.split(":").map(Number);
  return Math.min(24, Math.max(0, (h || 0) + (up && (m || 0) > 0 ? 1 : 0)));
}

/** An hour on the grid's edge in its short form: "10:00 AM" is "10 AM", so the label fits the gutter with room around it. */
export const hourLabel = (time: string): string => time.replace(/:00(?=\s|$)/, "");

/** How long, in minutes, an entry with no end is drawn: enough to read and press. */
export const SHORT = 30;

export interface Span {
  start: number;
  end: number;
}

/** The fewest hours the time grid shows. */
export const MIN_HOURS = 8;

/** The first and last hour the time grid shows: the working day (the configured hours), grown to the hour of the earliest entry's start
 * and the hour after the last entry's end (one range for every day of the view), the hour of `now` included when today is in view
 * (`now` is minutes after midnight, or null), and at least `MIN_HOURS`; what the minimum adds goes before the first hour, then after the last. */
export function gridHours(spans: readonly Span[], startsAt: string, endsAt: string, now: number | null = null): { from: number; to: number } {
  let from = Math.max(0, hourOf(startsAt));
  let to = Math.min(24, Math.max(from + 1, hourOf(endsAt, true)));
  if (spans.length > 0) {
    from = Math.min(from, Math.floor(Math.min(...spans.map((s) => s.start)) / 60));
    to = Math.max(to, Math.ceil(Math.max(...spans.map((s) => s.end)) / 60));
  }
  if (now !== null) {
    from = Math.min(from, Math.floor(now / 60));
    to = Math.max(to, Math.floor(now / 60) + 1);
  }
  from = Math.max(0, from);
  to = Math.min(24, to);
  const missing = Math.max(0, MIN_HOURS - (to - from));
  const before = Math.min(missing, from);
  from -= before;
  to = Math.min(24, to + (missing - before));
  return { from, to };
}

export interface Placed<T> extends Span {
  item: T;
  /** Which of `cols` side-by-side columns it takes. */
  col: number;
  cols: number;
}

/** Entries that overlap in time share the width of their day side by side. A run of entries that touch one another through
 * overlaps is one cluster; each entry takes the first column free of what it overlaps, and a cluster's columns are as many as
 * its widest overlap needs. */
export function placeOverlaps<T>(items: readonly { item: T; start: number; end: number }[]): Placed<T>[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.end - a.end);
  const placed: Placed<T>[] = [];
  let cluster: Placed<T>[] = [];
  let reach = -1;
  const close = () => {
    const cols = Math.max(1, ...cluster.map((p) => p.col + 1));
    for (const p of cluster) p.cols = cols;
    cluster = [];
  };
  for (const entry of sorted) {
    if (cluster.length && entry.start >= reach) close();
    const taken = new Set(cluster.filter((p) => p.end > entry.start).map((p) => p.col));
    let col = 0;
    while (taken.has(col)) col++;
    const one: Placed<T> = { ...entry, col, cols: 1 };
    cluster.push(one);
    placed.push(one);
    reach = Math.max(reach, entry.end);
  }
  close();
  return placed;
}

/** How two entries clash, as the engine says it (the same rules as Today's clash lines): they overlap, or they are in different
 * places with too little time between them. `minutes` is how long they overlap, or how many minutes short the travel time is;
 * `travel` is the travel time asked for between two places. */
export interface ClashLink {
  kind: "overlap" | "travel";
  minutes: number;
  travel: number;
}

export interface ClashGroup<T> extends Span {
  /** The entries that clash with one another, by when they begin. */
  items: T[];
  /** The longest overlap, in minutes, of two of them; zero when they clash only for want of travel time. */
  overlap: number;
  /** For a group that clashes only for want of travel time: the minutes asked for between the places; otherwise zero. */
  travel: number;
  /** For that group: how many minutes short of the travel time the gap between the meetings is; otherwise zero. */
  short: number;
}

/** The entries the engine says clash, each run of linked entries one group of two or more; an entry linked to none is in no group.
 * Whether two clash is `linked`'s answer, never the drawing's: an overlap on the screen is not a clash unless the engine named
 * it. The group spans from its first start to its last end. */
export function clashGroups<T>(items: readonly { item: T; start: number; end: number }[], linked: (a: T, b: T) => ClashLink | undefined): ClashGroup<T>[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.end - a.end);
  const parent = sorted.map((_, n) => n);
  const root = (n: number): number => (parent[n] === n ? n : (parent[n] = root(parent[n])));
  const links = new Map<number, ClashLink[]>();
  for (const [n, a] of sorted.entries())
    for (const [m, b] of sorted.entries()) {
      if (m <= n) continue;
      const link = linked(a.item, b.item) ?? linked(b.item, a.item);
      if (!link) continue;
      parent[root(m)] = root(n);
      links.set(n, [...(links.get(n) ?? []), link]);
    }
  const groups = new Map<number, { members: typeof sorted; links: ClashLink[] }>();
  for (const [n, entry] of sorted.entries()) {
    const group = groups.get(root(n)) ?? { members: [], links: [] };
    group.members.push(entry);
    group.links.push(...(links.get(n) ?? []));
    groups.set(root(n), group);
  }
  return [...groups.values()]
    .filter((g) => g.members.length > 1)
    .map((g) => {
      const overlaps = g.links.filter((l) => l.kind === "overlap");
      return {
        items: g.members.map((m) => m.item),
        start: g.members[0].start,
        end: Math.max(...g.members.map((m) => m.end)),
        overlap: Math.max(0, ...overlaps.map((l) => l.minutes)),
        travel: overlaps.length ? 0 : Math.max(0, ...g.links.map((l) => l.travel)),
        short: overlaps.length ? 0 : Math.max(0, ...g.links.map((l) => l.minutes)),
      };
    });
}

/** A clash group with the entries that share its stretch of the day without being linked to it by the engine. */
export interface DayClash<T> extends ClashGroup<T> {
  /** Entries that overlap the group's span (or another group's) but are no clash: laid out with the group, never drawn over it. */
  others: T[];
}

/** Settles which entries of a day must be laid out together. Each clash group is one block from its first start to its last end; any
 * entry whose time overlaps a block, and any block that overlaps another, is merged into one block, repeatedly, so that nothing on the
 * day is drawn over a clash and no two clash blocks cover each other. Returns the blocks (a group nothing overlaps is returned as it
 * is, with no `others`) and the entries that overlap no block, which the caller places as ordinary entries. Whether entries clash is
 * still only the engine's answer: a merged block's `others` are the entries that merely share its time. */
export function mergeClashSpans<T>(items: readonly { item: T; start: number; end: number }[], groups: readonly (ClashGroup<T> & { others?: readonly T[] })[]): { blocks: DayClash<T>[]; rest: T[] } {
  if (groups.length === 0) return { blocks: [], rest: items.map((i) => i.item) };
  const inGroup = new Set(groups.flatMap((g) => g.items));
  type Unit = { start: number; end: number; group?: ClashGroup<T> & { others?: readonly T[] }; item?: T };
  const units: Unit[] = [...groups.map((g) => ({ start: g.start, end: g.end, group: g })), ...items.filter((i) => !inGroup.has(i.item)).map((i) => ({ start: i.start, end: i.end, item: i.item }))];
  units.sort((a, b) => a.start - b.start || b.end - a.end);
  const clusters: Unit[][] = [];
  let reach = -1;
  for (const u of units) {
    if (clusters.length === 0 || u.start >= reach) clusters.push([u]);
    else clusters[clusters.length - 1].push(u);
    reach = Math.max(reach, u.end);
  }
  const blocks: DayClash<T>[] = [];
  const rest: T[] = [];
  const times = new Map(items.map((i) => [i.item, i]));
  for (const cluster of clusters) {
    const there = cluster.filter((u) => u.group).map((u) => u.group as ClashGroup<T> & { others?: readonly T[] });
    if (there.length === 0) {
      rest.push(...cluster.map((u) => u.item as T));
      continue;
    }
    const others = [...new Set([...cluster.filter((u) => !u.group).map((u) => u.item as T), ...there.flatMap((g) => g.others ?? [])])];
    if (cluster.length === 1) {
      blocks.push({ ...there[0], others: [...(there[0].others ?? [])] });
      continue;
    }
    const members = [...new Set([...there.flatMap((g) => g.items), ...others])].sort((a, b) => (times.get(a)?.start ?? 0) - (times.get(b)?.start ?? 0));
    const overlap = Math.max(...there.map((g) => g.overlap));
    blocks.push({
      items: members,
      others,
      start: Math.min(...cluster.map((u) => u.start)),
      end: Math.max(...cluster.map((u) => u.end)),
      overlap,
      travel: overlap > 0 ? 0 : Math.max(...there.map((g) => g.travel)),
      short: overlap > 0 ? 0 : Math.max(...there.map((g) => g.short)),
    });
  }
  return { blocks, rest };
}

/** The clashes the engine names, one for each group of pairs that share a meeting (`group` on each pair), earliest first: the one
 * count of clashes, whichever screen shows it. */
export function clashesOf<T extends { group: string }>(pairs: readonly T[]): T[] {
  const seen = new Set<string>();
  return pairs.filter((pair) => !seen.has(pair.group) && !!seen.add(pair.group));
}

type Say = (key: string, n: number, values?: Record<string, string | number>) => string;

/** The one phrase for clashes in a heading, on every screen that counts them: "1 clash: 4 meetings overlap", and with several "2 clashes:
 * 7 meetings overlap · the first on Wed" (`firstDay` is that day, short). A clash is one group of meetings that share time, counted once
 * whichever screen says it. `overlapping` is false when the meetings clash only for want of travel time between them. */
export function clashPhrase(tn: Say, clashes: number, meetings: number, overlapping = true, firstDay = ""): string {
  const key = overlapping ? "clash.phrase" : "clash.phrase_close";
  return tn(clashes === 1 || !firstDay ? key : `${key}_first`, clashes, { meetings: tn("schedule.meetings", meetings), day: firstDay });
}

/** One clash on its own line: "4 meetings overlap · Wed 4:11 PM", or for travel "Not enough time to get there · 30 min short". */
export function clashEach(t: (key: string, values?: Record<string, string | number>) => string, tn: Say, meetings: number, when: string, shortBy = 0): string {
  return shortBy > 0 ? t("clash.each_close", { n: shortBy }) : t("clash.each", { meetings: tn("schedule.meetings", meetings), when });
}

const ADDRESS = /([^\s@,]+)@([^\s@,]+\.[^\s@,]+)/;

export interface NamedCalendar {
  id: string;
  label: string;
  account?: string | null;
  /** The sides (top projects) the calendar serves, by id. */
  sides?: string[];
}

/** Whether a calendar's label is one the person gave it: a label that is an address, or says the account it reads, is the
 * connection's own and is not a name. */
const isGiven = (c: NamedCalendar): boolean => {
  const local = (c.account ?? "").split("@")[0].toLowerCase();
  const label = c.label.toLowerCase();
  return !label.includes("@") && !(local !== "" && label.includes(local));
};

/** A calendar's label with the account's address, and the part of it before the "@", left out: the Schedule never says an address (it is
 * on Connections). What is left is the connection's own wording ("Your calendar"), or nothing. */
export function withoutAddress(label: string, account?: string | null): string {
  const local = (account ?? "").split("@")[0].toLowerCase();
  let out = label.replace(new RegExp(ADDRESS.source, "g"), "");
  if (local) out = out.replace(new RegExp(local.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), "");
  return out.replace(/\s+/g, " ").replace(/^[\s,·:\-–]+|[\s,·:\-–]+$/g, "").trim();
}

/** What each calendar is called on the page, by id, never by an address. A name the person gave is kept. Otherwise a calendar linked to
 * one side is called that side ("Personal", or the project's name), and one with no side keeps its label without the account's address
 * or the start of it. Two calendars that would read the same are told apart by a number after the first (`numbered`); `fallback` names
 * one whose label was only an address. */
export function calendarNames(
  calendars: readonly NamedCalendar[],
  sideName: (side: string) => string | undefined,
  words: { numbered: (name: string, n: number) => string; fallback: string },
): Map<string, string> {
  const side = (c: NamedCalendar) => (c.sides?.length === 1 ? c.sides[0] : null);
  const base = calendars.map((c) => {
    const s = side(c);
    const word = s ? sideName(s) : undefined;
    if (isGiven(c)) return withoutAddress(c.label, c.account) || words.fallback;
    return word ?? (withoutAddress(c.label, c.account) || words.fallback);
  });
  const seen = new Map<string, number>();
  const names = new Map<string, string>();
  calendars.forEach((c, n) => {
    const count = (seen.get(base[n]) ?? 0) + 1;
    seen.set(base[n], count);
    names.set(c.id, count === 1 ? base[n] : words.numbered(base[n], count));
  });
  return names;
}

/** Entries that are the same thing said more than once (the key says what "the same" is) folded into one with how many there
 * were, in the order of each one's first appearance. */
export function foldIdentical<T>(items: readonly T[], keyOf: (item: T) => string): { item: T; count: number }[] {
  const folded = new Map<string, { item: T; count: number }>();
  for (const item of items) {
    const key = keyOf(item);
    const found = folded.get(key);
    if (found) found.count += 1;
    else folded.set(key, { item, count: 1 });
  }
  return [...folded.values()];
}

/** The longest side name a key chip shows whole; a longer one is cut here and its whole name is on hover and in its accessible name. */
export const KEY_CHIP_NAME = 16;

/** How many of the key's chips fit one line: the widths (px) of the chips in order, the gap between them, the room the line has and the
 * width of the "+N more" button that stands in for the rest. All of them when they all fit (with no button); otherwise as many as leave
 * room for the button; never fewer than none. */
export function chipsThatFit(widths: readonly number[], gap: number, room: number, moreWidth: number): number {
  const all = widths.reduce((sum, w, i) => sum + w + (i > 0 ? gap : 0), 0);
  if (all <= room) return widths.length;
  let used = moreWidth;
  let fit = 0;
  for (const w of widths) {
    used += w + gap;
    if (used > room) break;
    fit += 1;
  }
  return fit;
}
