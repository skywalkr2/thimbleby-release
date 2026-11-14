// The time grid of the Day, Work week and Week views (design 7.7): an hour column, a heading for each day, an all-day strip on
// top for what has no time (all-day events, due dates, dated deliveries) and each day's timed entries placed by start and end,
// overlapping ones side by side. The hours are the configured ones, grown to hold an entry outside them. A line marks now on
// today's column. Today is named in words in its heading, never only by color.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { S } from "../lib/api";
import { clashGroups, foldIdentical, gridHours, hourLabel, mergeClashSpans, minutesOf, placeOverlaps, SHORT, type ClashGroup, type Span } from "../lib/calendar";
import { day, onTheClock, wallTime, weekdayDay, weekdayLong } from "../lib/dates";
import { useIsNarrow } from "../lib/media";
import { useWords } from "../lib/wording";
import { Icon } from "../ui/Icon";
import { EntryButton, entryKey, type Calendars, type Entry } from "./ScheduleEntry";
import { AllDayStrip } from "./ScheduleAllDay";
import { GroupCard, type GroupRef } from "./ScheduleGroupCard";
import styles from "./Schedule.module.css";

export interface DayEntries {
  date: string;
  all_day: Entry[];
  timed: Entry[];
  /** The pairs of entries the engine says clash on this day (the same rules as Today's clash lines); empty when none. */
  clashes: S["ScheduleClashView"][];
}

/** Where a timed entry sits on its day, in minutes after midnight. One with no end is drawn short, unless it goes on past
 * midnight, when it runs to the end of the day; one that came in from the day before starts at its top. */
function spanOf(entry: Entry, date: string, nextStart = Infinity): Span {
  const start = entry.begins ? (minutesOf(entry.begins) ?? 0) : 0;
  const named = minutesOf(entry.ends);
  const end = named ?? (entry.begins && !continuesPast(entry, date) ? start + SHORT : 24 * 60);
  // A meeting shorter than the least drawn length is drawn that long, but never into the entry that starts where it ends.
  const floor = Math.min(start + SHORT, Math.max(nextStart, start + 1));
  return { start, end: Math.min(24 * 60, Math.max(end, floor)) };
}

function continuesPast(entry: Entry, date: string): boolean {
  return !!entry.end && entry.end.slice(0, 10) > date;
}

const clashId = (e: { snapshot: string; start: string }): string => `${e.snapshot}#${e.start}`;

/** The clash cards of a day: the entries the engine paired, each run of them one card. An overlap the engine did not name (an
 * all-day entry, one the person is not attending, a pair marked fine) is two ordinary entries. */
export function clashCards(day: DayEntries, spans: { item: Entry; start: number; end: number }[]): ClashGroup<Entry>[] {
  const pairs = new Map(day.clashes.map((c) => [`${clashId(c.first)}|${clashId(c.second)}`, { kind: c.kind, minutes: c.minutes, travel: c.travel_minutes }]));
  return clashGroups(spans, (a, b) => pairs.get(`${clashId(a)}|${clashId(b)}`));
}

/** The words at the head of a clash card: how long the meetings overlap, or that the places are too far apart for the time between. */
export function clashHeading(group: ClashGroup<Entry>, t: (key: string, values?: Record<string, string | number>) => string): string {
  if (group.overlap > 0) return t(group.items.length > 2 ? "schedule.clash.overlap_many" : "schedule.clash.overlap", { n: group.overlap, count: group.items.length });
  return group.travel > 0 ? t("schedule.clash.travel", { n: group.travel }) : t("schedule.clash.head");
}

/** The heading of a clash card with no room for the whole one: the word and the least that says what is wrong, in one line. */
export function clashBrief(group: ClashGroup<Entry>, t: (key: string, values?: Record<string, string | number>) => string): string {
  if (group.overlap > 0) return t(group.items.length > 2 ? "schedule.clash.brief_many" : "schedule.clash.brief_overlap", { n: group.overlap, count: group.items.length });
  return group.travel > 0 && group.short > 0 ? t("schedule.clash.brief_short", { n: group.short }) : t("schedule.clash.head");
}

/** The reason on a clash card, in a few words: how long the meetings overlap, or how short of the travel time the gap between them is. */
export function clashReason(group: ClashGroup<Entry>, t: (key: string, values?: Record<string, string | number>) => string): string {
  if (group.overlap > 0) return clashHeading(group, t);
  if (group.travel > 0 && group.short > 0) return t("schedule.clash.short", { n: group.short });
  return clashHeading(group, t);
}

/** A clock time written as the person's clock writes it ("4:11 PM"), from minutes after midnight. */
export function clockWords(m: number): string {
  return wallTime(`2000-01-01T${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
}

type Words = (key: string, values?: Record<string, string | number>) => string;

/** The accessible name of a clash, on every width: it always starts with the word and says how many meetings and when, "Clash: 4 meetings
 * overlap, 4:11 PM to 6:00 PM" (or "Clash: not enough time to get there, ..." for places too far apart for the time between). */
export function clashName(group: { items: unknown[]; start: number; end: number; overlap: number }, t: Words, tn: (key: string, n: number) => string): string {
  return t("schedule.clash.label_reason", {
    reason: group.overlap > 0 ? t("schedule.clash.label_overlap", { meetings: tn("schedule.meetings", group.items.length) }) : t("schedule.clash.label_travel"),
    start: clockWords(group.start),
    end: clockWords(group.end),
  });
}

/** The least width, in px, each lane of a clash needs for its meetings to stand side by side at their own times; with less, a clash is
 * one card that names each meeting on a line of its own. This is the reviewer's answer on clashes, and the only place the number is. */
export const SIDE_BY_SIDE_LANE = 85;

/** Whether a day's column has room to draw a clash's meetings side by side: each of its `lanes` gets at least `SIDE_BY_SIDE_LANE`, and the
 * window is not the phone layout, where a clash is always the one card (the reviewer's answer on clashes). */
export function roomForSideBySide(column: number, lanes: number, phone = false): boolean {
  return !phone && column / Math.max(1, lanes) >= SIDE_BY_SIDE_LANE;
}

/** An entry shorter than this, in minutes, has its second line run on after the title. */
const SHORT_BLOCK = 45;
/** The same for a lane of a side-by-side clash, whose title may take two lines: under an hour, its time runs on after the title. */
const LANE_SHORT_BLOCK = 60;
const ALL_HOURS_KEY = "cockpit:schedule-all-hours";
const storedAllHours = (): boolean => {
  try {
    return window.localStorage.getItem(ALL_HOURS_KEY) === "1";
  } catch {
    return false;
  }
};
/** The most a box may ask to be taller than its time, in minutes, so a very narrow column never makes one fill the day. */
const MAX_GROWTH = 180;
/** The hour column's width in px. */
const HOURS_WIDTH = 64;

export function TimeGrid(props: {
  days: DayEntries[];
  today: string;
  startsAt: string;
  endsAt: string;
  now: Date;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
  /** A group card's "+N more" was pressed: the screen opens the group in its side pane. */
  onOpenGroup: (group: GroupRef) => void;
  /** What stands at the left of the line above the grid, where "Show all hours" is at the right: the key to the sides' colors. */
  lead?: ReactNode;
}) {
  const { t, tn } = useWords();
  const phone = useIsNarrow();
  // How much room, in minutes from its start, each meeting's box has had to take to show its title and its time whole (by entry), and how
  // much a clash card has had to take to name every meeting whole (by day and start). A box taller than its span is laid out as long as
  // it is drawn: whatever its box reaches is laid out with it, so nothing is drawn under it.
  const [needs, setNeeds] = useState<Record<string, number>>({});
  const [grown, setGrown] = useState<Record<string, number>>({});
  // The clashes (by day and start) whose lanes were drawn and found unreadable: a lane that cannot show its start time whole and the first
  // whole word of its title is not drawn; the clash is the one card instead.
  const [unreadable, setUnreadable] = useState<Record<string, true>>({});
  // The width of a day's column, as last measured.
  const [column, setColumn] = useState(Infinity);
  // Meetings that overlap are one clash card naming them all; the rest share their day's width side by side.
  const perDay = props.days.map((d) => {
    // A meeting of a clash keeps its own time (the clash is one block, and a card takes its room by `grown`), so what it was once measured
    // to need never reaches the entry that starts where the clash ends.
    const spans = d.timed.map((e) => {
      const span = spanOf(e, d.date);
      const need = needs[entryKey(e, d.date)] ?? 0;
      return { item: e, start: span.start, end: Math.min(24 * 60, Math.max(span.end, span.start + need)) };
    });
    // Every entry that shares time with a clash is laid out with it (one block), so nothing is drawn over a clash; the rest are ordinary.
    const settled = mergeClashSpans(spans, clashCards(d, spans));
    // A meeting only drawn longer than its own end (the least drawn length) does not reach the entry that starts where the clash really
    // ends: that entry is its own, and the clash (card or lanes) stops at it.
    const starts = d.timed.map((e) => spanOf(e, d.date).start);
    const trimmed: Entry[] = [];
    const blocks = settled.blocks.map((b) => {
      const times = new Map(spans.map((x) => [x.item, x]));
      const real = Math.max(...b.items.filter((e) => !b.others.includes(e)).map((e) => {
        const first = spanOf(e, d.date);
        const next = Math.min(Infinity, ...starts.filter((st) => st > first.start && st >= (minutesOf(e.ends) ?? first.end)));
        return spanOf(e, d.date, next).end;
      }));
      const out = b.others.filter((e) => (times.get(e)?.start ?? 0) >= real);
      if (out.length === 0) return b;
      trimmed.push(...out);
      const items = b.items.filter((e) => !out.includes(e));
      return { ...b, items, others: b.others.filter((e) => !out.includes(e)), end: Math.max(real, ...items.map((e) => (b.others.includes(e) ? (times.get(e)?.end ?? 0) : 0))) };
    });
    const ordinary = new Set([...settled.rest, ...trimmed]);
    return { spans, placed: placeOverlaps(spans.filter((s) => ordinary.has(s.item))), clashes: blocks };
  });
  const nowMinutes = onTheClock(props.now).minutes;
  // The hours come from the meetings that stand (a called-off one does not stretch them), one range for every day of the view.
  const shownHours = gridHours(
    perDay.flatMap((d) => d.spans.filter((s) => !s.item.cancelled).map((s) => ({ start: s.start, end: s.end }))),
    props.startsAt,
    props.endsAt,
    props.days.some((d) => d.date === props.today) ? nowMinutes : null,
  );
  // The whole day, midnight to midnight, when the person asks for it (and it is remembered for them); else the hours worked out above.
  const [allHours, setAllHours] = useState(storedAllHours);
  const pickAllHours = (on: boolean) => {
    setAllHours(on);
    try {
      window.localStorage.setItem(ALL_HOURS_KEY, on ? "1" : "0");
    } catch {
      // A browser that keeps nothing forgets the choice; the grid still follows it for now.
    }
  };
  const { from, to } = allHours ? { from: 0, to: 24 } : shownHours;
  // A clash card that needs more height than its span takes the free room below it, up to the next entry or the end of the grid, and
  // pushes nothing: what still does not fit is counted in the card's "+N more".
  const cardEnd = (i: number, c: { start: number; end: number }) => {
    const want = Math.max(c.end, c.start + (grown[`${props.days[i].date}:${c.start}`] ?? 0));
    const next = Math.min(to * 60, ...perDay[i].clashes.filter((o) => o.start >= c.end && o.start !== c.start).map((o) => o.start), ...perDay[i].placed.filter((p) => p.start >= c.end).map((p) => p.start));
    return Math.max(c.end, Math.min(want, next));
  };
  const canShowAll = allHours || shownHours.to - shownHours.from < 24;
  const hours = Array.from({ length: to - from }, (_, n) => from + n);
  // What the days hold, so the frame is placed again when the entries of a newly picked range arrive after its empty days.
  const shape = `${allHours ? "all" : ""}${perDay.map((d) => `${d.placed.length}.${d.clashes.length}`).join()}`;
  const gridRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  // The day headings stay on top and the all-day row under them, so the row sticks at the headings' height, whatever it is.
  useLayoutEffect(() => {
    const grid = gridRef.current;
    const head = grid?.querySelector<HTMLElement>("h3");
    if (!grid || !head) return;
    const set = () => grid.style.setProperty("--head-h", `${head.getBoundingClientRect().height}px`);
    set();
    const watch = typeof ResizeObserver === "function" ? new ResizeObserver(set) : null;
    watch?.observe(head);
    return () => watch?.disconnect();
  }, [props.days.length]);
  // The meetings the frame hides above and below what shows, counted so a cut grid says so, and a press goes to them.
  // Where a day's column has room (`SIDE_BY_SIDE_LANE` a lane), a clash is drawn as its meetings at their own times; narrower,
  // it is one card from the first start to the last end that names them all.
  useLayoutEffect(() => {
    const box = scrollerRef.current;
    if (!box) return;
    const measure = () => setColumn((box.clientWidth - HOURS_WIDTH) / Math.max(1, props.days.length));
    measure();
    const watch = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    watch?.observe(box);
    return () => watch?.disconnect();
  }, [props.days.length]);
  // What was measured is forgotten when the width or the days change, so a box is never left taller than its title and time need.
  const drawing = `${column}|${phone}|${props.days.map((d) => d.date + d.timed.length).join()}`;
  const [measuredFor, setMeasuredFor] = useState(drawing);
  if (measuredFor !== drawing) {
    setMeasuredFor(drawing);
    setGrown({});
    setNeeds({});
    setUnreadable({});
  }
  // A box whose title and time don't fit whole in its height asks for the room, and a clash card that needs more height than its span
  // asks for it too (it takes only what is free below it, see `cardEnd`; the rest is in its "+N more").
  useLayoutEffect(() => {
    const box = scrollerRef.current;
    if (!box) return;
    const rowPx = box.querySelector<HTMLElement>("ul[data-day]")?.getBoundingClientRect().height ?? 0;
    const hourPx = rowPx / Math.max(1, to - from);
    if (hourPx <= 0) return;
    const minutes = (px: number) => Math.min(MAX_GROWTH, Math.ceil((px / hourPx) * 60));
    const nextNeeds: Record<string, number> = {};
    for (const b of box.querySelectorAll<HTMLElement>("ul[data-day] button[data-entry-key]")) {
      // A lane of a clash gives up its place and a title line before it asks for more room; a card has its own rule.
      if (b.closest("[data-group-card]") || b.closest("li[data-clash]")) continue;
      const slot = b.closest("li");
      const extra = b.scrollHeight - b.clientHeight;
      if (slot && extra > 1) nextNeeds[b.dataset.entryKey ?? ""] = minutes(slot.getBoundingClientRect().height + extra);
    }
    const nextGrown: Record<string, number> = {};
    for (const li of box.querySelectorAll<HTMLElement>("ul[data-day] > li[data-clash]:not([data-side])")) {
      const need = Number(li.querySelector<HTMLElement>("[data-group-card]")?.dataset.need ?? 0);
      if (need > li.getBoundingClientRect().height + 1) nextGrown[`${li.closest<HTMLElement>("ul[data-day]")?.dataset.day}:${li.dataset.clash}`] = minutes(need);
    }
    const lost: Record<string, true> = {};
    for (const li of box.querySelectorAll<HTMLElement>("ul[data-day] > li[data-clash][data-side]")) {
      const readable = Array.from(li.querySelectorAll<HTMLElement>("li[class*='clashMember']")).every((lane) => {
        const at = lane.getBoundingClientRect();
        const time = lane.querySelector<HTMLElement>("[data-entry-time]");
        if (time && (time.scrollWidth > time.clientWidth + 1 || time.getBoundingClientRect().right > at.right + 1)) return false;
        // Whole in height too: the first lane's "Clash" line takes a row of its own above the title, and a lane too short for it, the title
        // and the time is not drawn (the clash is the one card).
        // A short lane whose title and time have to run onto two lines (a narrow lane, 30 minutes tall) is cut the same way.
        if (lane.hasAttribute("data-first") && time && time.getBoundingClientRect().bottom > at.bottom + 1) return false;
        const button = lane.querySelector<HTMLElement>("button[data-entry-key]");
        if (button && (lane.hasAttribute("data-first") || button.hasAttribute("data-short")) && button.scrollHeight > button.clientHeight + 1) return false;
        const name = lane.querySelector<HTMLElement>("[class*='name']");
        const node = name?.firstChild;
        if (!name || !node || node.nodeType !== Node.TEXT_NODE) return true;
        const word = /^\S+/.exec(node.textContent ?? "")?.[0] ?? "";
        const range = document.createRange();
        range.setStart(node, 0);
        range.setEnd(node, word.length);
        // A browser that cannot measure a range (a test's) has nothing to judge by, so the lane stands.
        if (typeof range.getBoundingClientRect !== "function") return true;
        const first = range.getBoundingClientRect().right;
        return first <= name.getBoundingClientRect().right + 1 && first <= at.right + 1;
      });
      if (!readable) lost[`${li.closest<HTMLElement>("ul[data-day]")?.dataset.day}:${li.dataset.clash}`] = true;
    }
    if (Object.keys(lost).some((k) => !unreadable[k])) setUnreadable((was) => ({ ...was, ...lost }));
    const raise = (was: Record<string, number>, next: Record<string, number>) => {
      const keys = Object.keys(next).filter((k) => next[k] > (was[k] ?? 0));
      return keys.length === 0 ? was : { ...was, ...Object.fromEntries(keys.map((k) => [k, next[k]])) };
    };
    setNeeds((was) => raise(was, nextNeeds));
    setGrown((was) => raise(was, nextGrown));
  }, [drawing, needs, grown, unreadable, from, to, shape]);
  // A lane shows whole lines only: its place (the line under the time) is two lines where they fit, one where only one fits, and left out where
  // not even one does, never a line cut across by the lane's bottom edge. The whole text is on hover and on focus.
  useLayoutEffect(() => {
    const box = scrollerRef.current;
    if (!box) return;
    for (const b of box.querySelectorAll<HTMLElement>("li[class*='clashMember'] button[data-entry-key]:not([data-short])")) {
      b.removeAttribute("data-place-one");
      b.removeAttribute("data-place-hidden");
      const line = b.querySelector<HTMLElement>("[data-entry-line]");
      const place = b.querySelector<HTMLElement>("[class*='linePlace']");
      if (!line || !place) continue;
      const cut = () => place.getBoundingClientRect().bottom > line.getBoundingClientRect().bottom + 0.5;
      if (!cut()) continue;
      b.setAttribute("data-place-one", "");
      if (cut()) b.setAttribute("data-place-hidden", "");
    }
  }, [drawing, needs, grown, unreadable, from, to, shape]);
  // Entries that overlap without clashing share their day's width; where that leaves each too narrow to read its title, the run of them is
  // one card that lists every title in full with its own start.
  const layout = perDay.map((d) => {
    const sorted = d.placed.filter((p) => !(p.item.cancelled && (p.end <= from * 60 || p.start >= to * 60))).sort((a, b) => a.start - b.start || b.end - a.end);
    const runs: (typeof sorted)[] = [];
    let reach = -1;
    for (const p of sorted) {
      if (runs.length === 0 || p.start >= reach) runs.push([p]);
      else runs[runs.length - 1].push(p);
      reach = Math.max(reach, p.end);
    }
    const singles: typeof sorted = [];
    const cards: { items: Entry[]; start: number; end: number }[] = [];
    for (const run of runs) {
      const cols = Math.max(...run.map((p) => p.cols));
      if (cols > 1 && !roomForSideBySide(column, cols, phone)) cards.push({ items: run.map((p) => p.item), start: run[0].start, end: Math.max(...run.map((p) => p.end)) });
      else singles.push(...run);
    }
    return { singles, cards };
  });
  // Identical all-day entries of a day are one with a count; with none on any day the strip takes no room.
  const strips = props.days.map((d) => foldIdentical(d.all_day, (e) => [e.kind, e.title, e.own, e.cancelled].join("|")));
  const anyAllDay = strips.some((s) => s.length > 0);
  // The grid's hours and days, as the last drawing had them, for the count of meetings out of the frame.
  const geometry = useRef({ from, to, days: props.days });
  geometry.current = { from, to, days: props.days };
  const [cut, setCut] = useState({ above: 0, below: 0 });
  useEffect(() => {
    const box = scrollerRef.current;
    if (!box) return;
    const count = () => {
      const view = box.getBoundingClientRect();
      const head = box.querySelector<HTMLElement>("[data-grid] h3")?.getBoundingClientRect().height ?? 0;
      const strip = box.querySelector<HTMLElement>("[data-strip]")?.getBoundingClientRect().height ?? 0;
      // Each meeting counts once, by its own start and end: below when it starts at or under the frame's bottom edge, above when it ends at or
      // over the line under the headings and the strip. One partly in view counts as neither. A meeting in a group card counts by its own time,
      // whether the card draws its row or counts it in its "+N more".
      const lane = box.querySelector<HTMLElement>("ul[data-day]");
      const rows = Math.max(1, geometry.current.to - geometry.current.from);
      let above = 0;
      let below = 0;
      if (lane) {
        const laneBox = lane.getBoundingClientRect();
        const minuteAt = (y: number) => geometry.current.from * 60 + ((y - laneBox.top) / (laneBox.height / rows)) * 60;
        const top = minuteAt(view.top + head + strip);
        const bottom = minuteAt(view.bottom);
        const seen = new Set<string>();
        for (const d of geometry.current.days)
          for (const e of d.timed) {
            const key = entryKey(e, d.date);
            if (seen.has(key)) continue;
            seen.add(key);
            const span = spanOf(e, d.date);
            if (span.start >= bottom - 2) below += 1;
            else if (span.end <= top + 2) above += 1;
          }
      }
      setCut((was) => (was.above === above && was.below === below ? was : { above, below }));
    };
    count();
    box.addEventListener("scroll", count, { passive: true });
    const watch = typeof ResizeObserver === "function" ? new ResizeObserver(count) : null;
    watch?.observe(box);
    return () => {
      box.removeEventListener("scroll", count);
      watch?.disconnect();
    };
  }, [shape, props.days.length, anyAllDay]);
  const scrollBy = (sign: 1 | -1) => scrollerRef.current?.scrollBy({ top: sign * (scrollerRef.current.clientHeight * 0.7), behavior: "smooth" });
  const clockOf = (m: number) => wallTime(`2000-01-01T${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
  const clockWhole = (m: number) => clockOf(m).replace(/ /g, "\u00a0");
  // The words at the head of a clash card: how many meetings and when, or that the places are too far apart.
  // The time never breaks inside itself ("12:35 AM" stays whole), so a narrow column wraps before it, not in it.
  const clashLabel = (c: { items: Entry[]; start: number; end: number; overlap: number }) => clashName(c, t, tn);
  const clashText = (c: { items: Entry[]; start: number; travel: number }) =>
    c.items.length > 2
      ? t("schedule.clash.many", { n: c.items.length, time: wallTime(`2000-01-01T${String(Math.floor(c.start / 60)).padStart(2, "0")}:${String(c.start % 60).padStart(2, "0")}`).replace(/ /g, "\u00a0") })
      : c.travel > 0
        ? t("schedule.clash.travel", { n: c.travel })
        : t("schedule.clash.head");
  // A single day's date is the page's heading already, so its column says only which day it is.
  const single = props.days.length === 1;
  // A work week with today added on a day off has six columns: its headings take the short form to stay on one line.
  const said = props.days.length === 6 ? weekdayDay : day;
  const label = (date: string) =>
    single ? (date === props.today ? t("today.agenda.today") : weekdayLong(date)) : date === props.today ? t("schedule.day_today", { date: said(date) }) : t("schedule.day_plain", { date: said(date) });
    // The grid opens scrolled to what matters: the first clash, else now, else the first entry, else the start of the hours shown
  // (never on empty early hours). Once for each time it is drawn from nothing (a view or a day picked).
  useEffect(() => {
    const box = scrollerRef.current;
    if (!box) return;
    const target = box.querySelector<HTMLElement>("[data-clash]") ?? box.querySelector<HTMLElement>("[data-now]") ?? box.querySelector<HTMLElement>("ul[data-day] > li");
    if (!target) return;
    const head = box.querySelector<HTMLElement>("[data-grid] h3")?.getBoundingClientRect().height ?? 0;
    const strip = box.querySelector<HTMLElement>("[data-strip]")?.getBoundingClientRect().height ?? 0;
    const above = target.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    // Within the first hour of the top the grid stays at its top, so the first hour's label is not left half under the headings.
    let wanted = above - head - strip - 2 * 16;
    // The grid opens on the earliest entry of any day when the clash or now is still in the frame from there, so nothing early in the
    // week is scrolled out of sight for no reason.
    const firsts = Array.from(box.querySelectorAll<HTMLElement>("ul[data-day] > li:not([data-now])")).map((el) => el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop);
    const first = firsts.length > 0 ? Math.max(0, Math.min(...firsts) - head - strip - 2 * 16) : null;
    const hourPx = (box.querySelector<HTMLElement>("ul[data-day]")?.getBoundingClientRect().height ?? 0) / Math.max(1, to - from);
    // "Still in the frame" is the target's first hour: its heading and first rows show, and the rest is a scroll away.
    // The frame never opens past the day's first entry, so nothing is out of sight above it: a clash or now further down is a scroll away, said by the cue below.
    if (first !== null && first < wanted) wanted = first;
    // What already shows without scrolling stays where it is: scrolling a little would only slide the first hour under the headings.
    // The same when the whole grid is only a little taller than its frame (two hours or less): the frame stays at its top.
    const fits = above + target.getBoundingClientRect().height <= box.clientHeight || box.scrollHeight - box.clientHeight <= 2 * hourPx;
    box.scrollTop = fits || wanted < box.clientHeight / 8 ? 0 : wanted;
    // No entry is left cut across the frame's top edge under the headings: scroll up to its top, so its title shows (the ones above it are counted by the cue).
    for (let n = 0; n < 3 && box.scrollTop > 0; n++) {
      const boxTop = box.getBoundingClientRect().top;
      const visible = boxTop + head + strip;
      let at: number | null = null;
      for (const el of box.querySelectorAll<HTMLElement>("ul[data-day] [data-entry-key]")) {
        const r = el.getBoundingClientRect();
        if (r.top < visible - 1 && r.bottom > visible + 1) at = Math.min(at ?? Infinity, r.top - boxTop + box.scrollTop);
      }
      if (at === null) break;
      box.scrollTop = Math.max(0, at - head - strip - 8);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.days[0]?.date, props.days.length, shape, anyAllDay]);
  return (
    <>
    {(canShowAll || props.lead) && (
      <div className={styles.hoursSwitch} data-hours-switch="">
        <div className={styles.hoursLead}>{props.lead}</div>
        {canShowAll && (
          <button type="button" className={styles.hoursButton} data-all-hours="" aria-pressed={allHours} onClick={() => pickAllHours(!allHours)}>
            {t(allHours ? "schedule.hours.fewer" : "schedule.hours.all")}
          </button>
        )}
      </div>
    )}
    {cut.above > 0 && (
      <div className={styles.cueAbove}>
        <button type="button" className={styles.cue} data-more="above" onClick={() => scrollBy(-1)}>
          {tn("schedule.more_above", cut.above)}
        </button>
      </div>
    )}
    <div ref={scrollerRef} className={styles.scroller} tabIndex={0} role="region" aria-label={t("schedule.grid.region")} data-scroller="">
    <div ref={gridRef} className={styles.grid} style={{ ["--cols" as string]: props.days.length, ["--rows" as string]: to - from }} data-grid="" data-few={props.days.length <= 6 ? "" : undefined}>
      <div aria-hidden="true" className={styles.corner} />
      {props.days.map((d) => (
        <h3 key={d.date} className={styles.colHead} data-today={d.date === props.today ? "" : undefined}>
          {label(d.date)}
        </h3>
      ))}
      {anyAllDay && <div className={styles.stripLabel}>{t("schedule.all_day")}</div>}
      {anyAllDay &&
        props.days.map((d, i) => (
          <AllDayStrip key={d.date} date={d.date} label={`${t("schedule.all_day")}, ${label(d.date)}`} today={d.date === props.today} items={strips[i]} calendars={props.calendars} selected={props.selected} onOpen={props.onOpen} onMore={props.onOpenGroup} />
        ))}
      <div className={styles.hours} aria-hidden="true">
        {hours.map((h) => (
          <span key={h} className={styles.hour} data-hour="" data-first={h === from ? "" : undefined} style={{ top: `calc(${h - from} * var(--hour))` }}>
            {hourLabel(wallTime(`2000-01-01T${String(h).padStart(2, "0")}:00`))}
          </span>
        ))}
      </div>
      {props.days.map((d, i) => (
        <ul key={d.date} className={styles.lane} aria-label={label(d.date)} data-day={d.date} data-today={d.date === props.today ? "" : undefined}>
          {layout[i].singles.map((p, n) => (
            <li
              key={`${entryKey(p.item, d.date)}:${n}`}
              className={styles.slot}
              style={{
                top: `calc(${(p.start - from * 60) / 60} * var(--hour))`,
                height: `calc(${(p.end - p.start) / 60} * var(--hour))`,
                left: `${(p.col / p.cols) * 100}%`,
                width: `${100 / p.cols}%`,
              }}
            >
              <EntryButton entry={p.item} date={d.date} calendars={props.calendars} time={false} block short={p.end - p.start < SHORT_BLOCK} selected={props.selected === entryKey(p.item, d.date)} onOpen={props.onOpen} t={t} />
            </li>
          ))}
          {layout[i].cards.map((c, n) => (
            <li key={`overlap:${c.start}:${n}`} className={styles.slot} style={{ top: `calc(${(c.start - from * 60) / 60} * var(--hour))`, height: `calc(${(c.end - c.start) / 60} * var(--hour))`, left: 0, width: "100%" }} data-overlap="">
              <GroupCard
                tone="overlap"
                label={t("schedule.overlap.label", { names: c.items.map((e) => e.title).join(", ") })}
                head={<span className={styles.clashText}>{t("schedule.overlap.head", { n: c.items.length, time: clockWhole(c.start) })}</span>}
                items={c.items}
                time={clockOf(c.start)}
                startKey={String(c.start)}
                date={d.date}
                calendars={props.calendars}
                selected={props.selected}
                onOpen={props.onOpen}
                onMore={props.onOpenGroup}
              />
            </li>
          ))}
          {perDay[i].clashes.map((c, n) => {
            const timed = new Map(perDay[i].spans.map((x) => [x.item, x]));
            const members = placeOverlaps(c.items.map((e) => ({ item: e, start: timed.get(e)?.start ?? 0, end: Math.min(timed.get(e)?.end ?? 0, c.end) })));
            // Meetings that overlap stand side by side where the day's column has room; ones that clash only for want of travel time are the card that says so.
            const widest = Math.max(1, ...members.map((m) => m.cols));
            const side = widest > 1 && roomForSideBySide(column, widest, phone) && !unreadable[`${d.date}:${c.start}`];
            const end = side ? c.end : cardEnd(i, c);
            // The first lane (the earliest start, then the leftmost) carries the word "Clash" with its icon.
            const first = members.reduce((best, m, k) => (m.start < members[best].start || (m.start === members[best].start && m.col < members[best].col) ? k : best), 0);
            return (
              <li
                key={`clash:${c.start}:${n}`}
                className={styles.slot}
                style={{
                  top: `calc(${(c.start - from * 60) / 60} * var(--hour))`,
                  left: 0,
                  width: "100%",
                  height: `calc(${(end - c.start) / 60} * var(--hour))`,
                }}
                data-clash={String(c.start)}
                data-side={side ? "" : undefined}
              >
                {side ? (
                  <ul className={styles.clashSide} role="group" aria-label={clashLabel(c)}>
                    {members.map((m, k) => (
                      <li
                        key={`${entryKey(m.item, d.date)}:${k}`}
                        className={styles.clashMember}
                        data-plain={c.others.includes(m.item) ? "" : undefined}
                        data-first={k === first ? "" : undefined}
                        style={{
                          top: `${((m.start - c.start) / (c.end - c.start)) * 100}%`,
                          height: `${((m.end - m.start) / (c.end - c.start)) * 100}%`,
                          left: `${(m.col / m.cols) * 100}%`,
                          width: `calc(${100 / m.cols}% - 2px)`,
                        }}
                      >
                        <EntryButton entry={m.item} date={d.date} calendars={props.calendars} time={false} block lane tag={k === first} short={m.end - m.start < LANE_SHORT_BLOCK} selected={props.selected === entryKey(m.item, d.date)} onOpen={props.onOpen} t={t} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <GroupCard
                    tone="clash"
                    label={clashLabel(c)}
                    head={
                      <>
                        <Icon name="alert" size={16} />
                        <span className={styles.clashText}>{clashReason(c, t)}</span>
                      </>
                    }
                    brief={
                      <>
                        <Icon name="alert" size={16} />
                        <span className={styles.clashText}>{clashBrief(c, t)}</span>
                      </>
                    }
                    headTitle={clashText(c)}
                    items={c.items}
                    time={clockOf(c.start)}
                    startKey={String(c.start)}
                    date={d.date}
                    calendars={props.calendars}
                    selected={props.selected}
                    onOpen={props.onOpen}
                    onMore={props.onOpenGroup}
                  />
                )}
              </li>
            );
          })}
          {d.date === props.today && nowMinutes >= from * 60 && nowMinutes <= to * 60 && (
            <li className={styles.now} style={{ top: `calc(${(nowMinutes - from * 60) / 60} * var(--hour))` }} aria-hidden="true" data-now="" />
          )}
        </ul>
      ))}
    </div>
    </div>
    {cut.below > 0 && (
      <div className={styles.cueBelow}>
        <button type="button" className={styles.cue} data-more="below" onClick={() => scrollBy(1)}>
          {tn("schedule.more_below", cut.below)}
        </button>
      </div>
    )}
    </>
  );
}
