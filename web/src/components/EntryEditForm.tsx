// Change the place, the repeat or the person's part in an entry the app keeps itself (design 5.1, 7.7): the same fields the
// add form has, with the entry's own values to begin with. One change with Undo; what was not touched is left as it was.
import { useId, useState } from "react";
import { api } from "../lib/api";
import { useAct } from "../lib/act";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { DateField } from "../ui/DateField";
import { FormField } from "../ui/FormField";
import { Select } from "../ui/Select";
import { Actions } from "../ui/Actions";

type Every = "" | "day" | "week" | "two_weeks" | "month";
type Role = "attend" | "run" | "brief_only";
export interface EntryFields {
  where?: string | null;
  repeat?: { every: Exclude<Every, "">; until?: string | null } | null;
  role?: Role | null;
  start?: string | null;
  title?: string | null;
}

export function EntryEditForm(props: { entry: string; version: number; fields: EntryFields; onClose: () => void }) {
  const { t } = useWords();
  const act = useAct();
  const base = useId();
  const [where, setWhere] = useState(props.fields.where ?? "");
  const [repeat, setRepeat] = useState<Every>(props.fields.repeat?.every ?? "");
  const [stops, setStops] = useState(props.fields.repeat?.until ?? "");
  const [role, setRole] = useState<Role>(props.fields.role ?? "attend");
  // An entry with no part stays so until the person picks one: the list shows "attend" as its first choice, not as a choice made.
  const [roleTouched, setRoleTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const first = (props.fields.start ?? "").slice(0, 10);
  const stopsBad = repeat !== "" && stops !== "" && first !== "" && stops < first;
  const submit = async () => {
    if (busy || stopsBad) return;
    setBusy(true);
    const done = await act(
      () => api.editEvent(props.entry, { read_version: props.version, where: where.trim() || null, repeat: repeat || null, repeat_until: repeat && stops ? stops : null, role: roleTouched ? role : (props.fields.role ?? null) }),
      (result) =>
        result.refused || (!result.changeset && result.refused !== undefined)
          ? { message: t("calendar.own.refused.changed") }
          : { message: t("meeting.edit.done", { title: props.fields.title ?? "" }), undo: result.changeset ? () => api.undo(result.changeset ?? "") : undefined },
    );
    if (done === undefined) setBusy(false);
    else props.onClose();
  };
  return (
    <form
      className="answer-form"
      data-edit-entry={props.entry}
      aria-labelledby={`${base}-title`}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") props.onClose();
      }}
    >
      <h3 id={`${base}-title`}>{t("meeting.edit.title")}</h3>
      <FormField id={`${base}-where`} label={t("meeting.where")}>
        <input id={`${base}-where`} type="text" autoFocus autoComplete="off" value={where} onChange={(e) => setWhere(e.target.value)} />
      </FormField>
      <FormField id={`${base}-repeat`} label={t("meeting.repeat")}>
        <Select id={`${base}-repeat`} value={repeat} onChange={(e) => setRepeat(e.target.value as Every)}>
          <option value="">{t("meeting.repeat.none")}</option>
          {(["day", "week", "two_weeks", "month"] as const).map((every) => (
            <option key={every} value={every}>
              {t(`meeting.repeat.${every}`)}
            </option>
          ))}
        </Select>
      </FormField>
      {repeat !== "" && (
        <FormField id={`${base}-stops`} label={t("meeting.repeat_until")}>
          <DateField id={`${base}-stops`} value={stops} onChange={(e) => setStops(e.target.value)} />
        </FormField>
      )}
      {stopsBad && (
        <p className="problem-note" role="alert">
          {t("meeting.repeat_until_bad")}
        </p>
      )}
      <FormField id={`${base}-role`} label={t("meeting.role")}>
        <Select id={`${base}-role`} value={role} onChange={(e) => {
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
      <Actions align="end">
        <Button variant="quiet" onClick={props.onClose}>
          {t("action.cancel")}
        </Button>
        <Button variant="primary" type="submit" disabled={busy || stopsBad}>
          {t("meeting.edit.go")}
        </Button>
      </Actions>
    </form>
  );
}
