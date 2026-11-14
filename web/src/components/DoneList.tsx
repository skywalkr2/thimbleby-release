// The Done tab of To-dos (design 7.13): the to-dos finished in the last days, newest first, grouped by day, each saying who
// closed it (the person, or the assistant with the words it quoted) and offering "Not done after all", which reopens it. Where
// the person checks what the assistant closed on its own, and reverses it. It has no count and ends by saying where older ones are.
import { useId, useRef, useState } from "react";
import { useRowKeys } from "../lib/keys";
import type { ListChoice } from "../lib/list-choice";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { day, todayOn, addDays, sinceDay } from "../lib/dates";
import { onSide, useSideFilter } from "../lib/sides";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { plainTitle } from "../lib/title-dates";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { GroupLabel } from "../ui/GroupLabel";
import { Icon } from "../ui/Icon";
import { Row } from "../ui/Row";
import { RowList } from "../ui/RowList";
import { ProjectTag } from "./ProjectTag";
import { OriginLink } from "./Origin";
import { usePlaceText } from "../lib/place";
import styles from "./OpenItems.module.css";

export type DoneAction = S["DoneActionView"];

/** The rows by the day they were closed, newest day first; within a day the order they came in (newest first). */
export function byDay(rows: DoneAction[]): Array<{ day: string; rows: DoneAction[] }> {
  const days: Array<{ day: string; rows: DoneAction[] }> = [];
  for (const row of rows) {
    const last = days[days.length - 1];
    if (last && last.day === row.day) last.rows.push(row);
    else days.push({ day: row.day, rows: [row] });
  }
  return days;
}

export function DoneList(props: { rows: DoneAction[]; days: number; choice?: ListChoice }) {
  const { t, tn } = useWords();
  const side = useSideFilter();
  const today = todayOn(new Date());
  const rows = props.rows.filter((a) => onSide(a.side, side.picked, a.views, !!a.project_name));
  if (rows.length === 0) {
    return <EmptyState title={t("open.done.empty.title")} text={tn("open.done.empty", props.days)} />;
  }
  const label = (iso: string) => (iso === today ? t("open.done.today") : iso === addDays(today, -1) ? t("open.done.yesterday") : day(iso));
  return (
    <>
      <RowList aria-label={t("open.done.list")} data-done-list="">
        {byDay(rows).map((group) => (
          <DayRows key={group.day} label={label(group.day)} rows={group.rows} choice={props.choice} />
        ))}
      </RowList>
      <p className={`hint ${styles.older}`} data-done-older="">
        {t("open.done.older")}
      </p>
    </>
  );
}

function DayRows(props: { label: string; rows: DoneAction[]; choice?: ListChoice }) {
  const id = useId();
  return (
    <>
      <li className={styles.groupItem}>
        <GroupLabel id={id} as="h3" data-done-day="">
          {props.label}
        </GroupLabel>
      </li>
      {props.rows.map((a) => (
        <DoneRow key={a.id} action={a} choice={props.choice} />
      ))}
    </>
  );
}

type T = ReturnType<typeof useWords>["t"];

/** When the input arrived, as a phrase: "on Tue", or "today". The closing day stands in when the evidence names no input. */
function onDay(iso: string, t: T): string {
  const said = sinceDay(iso, new Date());
  return said ? t("open.done.on_day", { day: said }) : t("open.done.today_word");
}

/** What the app holds about the input the assistant read, as facts: who replied, which notice, the meeting, the person's note. */
function whyWords(a: DoneAction, t: T, has: (key: string) => boolean): string {
  const when = onDay(a.source_day ?? a.day, t);
  if (a.source_kind === "reply") return a.source_by ? t("open.done.why.reply", { who: a.source_by, when }) : t("open.done.why.reply_unknown", { when });
  if (a.source_kind === "notice" && a.notice && has(`open.done.notice.${a.notice}`)) return t("open.done.why.notice", { notice: t(`open.done.notice.${a.notice}`), when });
  if (a.source_kind === "calendar") return t("open.done.why.calendar");
  if (a.source_kind === "note") return t("open.done.why.note", { when });
  return when;
}

/** Who closed it, in words: "Done by you", "Done by Pat Sample", or "Closed by <the assistant's name> · <what it read>". Never a quote. */
function closedWords(a: DoneAction, t: T, has: (key: string) => boolean): string {
  if (a.closed_by === "assistant") return t("open.done.by_assistant_why", { why: whyWords(a, t, has) });
  return a.done_by.length > 0 ? t("open.done.by_others", { names: a.done_by.join(", ") }) : t("open.done.by_you");
}

/** The line over the quote when a row is opened: whose words they are and the day, in full. */
function fromWords(a: DoneAction, t: T): string {
  const date = a.source_day ? day(a.source_day) : day(a.day);
  if (a.source_kind === "reply") return a.source_by ? t("open.done.from.reply", { who: a.source_by, date }) : t("open.done.from.reply_unknown", { date });
  if (a.source_kind === "notice") return t("open.done.from.notice", { date });
  if (a.source_kind === "calendar") return t("open.done.from.calendar", { date });
  if (a.source_kind === "note") return t("open.done.from.note", { date });
  return t("open.done.from.other", { date });
}

function DoneRow(props: { action: DoneAction; choice?: ListChoice }) {
  const { t, has } = useWords();
  const act = useAct();
  const place = usePlaceText();
  const a = props.action;
  const ref = useRef<HTMLLIElement & HTMLDivElement>(null);
  useRowKeys(ref, { toggle: props.choice ? () => props.choice?.enter(a.id) : undefined });
  // The assistant's own close can be opened: the exact words it read, whose they are and a way to the message. Closed, a row holds none of them.
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const reopen = () =>
    void act(
      () => api.actionStatus(a.id, "open"),
      () => ({ message: t("toast.action_reopened_named", { text: plainTitle(a.text) }), undo: () => api.actionStatus(a.id, "done") }),
      undefined,
      { fail: { id: a.id, what: plainTitle(a.text) } },
    );
  const placed = place({ name: a.project_name, side: a.side_name }) ? <ProjectTag name={a.project_name} side={a.side_name} /> : null;
  const opens = a.closed_by === "assistant" && !!a.reason;
  return (
    <Row
      ref={ref}
      {...props.choice?.rowProps(a.id)}
      data-done-item=""
      failedId={a.id}
      clamp={plainTitle(a.text)}
      phoneClamp
      lead={<Icon name="check" size={18} />}
      title={
        <a
          href={viewHref(recordView("action", a.id))}
          onClick={(e) => {
            // Beside the list the title shows the to-do in the pane; a new-tab or modified click still goes to the page.
            if (!props.choice || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            e.preventDefault();
            props.choice.choose(a.id);
          }}
        >
          {plainTitle(a.text)}
        </a>
      }
      meta={
        <>
          <span data-closed-by={a.closed_by}>{closedWords(a, t, has)}</span>
          {placed && <> · {placed}</>}
          {opens && (
            <>
              {" · "}
              <Button variant="quiet" size="sm" aria-expanded={open} aria-controls={bodyId} data-done-why="" onClick={() => setOpen(!open)}>
                {t(open ? "open.done.why_close" : "open.done.why_open")}
              </Button>
            </>
          )}
        </>
      }
      primary={
        <Button variant="secondary" aria-label={t("open.done.reopen_named", { text: plainTitle(a.text) })} onClick={reopen}>
          {t("open.done.reopen")}
        </Button>
      }
    >
      {opens && open && (
        <div id={bodyId} className={styles.why} data-done-quote="">
          <p className={styles.quote}>{`“${a.reason}”`}</p>
          <p className="hint">{fromWords(a, t)}</p>
          <OriginLink origin={a.origin} label={t("open.done.open_message")} />
        </div>
      )}
    </Row>
  );
}
