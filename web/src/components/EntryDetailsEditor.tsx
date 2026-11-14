// An entry's and a note's "Edit details" (design 7.5), one editor like the to-do's: a drawer from the right with the words a person
// uses for each part (what, the day, when it starts and ends, where, which side or project, their part in it), never the record's own
// fields with their stored names and values. Cancel and Save are pinned at its foot; a save sends only what changed, as the person's
// own edit with Undo. A refusal because it changed since the editor opened keeps what was typed and says so.
import { useId, useState } from "react";
import { ApiError, api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { addDays } from "../lib/dates";
import { useSides } from "../lib/sides";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { DateField } from "../ui/DateField";
import { Drawer } from "../ui/Drawer";
import { FormField } from "../ui/FormField";
import { Select } from "../ui/Select";
import { ProjectPicker } from "./ProjectPicker";

type Role = "attend" | "run" | "brief_only";
type Record_ = S["GenericRecordView"];

const text = (value: unknown): string => (typeof value === "string" ? value : "");
/** The day and the time of day a stored start or end reads as ("2026-11-11T18:30:00" is Nov 11 at 18:30); a bare day has no time. */
export const splitMoment = (value: unknown): { day: string; time: string } => {
  const stored = text(value);
  return { day: stored.slice(0, 10), time: stored.length > 10 ? stored.slice(11, 16) : "" };
};
/** A stored start or end from a day and a time of day: the day alone is an all-day entry. */
export const joinMoment = (day: string, time: string): string => (time ? `${day}T${time}:00` : day);

function useSave(record: Record_, onClose: () => void) {
  const { t } = useWords();
  const act = useAct();
  const [stale, setStale] = useState(false);
  const save = async (fields: Record<string, unknown>, said: string) => {
    if (Object.keys(fields).length === 0) return;
    const done = await act(
      () => api.editRecord({ kind: record.kind, id: record.id, fields, read_version: record.version }),
      (result) => ({ message: said, undo: () => api.undo(result.changeset) }),
      (err) => {
        // Changed since the editor opened: what was typed stays, and the editor says why nothing was saved.
        if (err instanceof ApiError && err.status === 409) setStale(true);
        else throw err;
      },
    );
    if (done) onClose();
  };
  return { save, stale, note: stale ? <p className="problem-note" role="alert">{t("record.edit_stale")}</p> : null };
}

/** The editor of a calendar entry the app keeps itself. */
export function EntryEditor(props: { record: Record_; onClose: () => void }) {
  const { t } = useWords();
  const { justMe } = useSides();
  const id = useId();
  const f = props.record.fields;
  const first = splitMoment(f.start);
  const last = splitMoment(f.end);
  const [title, setTitle] = useState(text(f.title));
  const [on, setOn] = useState(first.day);
  const [at, setAt] = useState(first.time);
  const [until, setUntil] = useState(last.time);
  const [where, setWhere] = useState(text(f.where));
  const [project, setProject] = useState(text(f.project));
  const [role, setRole] = useState<Role>((text(f.role) as Role) || "attend");
  // An entry with no part stays so until the person picks one: "attend" is the list's first choice, not a choice made.
  const [roleTouched, setRoleTouched] = useState(false);
  const { save, note } = useSave(props.record, props.onClose);
  // An entry that runs past midnight ends on a later day than it starts; the editor keeps that many days between them, so its
  // end time of day may be earlier than its start and moving the day moves both.
  const spanDays = first.day && last.day && last.time ? Math.max(0, Math.round((Date.parse(`${last.day}T12:00:00Z`) - Date.parse(`${first.day}T12:00:00Z`)) / 86_400_000)) : 0;
  const endBad = until !== "" && at !== "" && spanDays === 0 && until <= at;
  const fields: Record<string, unknown> = {};
  if (title.trim() && title.trim() !== text(f.title)) fields.title = title.trim();
  const nextStart = joinMoment(on, at);
  if (on && nextStart !== text(f.start)) fields.start = nextStart;
  const nextEnd = at && until && on ? joinMoment(addDays(on, spanDays), until) : null;
  if ((nextEnd ?? "") !== text(f.end)) fields.end = nextEnd;
  if (where.trim() !== text(f.where)) fields.where = where.trim() || null;
  if (project !== text(f.project)) fields.project = project || null;
  if (roleTouched && role !== text(f.role)) fields.role = role;
  const changed = Object.keys(fields).length > 0;
  const reason = !title.trim() ? t("meeting.add_why_name") : !on ? t("meeting.add_why_day") : endBad ? t("meeting.add_why_times") : !changed ? t("open.edit.reason.unchanged") : undefined;
  const ready = !!title.trim() && !!on && !endBad && changed;
  return (
    <Drawer
      open
      title={t("entry.edit.title")}
      onClose={props.onClose}
      dirty={changed}
      footer={
        <>
          <Button variant="quiet" onClick={props.onClose}>
            {t("action.cancel")}
          </Button>
          <Button variant="primary" type="submit" form={`${id}-form`} disabled={!ready} reason={reason}>
            {t("open.edit.save")}
          </Button>
        </>
      }
    >
      <form
        id={`${id}-form`}
        className="answer-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) void save(fields, t("meeting.edit.done", { title: title.trim() }));
        }}
      >
        <FormField id={`${id}-what`} label={t("meeting.what")}>
          <input id={`${id}-what`} type="text" autoFocus autoComplete="off" value={title} onChange={(e) => setTitle(e.target.value)} />
        </FormField>
        <div className="meeting-times">
          <FormField id={`${id}-day`} label={t("meeting.day")}>
            <DateField id={`${id}-day`} value={on} onChange={(e) => setOn(e.target.value)} />
          </FormField>
          <FormField id={`${id}-time`} label={t("meeting.time")}>
            <DateField id={`${id}-time`} kind="time" value={at} placeholder={t("meeting.time_placeholder")} onChange={(e) => setAt(e.target.value)} />
          </FormField>
          <FormField id={`${id}-until`} label={t("meeting.until")}>
            <DateField id={`${id}-until`} kind="time" value={until} disabled={at === ""} placeholder={at === "" ? t("meeting.time_placeholder") : t("meeting.until_placeholder")} aria-invalid={endBad || undefined} onChange={(e) => setUntil(e.target.value)} />
          </FormField>
        </div>
        {endBad && (
          <p className="problem-note" role="alert">
            {t("meeting.until_bad")}
          </p>
        )}
        <FormField id={`${id}-where`} label={t("meeting.where")}>
          <input id={`${id}-where`} type="text" autoComplete="off" value={where} onChange={(e) => setWhere(e.target.value)} />
        </FormField>
        {!justMe && <ProjectPicker label={t("open.edit.project")} value={project} empty={t("addtodo.no_project")} onChange={setProject} />}
        <FormField id={`${id}-role`} label={t("meeting.role")}>
          <Select id={`${id}-role`} value={role} onChange={(e) => {
              setRole(e.target.value as Role);
              setRoleTouched(true);
            }}>
            {(["attend", "run", "brief_only"] as const).map((r) => (
              <option key={r} value={r}>
                {t(`meeting.role.${r}`)}
              </option>
            ))}
          </Select>
        </FormField>
        {note}
      </form>
    </Drawer>
  );
}

/** The editor of a note: its words, and where it belongs. */
export function NoteEditor(props: { record: Record_; onClose: () => void }) {
  const { t } = useWords();
  const { justMe } = useSides();
  const id = useId();
  const f = props.record.fields;
  const [words, setWords] = useState(text(f.text));
  const [project, setProject] = useState(text(f.project));
  const { save, note } = useSave(props.record, props.onClose);
  const fields: Record<string, unknown> = {};
  if (words.trim() && words.trim() !== text(f.text).trim()) fields.text = words.trim();
  if (project !== text(f.project)) fields.project = project || null;
  const changed = Object.keys(fields).length > 0;
  const reason = !words.trim() ? t("note.edit.reason.empty") : !changed ? t("open.edit.reason.unchanged") : undefined;
  return (
    <Drawer
      open
      title={t("note.edit.title")}
      onClose={props.onClose}
      dirty={changed}
      footer={
        <>
          <Button variant="quiet" onClick={props.onClose}>
            {t("action.cancel")}
          </Button>
          <Button variant="primary" type="submit" form={`${id}-form`} disabled={!words.trim() || !changed} reason={reason}>
            {t("open.edit.save")}
          </Button>
        </>
      }
    >
      <form
        id={`${id}-form`}
        className="answer-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (words.trim() && changed) void save(fields, t("note.edit.saved"));
        }}
      >
        <FormField id={`${id}-text`} label={t("note.edit.text")}>
          <textarea id={`${id}-text`} rows={8} autoFocus value={words} onChange={(e) => setWords(e.target.value)} />
        </FormField>
        {!justMe && <ProjectPicker label={t("note.edit.where")} value={project} empty={t("addtodo.no_project")} onChange={setProject} />}
        {note}
      </form>
    </Drawer>
  );
}
