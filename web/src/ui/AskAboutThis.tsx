// The composer on a record's page (design 7.14): one line, with a send button inside it at the right. The label is for screen
// readers; the words in the box say what to ask. Enter sends and Shift+Enter starts another line, so the box grows with what is
// typed. Its height is set here, in code, so every web view sizes it alike: it opens tall enough for its example (the words
// in it when empty) and for what is typed, up to the CSS `max-height`, and scrolls only beyond that. The help line, when
// there is one, sits under it.
import { useCallback, useId, useLayoutEffect, useRef, type Ref } from "react";
import { useWords } from "../lib/wording";
import { IconButton } from "./IconButton";
import styles from "./AskAboutThis.module.css";

/** Sets the box's height to what its words need, the example when it is empty, never above its CSS `max-height`; it scrolls
 * only beyond that. Measured by the box itself, so it needs no engine support for sizing a box by its content. */
export function fitHeight(el: HTMLTextAreaElement, example: string | undefined) {
  el.style.height = "auto";
  el.style.overflowY = "hidden";
  const typed = el.value;
  // An empty box is as tall as its example: measure it by holding the example for a moment.
  const measuring = !typed && !!example;
  if (measuring) el.value = example ?? "";
  const needed = el.scrollHeight + (el.offsetHeight - el.clientHeight);
  if (measuring) el.value = typed;
  const limit = parseFloat(getComputedStyle(el).maxHeight);
  const max = Number.isFinite(limit) ? limit : Infinity;
  el.style.height = `${Math.min(needed, max)}px`;
  el.style.overflowY = needed > max ? "auto" : "hidden";
}

export function AskAboutThis(props: {
  /** What the box is for, said to a screen reader. */
  label: string;
  placeholder?: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy?: boolean;
  /** The send button's name. */
  sendLabel: string;
  inputRef?: Ref<HTMLTextAreaElement>;
}) {
  const id = useId();
  const { t } = useWords();
  const empty = !props.value.trim();
  const own = useRef<HTMLTextAreaElement | null>(null);
  const given = props.inputRef;
  const setBox = useCallback(
    (el: HTMLTextAreaElement | null) => {
      own.current = el;
      if (typeof given === "function") given(el);
      else if (given) (given as { current: HTMLTextAreaElement | null }).current = el;
    },
    [given],
  );
  // Size it whenever its words change, and again when its width changes (a narrower window wraps the example onto more lines).
  useLayoutEffect(() => {
    const el = own.current;
    if (el) fitHeight(el, props.placeholder);
  }, [props.value, props.placeholder]);
  useLayoutEffect(() => {
    const el = own.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const watch = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      fitHeight(el, props.placeholder);
    });
    watch.observe(el);
    return () => watch.disconnect();
  }, [props.placeholder]);
  return (
    <form
      className={styles.composer}
      data-composer=""
      onSubmit={(e) => {
        e.preventDefault();
        props.onSend();
      }}
    >
      <label htmlFor={id} className="sr">
        {props.label}
      </label>
      <div className={styles.box}>
        <textarea
          id={id}
          ref={setBox}
          rows={1}
          className={styles.input}
          value={props.value}
          aria-describedby={props.hint ? `${id}-hint` : undefined}
          placeholder={props.placeholder}
          onChange={(e) => props.onChange(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter starts a new line.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              props.onSend();
            }
          }}
        />
        <IconButton icon="send" label={props.busy ? t("conversation.sending") : props.sendLabel} type="submit" isDisabled={props.busy || empty} variant="secondary" size="sm" tooltip={false} />
      </div>
      {props.hint && (
        <p id={`${id}-hint`} className={styles.hint}>
          {props.hint}
        </p>
      )}
    </form>
  );
}
