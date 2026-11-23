// The person's own rewording of a draft's content (design 6.12): each named part as an editable box, saved as one change that
// clears any yes, so the draft needs a new one. The cursor starts in the first box.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { QUOTED_PART, partLabel, type Act } from "../lib/acts";
import { useWords } from "../lib/wording";
import { Actions } from "../ui/Actions";
import { Button } from "../ui/Button";
import { FormField } from "../ui/FormField";

export function RewordAct(props: { act: Act; busy: boolean; onSave: (parts: Record<string, string>) => void; onCancel: () => void }) {
  const { t, has } = useWords();
  const base = useId();
  const first = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  // The subject first, as a message reads, whatever order the parts came in.
  const names = Object.keys(props.act.parts)
    .filter((n) => n !== QUOTED_PART)
    .sort((a, b) => Number(b === "subject") - Number(a === "subject"));
  const [parts, setParts] = useState<Record<string, string>>(() => Object.fromEntries(names.map((n) => [n, props.act.parts[n]])));
  // After the click that opened the form has settled, so the browser's own focus change can't take it back.
  useEffect(() => {
    const timer = window.setTimeout(() => first.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, []);
  const changed = names.some((n) => parts[n] !== props.act.parts[n]);
  return (
    <form
      className="answer-form"
      aria-label={t("outgoing.reword")}
      data-reword=""
      onSubmit={(e) => {
        e.preventDefault();
        if (changed) props.onSave(parts);
      }}
    >
      {names.map((n, i) => (
        <FormField key={n} id={`${base}-${n}`} label={partLabel(n, t, has)}>
          {(id) => {
            const common = {
              id,
              ref: i === 0 ? first : undefined,
              value: parts[n],
              onChange: (e: { target: { value: string } }) => setParts({ ...parts, [n]: e.target.value }),
              onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
                if (e.key === "Escape") {
                  e.stopPropagation();
                  props.onCancel();
                }
              },
            };
            // A subject is one line: a line break in it would be refused when the message is built.
            return n === "subject" ? <input type="text" {...common} /> : <textarea {...common} />;
          }}
        </FormField>
      ))}
      <Actions align="end">
        <Button variant="quiet" onClick={props.onCancel}>
          {t("action.cancel")}
        </Button>
        <Button type="submit" variant="primary" disabled={props.busy || !changed}>
          {t("outgoing.reword.save")}
        </Button>
      </Actions>
    </form>
  );
}
