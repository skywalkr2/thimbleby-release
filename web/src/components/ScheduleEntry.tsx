// One entry of the calendar page (design 7.7): the button that opens its details beside the calendar, and the words that
// say what it is, when it is and where it comes from. The calendar an entry comes from is always a word (in the button's
// name for a screen reader), with the calendar's color as a small mark beside it when one is set (with several sides, the side's color
// on the entry's edge instead, and its name in the button's name), so nothing is told apart by color alone; the app's own entries have a dashed edge as well as their words.
import { useAct } from "../lib/act";
import { api, type S } from "../lib/api";
import { day, wallTime } from "../lib/dates";
import { deliveryStatusWord } from "../lib/deliveries";
import { eventPageView, recordView, viewHref } from "../lib/views";
import type { useWords } from "../lib/wording";
import { Button as AriaButton } from "react-aria-components";
import { Icon } from "../ui/Icon";
import { Pill } from "../ui/Pill";
import { SideMark } from "../ui/SideMark";
import { RoundCheck, useCheckNow } from "../ui/RoundCheck";
import { Tooltip } from "../ui/Tooltip";
import styles from "./Schedule.module.css";

export type Entry = S["ScheduleEntryView"];
export type T = ReturnType<typeof useWords>["t"];

/** What the screen knows about the calendars: each one's name and color mark, by the id of its source. */
export interface Calendars {
  name: (id: string) => string | undefined;
  color: (id: string) => string | undefined;
  /** Whether a calendar can't be read until the person signs in again, so what it shows is from its last read. */
  stale?: (id: string) => boolean;
  /** The calendars the person reads, each with its name and mark, for the legend; left out where there is no legend. */
  list?: Array<{ id: string; name: string; color: string | null }>;
  /** The side an entry is on, as its color slot and name, worked out once by the screen; none for an entry on no known side, or when the person has one side. */
  side?: (side: string | null | undefined) => { slot: number; name: string } | null;
  /** Whether there is more than one side, so an entry's color is its side's (with a neutral edge when its side is not known). */
  bySide?: boolean;
}

/** The names of the other calendars that hold the same entry (the same invitation in two accounts), none when it is in one. */
export function alsoIn(entry: Entry, calendars: Calendars): string[] {
  return (entry.also_in ?? []).flatMap((id) => {
    const name = calendars.name(id);
    return name ? [name] : [];
  });
}

/** Which entry, on which day (an entry that goes on over several days is one on each). */
export function entryKey(entry: Entry, date: string | null): string {
  return [entry.kind, entry.snapshot, date ?? "", entry.begins ?? ""].join("|");
}

/** The page of an entry in the app: a to-do's, the app's own entry's, the entry kept for a connected event, or, for an event
 * the app keeps no entry for, a read-only page of what its calendar says. */
export function entryHref(entry: Entry): string {
  if (entry.kind === "due" && entry.action) return viewHref(recordView("action", entry.action));
  if (entry.own) return viewHref(recordView("event", entry.snapshot));
  if (entry.entry) return viewHref(recordView("event", entry.entry));
  return viewHref(eventPageView(entry.snapshot, entry.start));
}

/** What the entry is called on the screen: a due date says so. */
export function entryTitle(entry: Entry, t: T): string {
  return entry.kind === "due" ? t("schedule.due_title", { title: entry.title }) : entry.title;
}

/** Who added one of the app's own entries, read from the entry's `made_by`: the person's own say "Added by you", one the assistant
 * found says so, so the label is true. */
export function ownWords(entry: { made_by?: "assistant" | "person" | null }, t: T): string {
  return t(entry.made_by === "assistant" ? "made_by.added.assistant" : "schedule.entry.own");
}

/** Where the entry comes from, in words. */
export function fromWords(entry: Entry, calendars: Calendars, t: T): string {
  if (entry.kind === "due") return t("schedule.from_due");
  if (entry.own) return ownWords(entry, t);
  const name = calendars.name(entry.source);
  const also = alsoIn(entry, calendars);
  if (name && also.length > 0) return t("schedule.from_source_also", { source: name, others: also.join(", ") });
  return name ? t("schedule.from_source", { source: name }) : t("schedule.from_source_unknown");
}

/** When the entry is on its day, short: its start, "Until" its end for one that began earlier, or nothing for an all-day entry. */
export function shortWhen(entry: Entry, t: T): string {
  if (entry.slot === "all_day") return "";
  if (entry.begins) return wallTime(entry.begins);
  return entry.ends ? t("today.agenda.until", { time: wallTime(entry.ends) }) : "";
}

/** When the entry is on a day, in full words, for its details. */
export function fullWhen(entry: Entry, date: string | null, t: T): string {
  if (!date) return t("schedule.pane.not_dated");
  if (entry.slot === "all_day") return t("schedule.event.all_day", { date: day(date) });
  if (entry.begins && entry.ends) return t("schedule.event.range_same_day", { date: day(date), start: wallTime(entry.begins), end: wallTime(entry.ends) });
  if (entry.begins) return t("schedule.event.day_and_time", { date: day(date), time: wallTime(entry.begins) });
  return entry.ends ? t("schedule.event.day_and_time", { date: day(date), time: t("today.agenda.until", { time: wallTime(entry.ends) }) }) : t("schedule.event.all_day", { date: day(date) });
}

/** Where an entry is, for its second line: the calendar it is in by name, "In 2 calendars" for one held in several, "Added by you"
 * for the app's own (or "Added by" the assistant, for one it found), nothing for a due date (its title says it). */
export function calendarWords(entry: Entry, calendars: Calendars, t: T): string {
  if (entry.kind === "due") return "";
  if (entry.own) return ownWords(entry, t);
  const also = (entry.also_in ?? []).length;
  if (also > 0) return t("schedule.in_calendars", { n: also + 1 });
  return calendars.name(entry.source) ?? "";
}

/** The second line of an entry's block: when it begins, and that it is held in several calendars when it is. The calendar's own name is
 * the block's color and its name for a screen reader and its tooltip, so the line stays short enough for a narrow column. */
export function blockLine(entry: Entry, calendars: Calendars, t: T): string {
  const { time, rest } = blockLineParts(entry, calendars, t);
  return [time, rest].filter(Boolean).join(" · ");
}

/** The same line in its two parts: the time, which is never cut or broken across lines, and the rest (the place, the calendars), which
 * is the part that shortens when the box is narrow. */
export function blockLineParts(entry: Entry, _calendars: Calendars, t: T): { time: string; rest: string } {
  const also = entry.kind === "due" || entry.own ? 0 : (entry.also_in ?? []).length;
  return { time: shortWhen(entry, t), rest: [entry.where?.trim() ?? "", also > 0 ? t("schedule.in_calendars", { n: also + 1 }) : ""].filter(Boolean).join(" · ") };
}

/** The entry as a button. `time` puts its start before its title (a list of titles), left off where the grid's position says it.
 * `block` is the grid's block: the title, then the time and calendar on a line under it, so a block says what it is at a glance. */
export function EntryButton(props: {
  entry: Entry;
  date: string | null;
  calendars: Calendars;
  time: boolean;
  block?: boolean;
  /** A row of a clash card: the calendar's mark and the title, nothing else. */
  clash?: boolean;
  /** The block is too short for a second line of its own: the line runs on after the title. */
  short?: boolean;
  /** The block is one lane of several side by side: its title may be cut to two lines, so the whole of it shows on hover and on focus. */
  lane?: boolean;
  /** The first lane of a side-by-side clash: it starts with the word "Clash" and its icon, so a clash is never told by the icon alone. */
  tag?: boolean;
  /** How many identical entries this one stands for, when more than one. */
  count?: number;
  /** An all-day entry that goes on over several days is one bar: it joins the day before and the day after when they hold it. */
  join?: { from?: boolean; to?: boolean };
  selected: boolean;
  onOpen: (entry: Entry, date: string | null) => void;
  t: T;
}) {
  const { entry, t } = props;
  const act = useAct();
  const done = () =>
    act(
      () => api.actionStatus(entry.action as string, "done"),
      () => ({ message: t("toast.action_done_named", { text: entry.title }), undo: () => api.actionStatus(entry.action as string, "open") }),
      undefined,
      { once: `entry-done:${entry.action}` },
    );
  const [checked, tick] = useCheckNow(done);
  const status = deliveryStatusWord(entry, t);
  const when = props.time ? shortWhen(entry, t) : "";
  // With more than one side the entry's color is its side's (its 3px edge; the key is the side filter's chips), and an entry whose side is
  // not known has a neutral edge. With one side the calendar's own color tells calendars apart.
  const found = props.calendars.side?.(entry.side) ?? null;
  const slot = found?.slot ?? null;
  const sideName = found?.name ?? "";
  const color = !props.calendars.bySide && !entry.own && entry.kind !== "due" ? props.calendars.color(entry.source) : undefined;
  const stale = !entry.own && entry.kind !== "due" && !!props.calendars.stale?.(entry.source);
  const line = props.block && !props.clash ? blockLineParts(entry, props.calendars, t) : null;
  const full = [entryTitle(entry, t), shortWhen(entry, t), calendarWords(entry, props.calendars, t)].filter(Boolean).join(" · ");
  const attrs = {
    className: [props.clash ? styles.clashRow : styles.chip, props.block ? styles.block : "", entry.own || entry.kind === "due" ? styles.own : "", props.selected ? styles.selected : ""].filter(Boolean).join(" "),
    "data-entry-key": entryKey(entry, props.date),
    "data-kind": entry.kind,
    "data-color": color,
    "data-side-slot": slot ?? undefined,
    "data-source": entry.own ? "own" : entry.source,
    "data-selected": props.selected ? "" : undefined,
    "data-short": props.short ? "" : undefined,
    "data-lane": props.lane ? "" : undefined,
    "data-tagged": props.tag ? "" : undefined,
    "data-stale": stale ? "" : undefined,
    "data-join-from": props.join?.from ? "" : undefined,
    "data-join-to": props.join?.to ? "" : undefined,
  };
  const inner = (
    <>
      {props.tag && (
        // The first lane of a clash starts with the icon and the word on a line of its own, so a clash is never told by the icon alone.
        <span className={styles.clashTag} data-clash-tag="">
          <Icon name="alert" size={14} />
          {t("schedule.clash.head")}
        </span>
      )}
      {color && (!props.block || props.clash) && <span className={styles.mark} data-color={color} aria-hidden="true" />}
      {when && <span className={styles.when}>{when}</span>}
      <span className={entry.cancelled ? `${styles.name} ${styles.struck}` : styles.name}>{entryTitle(entry, t)}</span>
      {props.count && props.count > 1 && (
        <>
          <span className={styles.times} aria-hidden="true">
            {t("schedule.times", { n: props.count })}
          </span>
          <span className="sr">, {t("schedule.times_sr", { n: props.count })}</span>
        </>
      )}
      {props.clash && <SideMark side={entry.side} />}
      {entry.cancelled && <Pill tone="warn">{t(entry.held ? "calledoff.on_hold" : "today.agenda.called_off")}</Pill>}
      {status && <Pill tone={entry.delivery?.status === "arrived" ? "ok" : "neutral"}>{status}</Pill>}
      {line && (line.time || line.rest) && (
        <span className={styles.line} data-entry-line="">
          {line.time && (
            <span className={styles.lineTime} data-entry-time="">
              {line.time}
            </span>
          )}
          {line.rest && (
            <span className={styles.linePlace}>
              {line.time && <span className={styles.sep}>{" · "}</span>}
              {line.rest}
            </span>
          )}
        </span>
      )}
      {stale && (
        <span className={styles.staleNote} data-stale-note="" aria-hidden="true">
          {t("schedule.entry.stale_short")}
        </span>
      )}
      <span className="sr">
        , {fromWords(entry, props.calendars, t)}
        {sideName ? `, ${t("schedule.entry.side_sr", { side: sideName })}` : ""}
        {stale ? `. ${t("schedule.entry.stale")}` : ""}
      </span>
    </>
  );
  // A lane of a side-by-side clash cuts its title to two lines, and so does a chip of the Month or of a list: the whole of it shows on
  // hover and on keyboard focus (a tooltip does both; a native title does only the first). A block of the grid keeps its title.
  const tipText = props.lane ? full : props.time && !props.block && !props.clash ? entryTitle(entry, t) : null;
  const button = tipText ? (
    <Tooltip text={tipText} placement="top">
      <AriaButton {...attrs} onPress={() => props.onOpen(entry, props.date)}>
        {inner}
      </AriaButton>
    </Tooltip>
  ) : (
    <button type="button" {...attrs} title={props.block || props.clash ? full : undefined} onClick={() => props.onOpen(entry, props.date)}>
      {inner}
    </button>
  );
  // A to-do among the entries has the same mark as on the To-dos list; a calendar's entry has none, only its calendar's edge.
  return entry.kind === "due" && entry.action ? (
    <span className={styles.dueRow} data-due-row="">
      <RoundCheck small checked={checked} label={t("today.todo.done_named", { text: entry.title })} tip={t("followups.mark_done")} onClick={tick} />
      {button}
    </span>
  ) : (
    button
  );
}
