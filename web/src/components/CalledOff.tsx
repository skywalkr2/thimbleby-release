// A called-off entry waits for a new date or a drop (design 6.33): the two small forms behind its line on Today, and the
// Call off choice on an entry's own page. A new date is the move form with the entry's own time to begin with; a drop needs
// the person's reason, in their words. Each is the person's own change with Undo; the to-dos tied to the entry follow it.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "../lib/api";
import { useAct } from "../lib/act";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Actions } from "../ui/Actions";
import { MoveForm, localInput } from "./EventActs";

/** What a change to a called-off entry says and how it is undone: the server's refusal in words, or the done message with Undo. */
export function useCalledOff() {
  const act = useAct();
  const { t } = useWords();
  return (call: () => Promise<{ changeset?: string | null }>, message: string) =>
    act(call, (done) => ({ message: done.changeset ? message : t("calendar.own.refused.changed"), undo: done.changeset ? () => api.undo(done.changeset ?? "") : undefined }));
}

export function NewDateForm(props: { event: string; title: string; onClose: () => void }) {
  const { t } = useWords();
  const said = useCalledOff();
  const record = useQuery({ queryKey: ["record", "event", props.event], queryFn: () => api.record("event", props.event) });
  if (!record.data) return null;
  return (
    <MoveForm
      start={localInput(record.data.fields.start as string | undefined)}
      end={localInput(record.data.fields.end as string | null | undefined)}
      go={t("calledoff.date.go")}
      onCancel={props.onClose}
      onSubmit={async (from, to) => {
        const done = await said(() => api.newDateEvent(props.event, { start: from, end: to || null }), t("calledoff.date.toast", { title: props.title }));
        if (done) props.onClose();
      }}
    />
  );
}

export function DropForm(props: { event: string; title: string; onClose: () => void }) {
  const { t } = useWords();
  const said = useCalledOff();
  const id = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => box.current?.focus(), []);
  const words = reason.trim();
  const save = async () => {
    if (!words || busy) return;
    setBusy(true);
    const done = await said(() => api.dropEvent(props.event, words), t("calledoff.drop.toast", { title: props.title }));
    if (done === undefined) setBusy(false);
    else props.onClose();
  };
  return (
    <form
      className="answer-form note-box"
      data-drop-entry={props.event}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className="hint" htmlFor={id}>
        {t("calledoff.drop.label", { title: props.title })}
      </label>
      <textarea
        id={id}
        ref={box}
        className="short"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            props.onClose();
          } else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void save();
          }
        }}
      />
      <Actions align="end">
        <Button variant="quiet" onClick={props.onClose}>
          {t("action.cancel")}
        </Button>
        <Button variant="primary" type="submit" disabled={!words || busy}>
          {t("calledoff.drop.go")}
        </Button>
      </Actions>
    </form>
  );
}
