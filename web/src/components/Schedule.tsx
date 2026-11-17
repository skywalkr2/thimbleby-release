// The calendar page (design 7.7): Day, Work week, Week and Month views of everything the app knows is on a day (the person's
// calendars, the app's own entries, deliveries and due dates), each entry a button that opens its details beside the calendar,
// and the Timeline, where each piece of work stands over the coming weeks (ScheduleTimeline). The arrows and the Today button
// move by the view's unit (a range, in the Timeline), the keys 1 to 5 pick the view (which is remembered on this
// browser), the side filter narrows the entries, and Escape closes the details and returns the cursor to the entry (the keys are listed in the shortcuts menu). Week and
// Work week fall back to Day in a space too narrow for their columns. Read and open only: nothing here changes a calendar.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type TouchEvent } from "react";
import { ApiError, api, type S } from "../lib/api";
import { calendarNames, withoutAddress, clashesOf, clashPhrase, minutesOf, moveBy, rangeOf, rememberView, SHORT, startOfWeek, storedView, VIEWS, type CalendarView } from "../lib/calendar";
import { RANGE_DAYS, RANGES, rememberRange, storedRange, type TimelineRange } from "../lib/timeline";
import { addDays, fullDay, shortDay, shortRange, todayOn, monthDayLong, monthDayYear, monthYear, weekday, weekdayLong } from "../lib/dates";
import { typing } from "../lib/keys";
import { useIsNarrow, useMediaQuery, useWidth } from "../lib/media";
import { signInNeed } from "../lib/connections";
import { onAnySide, onSide, useSideFilter } from "../lib/sides";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { sideSlot } from "../ui/MarkDot";
import { IconButton } from "../ui/IconButton";
import { FilterSheet } from "../ui/FilterSheet";
import { ListDetail } from "../ui/ListDetail";
import { LoadFailed } from "../ui/LoadFailed";
import { SegmentedControl } from "../ui/SegmentedControl";
import { ViewTabs } from "../ui/ViewTabs";
import { Skeleton } from "../ui/Skeleton";
import { ScheduleSkeleton } from "./ScheduleSkeleton";
import { restoreFocus } from "./ModalPanel";
import { SideFilter } from "./SideFilter";
import { useNow } from "./RailSources";
import { AddMeeting } from "./ScheduleCard";
import { NewEvent } from "./NewEvent";
import { ScheduleMenu } from "./ScheduleMenu";
import { EntryButton, entryKey, entryTitle, type Calendars, type Entry } from "./ScheduleEntry";
import { ScheduleLegend, useHiddenCalendars } from "./ScheduleLegend";
import { EntryDetails } from "./ScheduleEntryPane";
import { clashCards, TimeGrid, type DayEntries } from "./ScheduleGrid";
import { ScheduleList } from "./ScheduleList";
import { GroupDetails } from "./ScheduleGroupPane";
import { groupKey, type GroupRef } from "./ScheduleGroupCard";
import { ScheduleStale } from "./ScheduleStale";
import { WeekAhead } from "./WeekAhead";
import { ScheduleSides, type KeySide } from "./ScheduleSides";
import { MonthGrid } from "./ScheduleMonth";
import { NeedsADate } from "./NeedsADate";
import { Timeline, type Lane } from "./ScheduleTimeline";
import styles from "./Schedule.module.css";

import { PageHeader } from "../ui/PageHeader";
/** How far, in pixels, a touch must travel sideways to count as a swipe. */
const SWIPE_MIN = 60;
/** The room, in pixels, the Week and Work week columns need (an hour column and about 96px for each day); in less the
 * calendar shows Day. */
const WEEK_MIN = 736;
const WORK_WEEK_MIN = 544;
/** The id the app's own calendar has among the calendars the legend lists (an entry's `data-source` says the same). */
const OWN_CALENDAR = "own";

type Page = S["ScheduleView"];
/** What the server says about the person's week and hours, kept from the last answer so the next request can be made at once. */
const FIRST_MEANS: Pick<Page, "week_starts_on" | "work_days" | "event_minutes"> = { week_starts_on: 0, work_days: [0, 1, 2, 3, 4], event_minutes: 60 };
/** The keys that pick a view, in the order of the view switch. */
const VIEW_KEYS: Record<string, CalendarView> = { "1": "day", "2": "work_week", "3": "week", "4": "month", "5": "timeline" };

function findEntry(entries: DayEntries[], rest: Entry[], key: string): { entry: Entry; date: string | null } | null {
  for (const d of entries) {
    for (const entry of [...d.all_day, ...d.timed]) if (entryKey(entry, d.date) === key) return { entry, date: d.date };
  }
  const entry = rest.find((e) => entryKey(e, null) === key);
  return entry ? { entry, date: null } : null;
}

export function Schedule() {
  const { t, tn } = useWords();
  const filter = useSideFilter();
  const [pick, setPick] = useState<CalendarView>(storedView);
  // The Timeline's range: the person's last pick on this browser, else what the workspace's setting says (read with the answer).
  const [rangePick, setRangePick] = useState<TimelineRange | null>(storedRange);
  // The day being looked at; none means today, wherever the server says today is.
  const [anchor, setAnchor] = useState<string | null>(null);
  const [means, setMeans] = useState<Pick<Page, "week_starts_on" | "work_days" | "event_minutes"> & { today: string | null }>({ ...FIRST_MEANS, today: null });
  const region = useRef<HTMLDivElement>(null);
  const width = useWidth(region);
  // Below this the week has no room for seven days: it shows the working days, and says so. On a phone it is a list by day.
  const weekdaysOnly = useMediaQuery("(max-width: 1099.98px)");
  const phone = useIsNarrow();
  const now = useNow();

  // Week and Work week need room for their columns; without it the calendar shows Day. A width not yet known counts as enough.
  const room = width ?? Number.POSITIVE_INFINITY;
  const fits = (v: CalendarView) => (phone && (v === "week" || v === "work_week") ? true : v === "week" ? room >= WEEK_MIN : v === "work_week" ? room >= WORK_WEEK_MIN : true);
  const view: CalendarView = fits(pick) ? pick : "day";
  // The week with seven days needs the room of a wide window; with less it is the working days.
  // On a phone the week is a list by day, which has room for all seven days.
  const shown: CalendarView = view === "week" && weekdaysOnly && !phone ? "work_week" : view;
  const asList = phone && (view === "week" || view === "work_week");

  const today = means.today ?? todayOn(now);
  const date = anchor ?? today;
  const range = useMemo(() => rangeOf(shown, date, means.week_starts_on, means.work_days, today), [shown, date, means.week_starts_on, means.work_days, today]);
  const isTimeline = view === "timeline";
  const page = useQuery({ queryKey: ["today", "schedule", range.first, range.days], queryFn: () => api.schedule(range.first, range.days), placeholderData: keepPreviousData, enabled: !isTimeline });
  // The Timeline starts on the first day of the week of the day being looked at, or of this week when none is.
  const timelineFrom = anchor === null ? null : startOfWeek(anchor, means.week_starts_on);
  const timeline = useQuery({ queryKey: ["today", "schedule", "timeline", timelineFrom, rangePick], queryFn: () => api.scheduleTimeline(timelineFrom, rangePick), placeholderData: keepPreviousData, enabled: isTimeline });
  const needs = useQuery({ queryKey: ["open-items"], queryFn: api.openItems, enabled: isTimeline });
  const rangeName: TimelineRange = rangePick ?? timeline.data?.default_range ?? "ten_weeks";
  const tl = timeline.data;
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const data = page.data;
  useEffect(() => {
    const known = data ?? tl;
    if (known) setMeans((m) => (m.today === known.today && m.week_starts_on === known.week_starts_on && m.work_days.join() === known.work_days.join() ? m : { ...m, today: known.today, week_starts_on: known.week_starts_on, work_days: known.work_days }));
    if (data) setMeans((m) => (m.event_minutes === data.event_minutes ? m : { ...m, event_minutes: data.event_minutes }));
  }, [data, tl]);

  // Whether the app's own calendar holds an entry in what is drawn, so it is listed among the calendars.
  const hasOwn = (data?.days ?? []).some((d) => [...d.all_day, ...d.timed].some((e) => e.own)) || (tl?.lanes ?? []).some((l) => l.items.some((i) => i.entry?.own));
  // The sides' names, as one string so the calendars' names are worked out again only when a side is renamed or added.
  const sideNames = filter.options.map((o) => `${o.id}\u0000${o.name}`).join("\u0001");
  const calendars: Calendars = useMemo(() => {
    const found = watch.data ?? [];
    // A calendar is named by its side or its own label, never by its account's address.
    const calendarLike = found.filter((s) => (s.reads ?? []).includes("calendar"));
    const short = calendarNames(calendarLike, (side) => filter.options.find((o) => o.id === side)?.name, { numbered: (name, n) => t("schedule.calendar.numbered", { name, n }), fallback: t("schedule.calendar.fallback") });
    const names = new Map(found.map((s) => [s.id, short.get(s.id) ?? (withoutAddress(s.label, s.account) || t("schedule.calendar.fallback"))]));
    // Each calendar has a color: the one the person picked, else one the app gave it, so two calendars are told apart.
    const colors = new Map(found.flatMap((s) => (s.shown_color || s.color ? [[s.id, (s.shown_color ?? s.color) as string] as const] : [])));
    const list = found.filter((s) => s.enabled && (s.reads ?? []).includes("calendar")).map((s) => ({ id: s.id, name: names.get(s.id) ?? s.label, color: filter.offered ? null : (s.shown_color ?? s.color ?? null) }));
    // The same test the banner above the calendar uses, so a calendar the banner names has its entries marked.
    const stale = new Set(found.filter((s) => signInNeed(s) !== null).map((s) => s.id));
    // The app's own calendar is one of the calendars while it holds an entry: it is listed, and its entries can be hidden like any other's.
    const withOwn = hasOwn ? [...list, { id: OWN_CALENDAR, name: t("schedule.pane.calendar_own"), color: null }] : list;
    const order = filter.options.map((o) => o.id);
    const side = (id: string | null | undefined) => {
      const at = id && filter.offered ? order.indexOf(id) : -1;
      return at < 0 ? null : { slot: sideSlot(at), name: filter.options[at].name };
    };
    return { name: (id) => names.get(id), color: (id) => colors.get(id), stale: (id) => stale.has(id), list: withOwn, side, bySide: filter.offered };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watch.data, sideNames, hasOwn, filter.offered]);
  // The calendars the person hid with the legend: an entry shows unless every calendar that holds it is hidden.
  const [hidden, toggleCalendar] = useHiddenCalendars();
  const visible = (e: Entry) =>
    e.kind === "due" || (e.own ? !hidden.has(OWN_CALENDAR) : !hidden.has(e.source) || ((e.also_in ?? []).length > 0 && (e.also_in ?? []).some((id) => !hidden.has(id))));

  // An entry of a calendar that serves several sides shows under each of them and under no other; any other entry under its own side.
  const shownUnder = (e: { side?: string | null; sides?: string[] | null; views?: string[] | null }) =>
    e.sides && e.sides.length > 0 ? onAnySide(e.sides, filter.picked, e.views) : filter.shows(e.side, e.views);
  // What each shown day holds under the side filter: an entry on no side shows under every choice.
  const days: DayEntries[] = useMemo(() => {
    const byDate = new Map((data?.days ?? []).map((d) => [d.date, d]));
    return range.shown.map((d) => {
      const found = byDate.get(d);
      return {
        date: d,
        all_day: (found?.all_day ?? []).filter((e) => shownUnder(e) && visible(e)),
        timed: (found?.timed ?? []).filter((e) => shownUnder(e) && visible(e)),
        clashes: (data?.clashes ?? []).filter((c) => c.day === d),
      };
    });
    // shownUnder and visible are rebuilt every render from filter.picked and hidden, which the memo is keyed on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, range, filter.picked, hidden]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const onItsWay = useMemo(() => (data?.on_its_way ?? []).filter((e) => shownUnder(e)), [data, filter.picked]);

  // What the Timeline holds under the side filter: a lane shows under the side it is on and the views of its project.
  const lanes: Lane[] = useMemo(() => (tl?.lanes ?? []).filter((l) => onSide(l.side, filter.picked, l.views, l.in_project)), [tl, filter.picked]);
  const timelineEntries = useMemo(() => new Map(lanes.flatMap((l) => l.items.flatMap((i) => (i.entry ? [[entryKey(i.entry, i.start), { entry: i.entry, date: i.start }] as const] : [])))), [lanes]);

  // The entry whose details are open.
  const [picked, setPicked] = useState<string | null>(null);
  const found = picked ? (isTimeline ? (timelineEntries.get(picked) ?? null) : findEntry(days, onItsWay, picked)) : null;
  const pickedRef = useRef(picked);
  pickedRef.current = picked;
  useEffect(() => {
    if (picked && (isTimeline ? tl : data) && !found) setPicked(null);
  }, [picked, data, tl, isTimeline, found]);
  // A group of meetings (a clash) opened from its "+N more": the pane lists every meeting, and each opens its own details in the same pane.
  const [grouped, setGrouped] = useState<GroupRef | null>(null);
  const groupedRef = useRef(grouped);
  groupedRef.current = grouped;
  const groupItems = grouped ? grouped.keys.flatMap((k) => findEntry(days, [], k) ?? []) : [];
  useEffect(() => {
    if (grouped && data && !page.isPlaceholderData && groupItems.length === 0) setGrouped(null);
  }, [grouped, data, groupItems.length, page.isPlaceholderData]);
  const open = (entry: Entry, on: string | null) => setPicked(entryKey(entry, on));
  const openGroup = (group: GroupRef) => {
    setPicked(null);
    setGrouped(group);
  };
  // Back from one meeting's details to the group's list: the cursor goes to the meeting it came from.
  const backToGroup = () => {
    const key = pickedRef.current;
    setPicked(null);
    if (key) restoreFocus(() => Array.from(document.querySelectorAll<HTMLElement>("[data-group-pane] [data-entry-key]")).find((el) => el.getAttribute("data-entry-key") === key));
  };
  const close = () => {
    const key = pickedRef.current;
    const group = groupedRef.current;
    if (!key && !group) return;
    setPicked(null);
    setGrouped(null);
    // Focus goes back to what opened the pane: the entry, or the "+N more" of its group.
    if (key) restoreFocus(() => Array.from(document.querySelectorAll<HTMLElement>("[data-entry-key]")).find((el) => el.getAttribute("data-entry-key") === key));
    else if (group) restoreFocus(() => document.querySelector<HTMLElement>(`[data-group-more="${groupKey(group.date, group.start)}"]`));
  };

  const go = (n: number) => {
    // The Timeline moves by the range it shows, from its own first day.
    const next = isTimeline ? addDays(tl?.first ?? startOfWeek(date, means.week_starts_on), n * RANGE_DAYS[tl?.range ?? rangeName]) : moveBy(view, date, n);
    setAnchor(next === today ? null : next);
  };
  const choose = (next: CalendarView) => {
    setPick(next);
    rememberView(next);
  };
  const chooseRange = (next: TimelineRange) => {
    setRangePick(next);
    rememberRange(next);
  };
  const openDay = (on: string) => {
    setAnchor(on === today ? null : on);
    choose("day");
  };
  // Keys are read from refs so one listener serves every render.
  const viewRef = useRef(view);
  viewRef.current = view;
  const keys = useRef({ go, choose, close, fits });
  keys.current = { go, choose, close, fits };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
      if (document.querySelector("[data-modal-open]")) return;
      if (event.key === "Escape") {
        if (pickedRef.current || groupedRef.current) {
          event.preventDefault();
          keys.current.close();
        }
        return;
      }
      const arrow = event.key === "ArrowLeft" || event.key === "ArrowRight";
      const picks = VIEW_KEYS[event.key];
      if (!arrow && !picks) return;
      if (picks) {
        event.preventDefault();
        if (keys.current.fits(picks)) keys.current.choose(picks);
        return;
      }
      // The arrows only with the cursor on the screen's own content or on no control at all: a menu or a group of options
      // keeps its arrows.
      const target = event.target instanceof Node ? event.target : null;
      if (target !== document.body && !(region.current && target && region.current.contains(target))) return;
      event.preventDefault();
      // Shift moves a week in Day view; the other views already move by that much or more.
      keys.current.go((event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey && viewRef.current === "day" ? 7 : 1));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  // On the phone layout a sideways swipe moves by the view's unit, as the arrows do (they stay, so nobody is left without a way
  // to move). A swipe is mostly sideways and long enough; one that is mostly up or down is the page scrolling and moves nothing.
  const touch = useRef<{ x: number; y: number } | null>(null);
  const swipeStart = (event: TouchEvent) => {
    const [first] = Array.from(event.touches);
    touch.current = event.touches.length === 1 && first && document.documentElement.hasAttribute("data-narrow") && !typing(event.target) ? { x: first.clientX, y: first.clientY } : null;
  };
  const swipeEnd = (event: TouchEvent) => {
    const from = touch.current;
    touch.current = null;
    const [end] = Array.from(event.changedTouches);
    if (!from || !end) return;
    const across = end.clientX - from.x;
    const down = end.clientY - from.y;
    if (Math.abs(across) < SWIPE_MIN || Math.abs(across) < Math.abs(down) * 1.5) return;
    keys.current.go(across < 0 ? 1 : -1);
  };

  const unit = view === "month" ? "month" : view === "day" ? "day" : isTimeline ? "timeline" : "week";
  // The clashes the days shown hold, each with the day it is on and how many meetings are in it.
  const found_clashes = days.flatMap((d) => clashCards(d, d.timed.map((e) => ({ item: e, start: minutesOf(e.begins) ?? 0, end: Math.max(minutesOf(e.ends) ?? (minutesOf(e.begins) ?? 0) + SHORT, (minutesOf(e.begins) ?? 0) + 1) }))).map((g) => ({ date: d.date, meetings: g.items.length, overlap: g.overlap > 0 })));
  const clashes = found_clashes.map((c) => c.date);
  // The line that names the clashes jumps to the first one on the grid (or its mark in a month).
  const toClash = () => region.current?.querySelector<HTMLElement>("[data-clash],[data-clash-mark]")?.scrollIntoView?.({ block: "nearest" });
  // The week's "so what" in one line: the clashes and how many meetings there are (the days of the month, in a month). A meeting is
  // what has a time; the all-day entries are counted apart.
  const inRange = days.filter((d) => view !== "month" || d.date.slice(0, 7) === date.slice(0, 7));
  const isMeeting = (e: Entry) => !e.cancelled && e.kind !== "due" && e.kind !== "delivery";
  const meetings = inRange.reduce((n, d) => n + d.timed.filter(isMeeting).length, 0);
  const allDay = inRange.reduce((n, d) => n + d.all_day.filter(isMeeting).length, 0);
  // The to-dos drawn on their due days are counted apart from the meetings.
  const due = inRange.reduce((n, d) => n + [...d.all_day, ...d.timed].filter((e) => !e.cancelled && e.kind === "due").length, 0);
  // The Timeline's line is how many items it shows, so the title block is as tall on it as on the other views.
  const timelineCount = lanes.reduce((n, l) => n + l.items.length, 0);
  // The Timeline counts clashes the way every screen does: a run of pairs that share a meeting is one clash.
  const timelineClashes = clashesOf(tl?.clashes ?? []);
  const timelineMeetings = new Set(
    (tl?.clashes ?? []).flatMap((c) => [`${c.group}|${c.first.snapshot}#${c.first.start}`, `${c.group}|${c.second.snapshot}#${c.second.start}`]),
  ).size;
  const subtitle = isTimeline ? (timelineCount > 0 || timelineClashes.length > 0 ? (
      <>
        {timelineClashes.length > 0 && (
          <span data-timeline-clashes="" title={t(timelineClashes.length === 1 ? "schedule.clash.sub.one" : "schedule.clash.sub.other", { day: monthDayLong(timelineClashes[0].day) })}>
            {clashPhrase(tn, timelineClashes.length, timelineMeetings, (tl?.clashes ?? []).some((c) => c.kind === "overlap"), weekday(timelineClashes[0].day))}
          </span>
        )}
        {timelineClashes.length > 0 && timelineCount > 0 && " · "}
        {timelineCount > 0 && <span data-timeline-count="">{tn("schedule.timeline.count", timelineCount)}</span>}
      </>
    ) : undefined) : clashes.length === 0 && meetings === 0 && allDay === 0 && due === 0 ? (!page.isSuccess || page.isPlaceholderData ? undefined : (
      <span className={styles.summary} data-summary=""><span className={styles.summaryPart} data-meetings="">{t("schedule.summary.none")}</span></span>
    )) : (
      <span className={styles.summary} data-summary="">
        {clashes.length > 0 && (
          <span className={styles.summaryPart} data-clash-summary="">
            <span data-clash-count="">{tn(`schedule.clashes.${unit === "month" ? "month" : unit === "day" ? "day" : "week"}`, clashes.length)}</span>
            <button type="button" className="link-button" data-clash-jump="" title={t(clashes.length === 1 ? "schedule.clash.sub.one" : "schedule.clash.sub.other", { day: weekdayLong(clashes[0]) })} onClick={toClash}>
              {t(clashes.length === 1 ? "schedule.clash.show_it" : "schedule.clash.show_first")}
            </button>
          </span>
        )}
        {(meetings > 0 || allDay > 0 || due > 0) && (
          <span className={styles.summaryPart} data-meetings="">
            {[meetings > 0 ? tn("schedule.meetings", meetings) : "", allDay > 0 ? tn("schedule.all_day_count", allDay) : "", due > 0 ? tn("schedule.due_count", due) : ""].filter(Boolean).join(" · ")}
          </span>
        )}
      </span>
    );
  const back = { day: t("schedule.back.day"), week: t("schedule.back.week"), month: t("schedule.back.month"), timeline: t("schedule.back.timeline") }[unit];
  const forward = { day: t("schedule.forward.day"), week: t("schedule.forward.week"), month: t("schedule.forward.month"), timeline: t("schedule.forward.timeline") }[unit];
  // On a phone the range is short ("Nov 2 – 6") so the row of moves and the range stays one line.
  const rangeText = (first: string, last: string) => (phone ? t("schedule.range", shortRange(first, last)) : t("schedule.range", { start: monthDayLong(first), end: monthDayYear(last) }));
  const heading = isTimeline
    ? tl
      ? rangeText(tl.first, tl.last)
      : t("schedule.view.timeline")
    : view === "day"
      ? phone
        ? shortDay(date)
        : fullDay(date)
      : view === "month"
        ? monthYear(date)
        : rangeText(range.shown[0], range.shown[range.shown.length - 1]);
  const viewNames: Record<CalendarView, string> = { day: t("schedule.view.day"), work_week: t("schedule.view.work_week"), week: t("schedule.view.week"), month: t("schedule.view.month"), timeline: t("schedule.view.timeline") };
  const rangeOptions = RANGES.map((r) => ({ value: r, label: t(`schedule.timeline.range.${r}`) }));
  const needDate = (needs.data?.actions ?? []).filter((a) => a.needs_date && onSide(a.side, filter.picked, a.views, !!a.project_name));
  const options = VIEWS.filter(fits).map((v) => ({ value: v, label: viewNames[v] }));
  // The page the entry would be added to could not be read: Add waits for it, with its reason beside it.
  const dead = isTimeline ? timeline.isError && !tl : page.isError && !data;
  // The sides with an entry in the range on screen, in the person's order: the key to the colors of the entries drawn.
  const drawnSides = new Set([...days.flatMap((d) => [...d.all_day, ...d.timed]), ...onItsWay].map((e) => e.side).filter((x): x is string => !!x));
  const keySides: KeySide[] = filter.options.flatMap((o) => {
    const found = calendars.side?.(o.id);
    return found && drawnSides.has(o.id) ? [{ id: o.id, name: found.name, slot: found.slot }] : [];
  });
  const empty = days.every((d) => d.all_day.length === 0 && d.timed.length === 0);

  return (
    <section className="panel-section" aria-labelledby="schedule-title" ref={region}>
      <PageHeader
        id="schedule-title"
        title={t("schedule.title")}
        subtitle={subtitle}
        reserveSubtitle
        className={styles.header}
        // The account line is told from the sign-in states, not from the days, so it holds its place while the days load and nothing moves when they come.
        banners={<ScheduleStale nameOf={calendars.name} />}
        // Today and Add stand on the first row of controls (the moves and the range) with the page's other adds, not in the title's row. On a phone
        // the tab bar's plus hands something in rather than adding to the schedule, so both adds are in the menu at the right of the title's row.
        more={phone ? <ScheduleMenu today={today} minutes={means.event_minutes} held={dead} /> : undefined}
      />
      <div className={styles.bar}>
        <div className={`${styles.row} ${styles.navRow}`} data-bar-row="" data-nav-row="">
          <div className={styles.nav} role="group" aria-label={t("schedule.nav")}>
            <IconButton icon="chevron" label={back} className={styles.back} variant="secondary" onPress={() => go(-1)} />
            <Button onClick={() => setAnchor(null)} data-today-button="">{t("schedule.today")}</Button>
            <IconButton icon="chevron" label={forward} variant="secondary" onPress={() => go(1)} />
          </div>
          <h2 className={styles.range} aria-live="polite">
            {heading}
          </h2>
          {!phone && (
            // Today draws no Schedule card on a day with nothing in it, so adding a meeting is also offered here; a connected calendar that can
            // add events after the person's yes offers a new event on it.
            <div className={styles.addActions} role="group" aria-label={t("schedule.add_actions")}>
              <NewEvent today={today} />
              <AddMeeting today={today} minutes={means.event_minutes} primary held={dead} />
            </div>
          )}
        </div>
        <div className={isTimeline ? styles.row : `${styles.row} ${styles.viewsRow}`} data-bar-row="">
          <ViewTabs<CalendarView> label={t("schedule.views")} value={view} onChange={choose} options={options} className={styles.views} />
          {isTimeline && (
            <span className={styles.rangeSwitch} data-range-switch="">
              <SegmentedControl<TimelineRange> label={t("schedule.timeline.range")} value={tl?.range ?? rangeName} onChange={chooseRange} options={rangeOptions} className={styles.views} />
            </span>
          )}
          {phone ? (
            // On a phone the calendars and the side filter are one Filter sheet, so the bar stays the moves and the views.
            (calendars.list ?? []).length > 1 || filter.offered ? (
              <FilterSheet active={(hidden.size > 0 && (calendars.list ?? []).length > 1 ? 1 : 0) + (filter.picked !== "all" ? 1 : 0)}>
                <ScheduleLegend calendars={calendars} hidden={hidden} onToggle={toggleCalendar} />
                <SideFilter marks />
              </FilterSheet>
            ) : null
          ) : (
            <>
              <ScheduleLegend calendars={calendars} hidden={hidden} onToggle={toggleCalendar} />
              <SideFilter marks />
            </>
          )}
        </div>
      </div>
      {/* The assistant's reading of this week sits at the top of the week's views (this week only: it reads no other). */}
      {(view === "week" || view === "work_week") && anchor === null && <WeekAhead />}
      <ListDetail
        title={found ? entryTitle(found.entry, t) : grouped ? t(grouped.allDay ? "schedule.group.all_all_day" : "schedule.group.all", { n: grouped.keys.length, time: grouped.time, date: grouped.allDay ? shortDay(grouped.date) : "" }) : ""}
        onClose={close}
        floating
        anchorTo={picked ? `[data-entry-key="${picked.replace(/["\\]/g, "\\$&")}"]` : grouped ? `[data-group-more="${groupKey(grouped.date, grouped.start)}"]` : undefined}
        detail={
          found ? (
            <>
              {grouped && (
                <Button variant="secondary" size="sm" onClick={backToGroup} data-group-back="">
                  {t(grouped.allDay ? "schedule.group.back_all_day" : "schedule.group.back", { n: grouped.keys.length })}
                </Button>
              )}
              <EntryDetails entry={found.entry} date={found.date} calendars={calendars} />
            </>
          ) : grouped && groupItems.length > 0 ? (
            <GroupDetails items={groupItems.map((g) => g.entry)} date={grouped.date} calendars={calendars} onOpen={open} allDay={grouped.allDay} />
          ) : null
        }
      >
        {isTimeline ? (
          timeline.isPending ? (
            <Skeleton />
          ) : timeline.isError || !tl ? (
            <LoadFailed message={t("schedule.timeline.load_failed")} onRetry={() => void timeline.refetch()} />
          ) : (
            <div className={styles.frame} data-swipe="" data-view={view} data-shown={shown} onTouchStart={swipeStart} onTouchEnd={swipeEnd} onTouchCancel={() => (touch.current = null)}>
              <Timeline data={tl} lanes={lanes} sideName={(side) => filter.options.find((o) => o.id === side)?.name} selected={picked} onOpen={open} colorOf={(e) => calendars.color(e.source)} nameOf={(e) => calendars.name(e.source)} />
            </div>
          )
        ) : page.isPending ? (
          <ScheduleSkeleton view={view === "month" ? "month" : asList ? "list" : "grid"} days={range.shown.length} />
        ) : page.isError || !data ? (
          <LoadFailed message={t("schedule.load_failed")} detail={page.error instanceof ApiError && page.error.detail ? page.error.detail : null} onRetry={() => void page.refetch()} />
        ) : (
          <div className={styles.frame} data-swipe="" data-view={view} data-shown={shown} onTouchStart={swipeStart} onTouchEnd={swipeEnd} onTouchCancel={() => (touch.current = null)}>
            {page.isPlaceholderData ? (
              // The answer for a new range is on its way: the days of the new range are never drawn from the answer for another one (a bare
              // lane for a day that holds entries). The frame stays, so a swipe or a key goes on working; its days wait for their answer.
              <ScheduleSkeleton view={view === "month" ? "month" : asList ? "list" : "grid"} days={range.shown.length} />
            ) : view === "month" ? (
              <>
                <ScheduleSides sides={keySides} />
                <MonthGrid days={days} today={data.today} month={date} limit={data.month_entries} calendars={calendars} selected={picked} onOpen={open} onOpenDay={openDay} listBelow={phone} />
              </>
            ) : asList ? (
              <>
                <ScheduleSides sides={keySides} />
                <ScheduleList days={days} today={data.today} calendars={calendars} selected={picked} onOpen={open} />
              </>
            ) : (
              <TimeGrid lead={<ScheduleSides sides={keySides} />} onOpenGroup={openGroup} days={days} today={data.today} startsAt={data.grid_starts} endsAt={data.grid_ends} now={now} calendars={calendars} selected={picked} onOpen={open} />
            )}
            {view === "week" && weekdaysOnly && !phone && !empty && <p className={styles.none} data-weekdays-only="">{t("schedule.weekdays_only")}</p>}
          </div>
        )}
        {isTimeline && <NeedsADate rows={needDate} hint="schedule.timeline.needs_hint" />}
        {!isTimeline && data && onItsWay.length > 0 && (
          <section className={styles.waiting} aria-labelledby="schedule-on-its-way">
            <h2 id="schedule-on-its-way" className={styles.caption}>
              {t("today.agenda.on_its_way")}
            </h2>
            <ul className={styles.waitList}>
              {onItsWay.map((e, i) => (
                <li key={`${entryKey(e, null)}:${i}`}>
                  <EntryButton entry={e} date={null} calendars={calendars} time={false} selected={picked === entryKey(e, null)} onOpen={open} t={t} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </ListDetail>
    </section>
  );
}
