// "Needs a date" (design 7.5): the open to-dos with no date that the person owns or has told someone about, at the top of
// the to-dos, each with a date picker. Picking a day sets the to-do's date as the person's own change, at once, with Undo; it
// drops the words an old date was read from and leaves the group on its own. Nothing here guesses a date.
import { useRef, useState } from "react";
import { api } from "../lib/api";
import { useAct } from "../lib/act";
import { day } from "../lib/dates";
import type { OpenAction } from "../lib/open-items";
import { shortTitle } from "../lib/title-dates";
import { viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Button, ButtonLink } from "../ui/Button";
import { DateField } from "../ui/DateField";
import { Icon } from "../ui/Icon";
import { GroupLabel } from "../ui/GroupLabel";
import { RowList } from "../ui/RowList";
import { ActionRow } from "./OpenItems";
import styles from "./OpenItems.module.css";

/** A day typed or picked in full: four digits for the year, so a year half typed is never saved. */
const FULL_DAY = /^(19|2\d)\d\d-\d\d-\d\d$/;

/** How many rows the card shows before "Show N more". */
export const NEEDS_DATE_SHOWN = 5;

/** A date field with its Set button beside it. A day picked or typed only fills the field; Set (or Enter in the field) saves it,
 * so a card left alone, or touched by accident, sets nothing. The field's name is `label`, never a visible label. */
function DayAndSet(props: { id: string; label: string; setLabel: string; onSet: (day: string) => void }) {
  const { t } = useWords();
  const [picked, setPicked] = useState("");
  // What the field holds right now, so Enter sees a day the field has just read from words ("tomorrow") in the same key press.
  const latest = useRef("");
  const whole = FULL_DAY.test(picked);
  const save = () => {
    if (FULL_DAY.test(latest.current)) props.onSet(latest.current);
  };
  // Words the box cannot read itself ("next Tuesday") are read by the same reader the add box uses; Enter waits for that answer.
  const pending = useRef<Promise<unknown> | null>(null);
  const readWords = (text: string) => {
    const read = api
      .checkTodoDay({ words: text })
      .then((view) => (view.status === "ok" && view.day ? view.day : null))
      .catch(() => null);
    pending.current = read;
    void read.finally(() => {
      if (pending.current === read) pending.current = null;
    });
    return read;
  };
  return (
    <div
      className={styles.pick}
      onKeyDown={(e) => {
        // Enter in the text box only; a calendar's own Enter chooses a day and is not a save.
        if (e.key === "Enter" && e.target instanceof HTMLInputElement) {
          const waiting = pending.current;
          if (waiting) void waiting.then(save);
          else save();
        }
      }}
    >
      <DateField
        id={props.id}
        aria-label={props.label}
        placeholder={t("open.needs_date.placeholder")}
        readWords={readWords}
        value={picked}
        onChange={(e) => {
          latest.current = e.target.value;
          setPicked(e.target.value);
        }}
      />
      <Button className={styles.setBtn} aria-disabled={!whole} onClick={save}>
        {props.setLabel}
      </Button>
    </div>
  );
}

/** `hint` names the wording of the note under the group (its `.one` and `.other` forms), for a screen where the dated to-do goes
 * somewhere other than the list below. */
export function NeedsADate(props: { rows: OpenAction[]; first?: boolean; hint?: string; headless?: boolean }) {
  const { t, tn } = useWords();
  const act = useAct();
  const [expanded, setExpanded] = useState(false);
  const [bulk, setBulk] = useState(false);
  if (props.rows.length === 0) return null;
  const shown = expanded ? props.rows : props.rows.slice(0, NEEDS_DATE_SHOWN);
  const hidden = props.rows.length - shown.length;
  const edit = (row: OpenAction, picked: string) => api.editRecord({ kind: "action", id: row.id, fields: { due: picked, due_words: null, due_check: false }, read_version: row.version });
  const setDay = (row: OpenAction, picked: string) => {
    if (!FULL_DAY.test(picked)) return;
    void act(
      () => edit(row, picked),
      (result) => ({
        message: t("open.needs_date.saved", { text: shortTitle(row.text), date: day(picked) }),
        undo: () => api.undo(result.changeset),
      }),
      undefined,
      { once: `needs-date:${row.id}` },
    );
  };
  // One day for every to-do in the card, as one act with one Undo.
  const setEvery = (picked: string) => {
    if (!FULL_DAY.test(picked)) return;
    void act(
      async () => {
        const changesets: string[] = [];
        for (const row of props.rows) changesets.push((await edit(row, picked)).changeset);
        return changesets;
      },
      (changesets) => ({
        message: t("open.needs_date.saved_all", { n: String(changesets.length), date: day(picked) }),
        undo: async () => {
          for (const changeset of changesets) await api.undo(changeset);
        },
      }),
      undefined,
      { once: "needs-date:all" },
    );
    setBulk(false);
  };
  return (
    <section
      className={styles.needs}
      aria-labelledby={props.headless ? undefined : "needs-date-title"}
      aria-label={props.headless ? t("open.needs_date.title") : undefined}
      data-needs-date=""
    >
      {!props.headless && (
        <>
          <GroupLabel as="h2" id="needs-date-title" count={props.rows.length} className={styles.needsHead}>
            {t("open.needs_date.title")}
          </GroupLabel>
          <p className="hint">{tn(props.hint ?? "open.needs_date.hint", props.rows.length)}</p>
        </>
      )}
      {/* The same row as every other to-do (circle, title, meta, menu), with the date picker as its one primary. */}
      <RowList aria-label={t("open.needs_date.list")} data-needs-rows="">
        {shown.map((a) => (
          <ActionRow
            key={a.id}
            action={a}
            inlineOrigin
            data-needs-row=""
            primary={<DayAndSet id={`needs-date-${a.id}`} label={t("open.needs_date.pick", { text: shortTitle(a.text) })} setLabel={t("open.needs_date.set")} onSet={(d) => setDay(a, d)} />}
          />
        ))}
      </RowList>
      {(hidden > 0 || props.rows.length > 1) && (
        <div className={styles.needsFoot}>
          {hidden > 0 && (
            <Button variant="quiet" size="sm" data-show-more="needs-date" onClick={() => setExpanded(true)}>
              {tn("open.show_more", hidden)}
            </Button>
          )}
          {props.rows.length > 1 &&
            (bulk ? (
              <DayAndSet id="needs-date-all" label={t("open.needs_date.all_label", { n: String(props.rows.length) })} setLabel={t("open.needs_date.set_all")} onSet={setEvery} />
            ) : (
              <Button variant="quiet" size="sm" onClick={() => setBulk(true)}>
                {t("open.needs_date.all")}
              </Button>
            ))}
        </div>
      )}
    </section>
  );
}

/** Where "Needs a date" is only counted: a line that says how many to-dos have no date and links to the one place they are listed
 * in full, To-dos, where each has its date picker. Nothing at all with none. */
export function NeedsADateLink(props: { rows: OpenAction[]; note: string }) {
  const { t, tn } = useWords();
  if (props.rows.length === 0) return null;
  return (
    <p className="hint" data-needs-date-link="">
      {tn(props.note, props.rows.length)}{" "}
      <ButtonLink variant="quiet" size="sm" href={viewHref("work/open")}>
        {t("schedule.timeline.needs_open")}
      </ButtonLink>
    </p>
  );
}

/** The to-dos that need a date, listed at the foot of the list under one line that counts them ("2 to-dos need a date"), each with
 * its date picker beside it, never behind a button. Nothing at all with none. */
export function NeedsADateLine(props: { rows: OpenAction[] }) {
  const { tn } = useWords();
  if (props.rows.length === 0) return null;
  return (
    <li className={styles.needsLine} data-needs-date-line="">
      <div className={styles.needsLineRow}>
        <Icon name="calendar" size={16} />
        <span>{tn("open.needs_date.line", props.rows.length)}</span>
      </div>
      <NeedsADate rows={props.rows} headless />
    </li>
  );
}
