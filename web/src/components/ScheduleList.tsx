// The week as a list by day (design 7.7), for a phone: a heading for each day, then its entries in order, each a row with the
// calendar's mark, its title and, under it, when it is, where and which calendar it is in ("In 2 calendars" for one held in
// several). Meetings that overlap are one row naming them, with how long they overlap. A day with nothing says so. Every row
// opens the entry's details, as a block of the grid does.
import { foldIdentical, minutesOf, SHORT } from "../lib/calendar";
import { dayLong, wallTime, weekdayLong } from "../lib/dates";
import { useWords } from "../lib/wording";
import { GroupLabel } from "../ui/GroupLabel";
import { Icon } from "../ui/Icon";
import { MarkDot, type CalendarColor } from "../ui/MarkDot";
import { SideMark } from "../ui/SideMark";
import { calendarWords, entryKey, entryTitle, type Calendars, type Entry } from "./ScheduleEntry";
import { clashCards, clashName, clashReason, type DayEntries } from "./ScheduleGrid";
import styles from "./Schedule.module.css";

type T = ReturnType<typeof useWords>["t"];

/** When an entry is, for its row: "All day", its start to its end, or its start. */
function rangeWords(entry: Entry, t: T): string {
  if (entry.slot === "all_day") return t("schedule.all_day");
  if (entry.begins && entry.ends) return t("schedule.list.range", { start: wallTime(entry.begins), end: wallTime(entry.ends) });
  if (entry.begins) return wallTime(entry.begins);
  return entry.ends ? t("today.agenda.until", { time: wallTime(entry.ends) }) : "";
}

type Row = { type: "entry"; entry: Entry; at: number; count?: number } | { type: "clash"; entries: Entry[]; heading: string; name: string; at: number };

export function ScheduleList(props: {
  days: DayEntries[];
  today: string;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
}) {
  const { t, tn } = useWords();
  const slotOf = (side: string | null | undefined) => props.calendars.side?.(side)?.slot ?? null;
  // With several sides a row's mark and its words say its side (never an account's address); with one, its calendar.
  const colorOf = (entry: Entry): CalendarColor | null => (props.calendars.bySide || entry.own || entry.kind === "due" ? null : ((props.calendars.color(entry.source) as CalendarColor | undefined) ?? null));
  // An entry of a calendar that needs signing in again says it may be out of date, as the grid's entries do.
  const stale = (entry: Entry) => !entry.own && entry.kind !== "due" && !!props.calendars.stale?.(entry.source);
  const open = (entry: Entry, date: string, count = 1) => (
    <button
      type="button"
      className={styles.listButton}
      data-entry-key={entryKey(entry, date)}
      data-kind={entry.kind}
      data-selected={props.selected === entryKey(entry, date) ? "" : undefined}
      data-stale={stale(entry) ? "" : undefined}
      onClick={() => props.onOpen(entry, date)}
    >
      <span className={styles.listLead} aria-hidden="true">
        {slotOf(entry.side) !== null ? <MarkDot kind="side" slot={slotOf(entry.side) as number} /> : <MarkDot kind="calendar" color={colorOf(entry)} />}
      </span>
      <span className={styles.listMain}>
        <span className={entry.cancelled ? `${styles.listTitle} ${styles.struck}` : styles.listTitle}>
          {entryTitle(entry, t)}
          {count > 1 && (
            <>
              {" "}
              <span className={styles.times} aria-hidden="true">
                {t("schedule.times", { n: count })}
              </span>
              <span className="sr">, {t("schedule.times_sr", { n: count })}</span>
            </>
          )}
        </span>
        <span className={styles.listMeta}>
          <span>{[rangeWords(entry, t), entry.where ?? "", slotOf(entry.side) !== null ? "" : calendarWords(entry, props.calendars, t)].filter(Boolean).join(" · ")}</span>
          {slotOf(entry.side) !== null && <SideMark side={entry.side} />}
          {stale(entry) && <span className={styles.staleNote} data-stale-note="">{t("schedule.entry.stale_short")}</span>}
        </span>
      </span>
    </button>
  );
  // Each day's rows in order, a clash being one row; days with nothing on them are not rows, they are one line at the end.
  const days = props.days.map((d) => {
    const spans = d.timed.map((e) => {
      const start = minutesOf(e.begins) ?? 0;
      return { item: e, start, end: Math.max(minutesOf(e.ends) ?? start + SHORT, start + 1) };
    });
    const clashes = clashCards(d, spans);
    const clashing = new Set(clashes.flatMap((c) => c.items));
    const rows: Row[] = [
      ...foldIdentical(d.all_day, (e) => [e.kind, e.title, e.own, e.source, e.cancelled].join("|")).map(({ item, count }): Row => ({ type: "entry", entry: item, at: -1, count })),
      ...spans.filter((s) => !clashing.has(s.item)).map((s): Row => ({ type: "entry", entry: s.item, at: s.start })),
      ...clashes.map((c): Row => ({ type: "clash", entries: c.items, heading: clashReason(c, t), name: clashName(c, t, tn), at: c.start })),
    ].sort((a, b) => a.at - b.at);
    const heading = t(d.date === props.today ? "schedule.list.day_today" : "schedule.list.day", { date: dayLong(d.date) });
    return { d, rows, heading };
  });
  const quiet = days.filter((x) => x.rows.length === 0).map((x) => weekdayLong(x.d.date));
  return (
    <div className={styles.list} data-schedule-list="" role="list" aria-label={t("schedule.list.label")}>
      {days.filter((x) => x.rows.length > 0).map(({ d, rows, heading }) => {
        return (
          <section key={d.date} className={styles.listDay} aria-label={heading} role="listitem" data-day={d.date} data-today={d.date === props.today ? "" : undefined}>
            <GroupLabel>{heading}</GroupLabel>
              <ul className={styles.listRows}>
                {rows.map((row, n) =>
                  row.type === "entry" ? (
                    <li key={`${entryKey(row.entry, d.date)}:${n}`} className={styles.listRow}>
                      {open(row.entry, d.date, row.count)}
                    </li>
                  ) : (
                    <li key={`clash:${row.at}:${n}`} className={`${styles.listRow} ${styles.listClash}`} data-clash="">
                      <div role="group" aria-label={row.name}>
                        <p className={styles.listClashHead}>
                          <Icon name="alert" size={16} />
                          <span>{row.heading}</span>
                        </p>
                        <ul className={styles.listRows}>
                          {row.entries.map((entry, k) => (
                            <li key={`${entryKey(entry, d.date)}:${k}`}>{open(entry, d.date)}</li>
                          ))}
                        </ul>
                      </div>
                    </li>
                  ),
                )}
              </ul>
          </section>
        );
      })}
      {quiet.length > 0 && (
        <p className={styles.listNone} role="listitem" data-nothing-on="">
          {t("schedule.list.nothing", { day: quiet.join(", ") })}
        </p>
      )}
    </div>
  );
}
