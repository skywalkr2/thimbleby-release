// One day's all-day band on the time grid (design 7.7): the entries as whole rows in the band's height, never a row cut part-way. What
// does not fit whole is left out and counted in a "+N more" button that opens the day's all-day entries in the side pane, the way a
// clash card's "+N more" opens its meetings.
import { useLayoutEffect, useRef, useState } from "react";
import { useWords } from "../lib/wording";
import { EntryButton, entryKey, type Calendars, type Entry } from "./ScheduleEntry";
import type { GroupRef } from "./ScheduleGroupCard";
import styles from "./Schedule.module.css";

/** The room the "+N more" row takes under the last row, in px. */
const MORE_H = 28;

/** The `start` that names an all-day group for the pane (with the day), beside the timed groups' minutes. */
export const ALL_DAY_START = "all-day";

export function AllDayStrip(props: {
  date: string;
  label: string;
  today: boolean;
  items: Array<{ item: Entry; count: number }>;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
  onMore: (group: GroupRef) => void;
}) {
  const { t } = useWords();
  const box = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState(0);
  const [tick, setTick] = useState(0);
  const names = props.items.map((i) => entryKey(i.item, props.date)).join("|");
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver !== "function") return;
    const watch = new ResizeObserver(() => setTick((n) => n + 1));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const rows = Array.from(el.querySelectorAll<HTMLElement>(":scope > [data-strip-row]"));
    const button = el.querySelector<HTMLElement>(":scope > [data-strip-more]");
    if (button) button.hidden = true;
    for (const row of rows) row.hidden = false;
    const style = getComputedStyle(el);
    const limit = () => el.getBoundingClientRect().top + el.clientHeight - parseFloat(style.paddingBottom || "0") + 0.5;
    const fits = (row: HTMLElement, to: number) => row.getBoundingClientRect().bottom <= to;
    if (rows.every((row) => fits(row, limit()))) return void setMore(0);
    let shown = 0;
    while (shown < rows.length && fits(rows[shown], limit() - MORE_H)) shown += 1;
    rows.forEach((row, n) => (row.hidden = n >= shown));
    if (button) button.hidden = false;
    setMore(rows.length - shown);
  }, [names, tick]);
  return (
    <ul ref={box} className={styles.strip} data-strip="" aria-label={props.label} data-today={props.today ? "" : undefined}>
      {props.items.map(({ item: e, count }, n) => (
        <li key={`${entryKey(e, props.date)}:${n}`} data-strip-row="">
          <EntryButton entry={e} date={props.date} calendars={props.calendars} time={false} count={count} selected={props.selected === entryKey(e, props.date)} onOpen={props.onOpen} t={t} />
        </li>
      ))}
      {more > 0 && (
        <li data-strip-more="">
          <button
            type="button"
            className={styles.groupMore}
            data-group-more={`${props.date}|${ALL_DAY_START}`}
            aria-label={t("schedule.all_day_more", { n: more })}
            onClick={() => props.onMore({ date: props.date, time: t("schedule.all_day"), start: ALL_DAY_START, allDay: true, keys: props.items.map((i) => entryKey(i.item, props.date)) })}
          >
            {t("schedule.group.more_short", { n: more })}
          </button>
        </li>
      )}
    </ul>
  );
}
