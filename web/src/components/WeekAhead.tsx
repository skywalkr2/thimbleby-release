// The week ahead (design 6.32): the assistant's reading of the coming week as one card, a sentence on the week and one row
// for each thing that happens in it, each with its day or window, its words and a link to its source. It sits at the top of the
// Schedule's Week and Work week views and in the Monday briefing. With no reading the rows are built by rules and there is no
// sentence. "Not this week" leaves a row out, with Undo; "Read the week again" asks for a new reading.
import { useQuery } from "@tanstack/react-query";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { shortDay } from "../lib/dates";
import { useMoney } from "../lib/money";
import { shortTitle } from "../lib/title-dates";
import { onSide, useSideFilter } from "../lib/sides";
import { eventPageView, recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import styles from "./WeekAhead.module.css";

type Row = S["WeekAheadRowView"];

/** Where a row's source opens: the page of the record it comes from. */
export function rowHref(row: Row): string {
  const { kind, id } = row.link;
  return viewHref(kind === "snapshot" ? eventPageView(id, row.from_day) : recordView(kind, id));
}

/** `leaveOutAgenda`: on Today, a row whose record Today's agenda already lists is left out, so the card is never a copy of Today. */
export function WeekAhead(props: { headingLevel?: 2 | 3; leaveOutAgenda?: boolean }) {
  const { t } = useWords();
  const act = useAct();
  const money = useMoney();
  const filter = useSideFilter();
  const week = useQuery({ queryKey: ["week-ahead"], queryFn: api.weekAhead });
  const agenda = useQuery({ queryKey: ["today", "agenda"], queryFn: api.agenda, enabled: !!props.leaveOutAgenda });
  const data = week.data;
  const Head = props.headingLevel === 3 ? "h3" : "h2";
  if (week.isError) return <p className="hint" data-week-ahead="failed">{t("week_ahead.load_failed")}</p>;
  if (!data) return null;
  // Wait for the agenda before drawing, so a row that is left out never shows for a moment; with no agenda to read, the card is whole.
  if (props.leaveOutAgenda && agenda.isPending) return null;
  const listed = new Set(props.leaveOutAgenda ? (agenda.data ?? []).map((a) => a.snapshot) : []);
  // Under a side's filter the card shows that side's rows and those on no side (saying so), and no sentence: it reads the whole week.
  const filtered = filter.choice !== "all";
  const onToday = data.rows.filter((row) => onSide(row.side, filter.choice));
  const rows = onToday.filter((row) => !listed.has(row.link.id));
  const leftOut = rows.length < onToday.length;
  const when = (row: Row) => (row.to_day && row.to_day !== row.from_day ? t("week_ahead.when.window", { start: shortDay(row.from_day), end: shortDay(row.to_day) }) : shortDay(row.from_day));
  // A row's words as Today shows a to-do's: a day written out as year-month-day reads as a day.
  const wordsOf = (row: Row) => shortTitle(row.words, row.from_day);
  const status =
    data.state === "working" ? t("week_ahead.reading") : data.state === "needs_go" ? (data.estimate_usd != null ? t("week_ahead.needs_go_cost", { cost: money(data.estimate_usd) }) : t("week_ahead.needs_go")) : null;
  return (
    <section className={styles.card} aria-labelledby="week-ahead-title" data-week-ahead={data.state}>
      <div className={styles.head}>
        <Head id="week-ahead-title" className={styles.title}>
          {t("week_ahead.title")}
        </Head>
        <Button size="sm" variant="secondary" disabled={!data.read_again} onClick={() => void act(() => api.readWeekAhead())} data-week-ahead-again="">
          {t("week_ahead.read_again")}
        </Button>
      </div>
      {status && <p className="hint" data-week-ahead-status="">{status}</p>}
      {data.sentence && !filtered && !leftOut && <p className={styles.sentence} data-week-ahead-sentence="">{data.sentence}</p>}
      {rows.length === 0 ? (
        (data.state === "empty" || ((filtered || leftOut) && data.rows.length > 0)) && <p className={styles.quiet}>{t("week_ahead.empty")}</p>
      ) : (
        <ul className={styles.rows}>
          {rows.map((row) => (
            <li key={row.link.id} className={styles.row} data-week-ahead-row={row.link.id}>
              <span className={styles.when}>{when(row)}</span>
              <span className={styles.words}>
                <a href={rowHref(row)} aria-label={t("week_ahead.open", { words: wordsOf(row) })}>{wordsOf(row)}</a>
                <span className={styles.kind}>{t(`week_ahead.kind.${row.kind}`)}</span>
                {filtered && !row.side && <span className={styles.kind} data-every-side="">{t("queue.every_side")}</span>}
              </span>
              <Button
                size="sm"
                variant="quiet"
                onClick={() =>
                  void act(
                    () => api.setAsideWeekAhead(row.link.id),
                    (kept) => ({ message: t("week_ahead.left_out"), undo: () => api.restoreWeekAhead(kept.previous) }),
                  )
                }
              >
                {t("week_ahead.not_this_week")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
