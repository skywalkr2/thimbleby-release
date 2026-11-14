// A group card on the time grid (design 7.7): the meetings that clash, or overlap in a column too narrow to stand side by side, as one
// card from their first start to their last end. Each member is a row of its own (its start, then its title, which wraps rather than
// being cut). A card keeps to its box: the grid gives a clash card the free room below it when its rows need more than its span (and
// never room another entry has), and the rows that still do not fit are not drawn at all, never half, and are counted in a "+N more"
// button inside the card that opens the clash in the side pane, listing every meeting; no row is ever partly out of its box.
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useWords } from "../lib/wording";
import { EntryButton, entryKey, type Calendars, type Entry } from "./ScheduleEntry";
import styles from "./Schedule.module.css";

/** The room the "+N more" button takes under the last row, in px. */
const MORE_H = 24;

/** A group's meetings, as the side pane names them: the day, when the group starts and which entries (by key). */
export interface GroupRef {
  date: string;
  time: string;
  /** The group's start in minutes after midnight, as text. */
  start: string;
  keys: string[];
  /** The group is a day's all-day entries (the band's "+N more"), not meetings at a time. */
  allDay?: boolean;
}

/** The key that ties a group's "+N more" button to the pane it opens (the pane points back to it, and focus returns to it). */
export const groupKey = (date: string, start: string): string => `${date}|${start}`;

/** One meeting of a group: its start, then its title and side, as the card's rows and the pane's list both draw it. */
export function GroupRow(props: { entry: Entry; date: string; calendars: Calendars; selected: string | null; onOpen: (entry: Entry, date: string | null) => void }) {
  const { t } = useWords();
  return <EntryButton entry={props.entry} date={props.date} calendars={props.calendars} time block clash selected={props.selected === entryKey(props.entry, props.date)} onOpen={props.onOpen} t={t} />;
}

export function GroupCard(props: {
  tone: "clash" | "overlap";
  label: string;
  head: ReactNode;
  /** The heading in a few words ("Clash · 30 min short"), for a card with no room for even one meeting under the whole heading: it is the
   * whole of a shorter sentence, never the first part of the long one, and the long one stays in the card's hover text. */
  brief?: ReactNode;
  headTitle?: string;
  items: Entry[];
  /** The time the group starts, written as the person's clock writes it. */
  time: string;
  /** The group's start in minutes after midnight, which with the day names it for the pane. */
  startKey: string;
  date: string;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
  /** Opens the group in the side pane (its "+N more"). */
  onMore: (group: GroupRef) => void;
}) {
  const { t, tn } = useWords();
  const card = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLParagraphElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState(0);
  const [tick, setTick] = useState(0);
  const names = props.items.map((e) => entryKey(e, props.date)).join("|");
  useLayoutEffect(() => {
    const box = card.current;
    if (!box || typeof ResizeObserver !== "function") return;
    const watch = new ResizeObserver(() => setTick((n) => n + 1));
    watch.observe(box);
    return () => watch.disconnect();
  }, []);
  useLayoutEffect(() => {
    const box = card.current;
    const rows = Array.from(list.current?.children ?? []) as HTMLElement[];
    const heading = head.current;
    if (!box || !heading || rows.length === 0) return;
    // The "+N more" button of an earlier measure is out of the way while the rows are measured, so it never takes the room they need.
    const button = box.querySelector<HTMLElement>("[data-group-more]");
    if (button) button.hidden = true;
    const parts = Array.from(heading.children) as HTMLElement[];
    const hasBrief = parts.some((part) => part.hasAttribute("data-head-brief"));
    // The whole heading, or the short sentence in its place (never the first part of the long one).
    const showHeading = (brief: boolean) => {
      heading.hidden = false;
      for (const part of parts) part.hidden = part.hasAttribute("data-head-brief") !== (brief && hasBrief);
    };
    if (props.headTitle) heading.title = props.headTitle;
    else heading.removeAttribute("title");
    // Draw everything, measure, then leave out what does not fit whole.
    for (const row of rows) row.hidden = false;
    box.removeAttribute("data-compact");
    showHeading(false);
    const style = getComputedStyle(box);
    const limit = () => box.getBoundingClientRect().bottom - parseFloat(style.paddingBottom || "0") - parseFloat(style.borderBottomWidth || "0") + 0.5;
    const fits = (row: HTMLElement, to: number) => row.getBoundingClientRect().bottom <= to;
    // The height every row needs, from the last row's bottom edge (every row drawn), for the grid to give the card the free room below it.
    const needed = () =>
      Math.ceil(rows[rows.length - 1].getBoundingClientRect().bottom - box.getBoundingClientRect().top + parseFloat(style.paddingBottom || "0") + parseFloat(style.borderBottomWidth || "0") + 1);
    if (rows.every((row) => fits(row, limit()))) {
      box.dataset.need = String(needed());
      return void setMore(0);
    }
    // A clash card shows every meeting before it shows its long heading: each meeting on one line (its title; the time and place are in
    // the row's hover text, its name and the pane) under the short heading. The height this takes is what the grid may give the card from
    // the free room below it.
    if (props.tone === "clash") {
      box.setAttribute("data-compact", "");
      showHeading(true);
      box.dataset.need = String(needed());
      if (rows.every((row) => fits(row, limit()))) return void setMore(0);
    } else {
      box.dataset.need = String(needed());
    }
    // Still not whole where the card may not grow: the meetings that fit stay, and the rest are counted in "+N more".
    let shown = 0;
    while (shown < rows.length && fits(rows[shown], limit() - MORE_H)) shown += 1;
    rows.forEach((row, n) => (row.hidden = n >= shown));
    // With no room for even one row the button stands in the heading's place (a clash card keeps its heading: the reason is what it is for).
    heading.hidden = shown === 0 && props.tone === "overlap";
    if (button) button.hidden = false;
    setMore(rows.length - shown);
  }, [names, tick, props.tone, props.headTitle]);
  return (
    <div ref={card} className={`${styles.clash} ${props.tone === "overlap" ? styles.overlapCard : ""}`} role="group" aria-label={props.label} data-group-card="" data-tone={props.tone}>
      <p ref={head} className={styles.clashHead} title={props.headTitle}>
        <span className={styles.clashHeadPart}>{props.head}</span>
        {props.brief && (
          <span className={styles.clashHeadPart} data-head-brief="" hidden>
            {props.brief}
          </span>
        )}
      </p>
      <ul ref={list} className={styles.clashRows}>
        {props.items.map((e, k) => (
          <li key={`${entryKey(e, props.date)}:${k}`}>
            <GroupRow entry={e} date={props.date} calendars={props.calendars} selected={props.selected} onOpen={props.onOpen} />
          </li>
        ))}
      </ul>
      {more > 0 && (
        <button
          type="button"
          className={styles.groupMore}
          data-group-more={groupKey(props.date, props.startKey)}
          aria-label={tn("schedule.group.more", more, { time: props.time })}
          onClick={() => props.onMore({ date: props.date, time: props.time, start: props.startKey, keys: props.items.map((e) => entryKey(e, props.date)) })}
        >
          {t("schedule.group.more_short", { n: more })}
        </button>
      )}
    </div>
  );
}
