// The week as a list (design 7.7), drawn in place of the time grid when no meeting has a time in the days shown: a row for each
// day with its all-day entries, the to-dos due that day, the projects' target days and, when nobody works that day, why. The
// to-dos past due that no day shown holds are stacked under today's row. A week with no meeting says so once, above the rows.
import type { S } from "../lib/api";
import { foldIdentical } from "../lib/calendar";
import { dayOfMonth, weekday } from "../lib/dates";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { EntryButton, entryKey, type Calendars, type Entry } from "./ScheduleEntry";
import { offWords, type DayEntries } from "./ScheduleGrid";
import styles from "./Schedule.module.css";

type Target = S["ScheduleTargetView"];

export function ScheduleAgenda(props: {
  days: DayEntries[];
  today: string;
  /** The days nobody works, by day, with the reason. */
  off: ReadonlyMap<string, string>;
  /** The projects' target days in the days shown, the side filter already applied. */
  targets: Target[];
  /** The keys of the entries that are overdue from before the days shown; they are stacked under today's row. */
  overdueKeys: ReadonlySet<string>;
  /** The page's own summary line already says "No meetings" (nothing at all is in the days shown): the list does not say it again. */
  summaryHasIt?: boolean;
  calendars: Calendars;
  selected: string | null;
  onOpen: (entry: Entry, date: string | null) => void;
}) {
  const { t } = useWords();
  return (
    <div data-agenda="">
      {!props.summaryHasIt && (
        <p className={styles.none} data-agenda-no-meetings="">
          {t("schedule.agenda.no_meetings")}
        </p>
      )}
      <ol className={styles.agenda} aria-label={t("schedule.agenda.region")}>
        {props.days.map((d) => {
          const entries = [...d.all_day, ...d.timed];
          const late = entries.filter((e) => props.overdueKeys.has(entryKey(e, d.date)));
          const here = entries.filter((e) => !late.includes(e));
          const targets = props.targets.filter((x) => x.day === d.date);
          const reason = props.off.get(d.date);
          const isToday = d.date === props.today;
          const empty = entries.length === 0 && targets.length === 0 && reason === undefined;
          // The same thing said several times (a holiday held by every calendar) is one row with how many.
          const rows = (list: Entry[]) =>
            foldIdentical(list, (e) => [e.kind, e.title, e.own, e.cancelled].join("|")).map(({ item: e, count }, n) => (
              <li key={`${entryKey(e, d.date)}:${n}`}>
                <EntryButton entry={e} date={d.date} calendars={props.calendars} time={false} count={count} selected={props.selected === entryKey(e, d.date)} onOpen={props.onOpen} t={t} />
              </li>
            ));
          return (
            <li key={d.date} className={styles.agendaDay} data-day={d.date} data-today={isToday ? "" : undefined} data-off={reason !== undefined ? "" : undefined}>
              <h3 className={styles.agendaHead}>{isToday ? t("schedule.day_today", { date: `${weekday(d.date)} ${dayOfMonth(d.date)}` }) : `${weekday(d.date)} ${dayOfMonth(d.date)}`}</h3>
              <div className={styles.agendaBody}>
                {reason !== undefined && (
                  <p className={styles.agendaNote} data-day-off="">
                    {offWords(reason, t)}
                  </p>
                )}
                {late.length > 0 && (
                  <>
                    <p className={styles.agendaSub} data-agenda-overdue="">
                      {t("schedule.agenda.overdue")}
                    </p>
                    <ul>{rows(late)}</ul>
                  </>
                )}
                {(here.length > 0 || targets.length > 0) && (
                  <ul>
                    {rows(here)}
                    {targets.map((x) => (
                      <li key={`target:${x.project}`} data-agenda-target={x.project}>
                        <a href={viewHref(recordView("project", x.project))}>{t("schedule.agenda.target", { name: x.name })}</a>
                      </li>
                    ))}
                  </ul>
                )}
                {empty && <p className={styles.agendaNote}>{t("schedule.agenda.nothing")}</p>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
