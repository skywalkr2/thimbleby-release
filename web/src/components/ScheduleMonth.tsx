// The Month view (design 7.7): six weeks of days, each listing its first entries by time and saying how many more there are;
// the day and "N more" open that day in Day view. In a narrow space a day keeps only its count and a row of dots, so nothing
// is wider than the window. Today is named in words for a screen reader, never only by color.
import { useState } from "react";
import { dayOfMonth, day, weekday } from "../lib/dates";
import { Icon } from "../ui/Icon";
import { clashesOf, foldIdentical } from "../lib/calendar";
import { entryFoldKey } from "../lib/entry-fold";
import { useWords } from "../lib/wording";
import type { DayEntries } from "./ScheduleGrid";
import { EntryButton, entryKey, type Calendars, type Entry } from "./ScheduleEntry";
import styles from "./Schedule.module.css";

/** What makes two days' all-day entries the same one. */
const runId = (e: Entry) => `${e.kind}|${e.snapshot}|${e.title}`;

/** The most dots a day shows in a narrow space. */
const DOTS = 4;

export function MonthGrid(props: {
  days: DayEntries[];
  today: string;
  /** The month being looked at (a day in it): days outside it are dimmed. */
  month: string;
  limit: number;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
  onOpenDay: (date: string) => void;
  /** On a phone a day's button chooses it and its entries are listed under the month, instead of opening Day view. */
  listBelow?: boolean;
}) {
  const { t, tn } = useWords();
  const [chosen, setChosen] = useState<string | null>(null);
  const chosenDay = props.listBelow ? props.days.find((d) => d.date === (chosen ?? props.today)) : undefined;
  const inMonth = (date: string) => date.slice(0, 7) === props.month.slice(0, 7);
  // An all-day entry that runs over several days is one bar across them: a day's entry joins the day before it and the day after it
  // in the same week row, when they hold the same entry.
  const allDayIds = props.days.map((d) => new Set(d.all_day.map(runId)));
  const joins = (e: Entry, at: number) => ({ from: e.slot === "all_day" && at % 7 > 0 && allDayIds[at - 1]?.has(runId(e)), to: e.slot === "all_day" && at % 7 < 6 && allDayIds[at + 1]?.has(runId(e)) });
  return (
    <>
    <div className={styles.month} data-month="">
      <div className={styles.weekdays} aria-hidden="true">
        {props.days.slice(0, 7).map((d) => (
          <span key={d.date}>
            <span className={styles.weekdayName}>{weekday(d.date)}</span>
          </span>
        ))}
      </div>
      <div className={styles.cells}>
        {props.days.map((d, at) => {
          // Identical all-day entries of a day (one sent message held by several mailboxes makes several due dates that are the same
          // to-do) are one with a count, as the week's strip folds them: the same rule, written once (`foldIdentical`).
          const strip = foldIdentical(d.all_day, entryFoldKey);
          const counted = new Map(strip.map((f) => [f.item, f.count]));
          const all = [...strip.map((f) => f.item), ...d.timed];
          const listed = all.slice(0, props.limit);
          const more = all.length - listed.length;
          const label = d.date === props.today ? t("schedule.day_today", { date: day(d.date) }) : day(d.date);
          return (
            <section key={d.date} className={styles.cell} aria-label={label} data-day={d.date} data-today={d.date === props.today ? "" : undefined} data-outside={inMonth(d.date) ? undefined : ""}>
              <button type="button" className={styles.dayButton} onClick={() => (props.listBelow ? setChosen(d.date) : props.onOpenDay(d.date))} aria-pressed={props.listBelow ? chosenDay?.date === d.date : undefined}>
                <span className={styles.dayNumber} aria-hidden="true">
                  {dayOfMonth(d.date)}
                </span>
                {d.clashes.length > 0 && (
                  <span className={styles.clashMark} data-clash-mark="" title={t("schedule.month.clash")}>
                    <Icon name="alert" size={14} />
                    <span className={styles.clashMarkText} aria-hidden="true">{tn("schedule.month.clash_count", clashesOf(d.clashes).length)}</span>
                    <span className={styles.clashMarkNum} aria-hidden="true">{clashesOf(d.clashes).length}</span>
                    <span className="sr">{tn("schedule.month.clash_sr", clashesOf(d.clashes).length)}</span>
                  </span>
                )}
                {all.length > 0 && (
                  <span className={styles.count} aria-hidden="true">
                    {all.length}
                  </span>
                )}
                <span className="sr">{tn("schedule.month.day", all.length, { date: label })}</span>
                {all.length > 0 && (
                  <span className={styles.dots} aria-hidden="true">
                    {all.slice(0, DOTS).map((e, i) => (
                      <span key={i} className={styles.dot} data-color={e.own || e.kind === "due" ? undefined : props.calendars.color(e.source)} data-own={e.own || e.kind === "due" ? "" : undefined} />
                    ))}
                  </span>
                )}
              </button>
              <ul className={styles.titles}>
                {listed.map((e, i) => (
                  <li key={`${entryKey(e, d.date)}:${i}`}>
                    <EntryButton entry={e} date={d.date} calendars={props.calendars} time count={counted.get(e)} join={joins(e, at)} selected={props.selected === entryKey(e, d.date)} onOpen={props.onOpen} t={t} />
                  </li>
                ))}
                {more > 0 && (
                  <li>
                    <button type="button" className={styles.more} onClick={() => props.onOpenDay(d.date)}>
                      {tn("schedule.more", more)}
                    </button>
                  </li>
                )}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
    {chosenDay && (
      <section className={styles.dayList} aria-label={t("schedule.month.list", { date: day(chosenDay.date) })} data-month-day-list="">
        <h3 className={styles.caption}>{t("schedule.month.list", { date: day(chosenDay.date) })}</h3>
        {[...chosenDay.all_day, ...chosenDay.timed].length === 0 ? (
          <p className="hint">{t("schedule.month.list_empty")}</p>
        ) : (
          <ul className={styles.waitList}>
            {[...chosenDay.all_day, ...chosenDay.timed].map((e, i) => (
              <li key={`${entryKey(e, chosenDay.date)}:${i}`}>
                <EntryButton entry={e} date={chosenDay.date} calendars={props.calendars} time selected={props.selected === entryKey(e, chosenDay.date)} onOpen={props.onOpen} t={t} />
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="link-button" onClick={() => props.onOpenDay(chosenDay.date)}>
          {t("schedule.month.open_day")}
        </button>
      </section>
    )}
    </>
  );
}
