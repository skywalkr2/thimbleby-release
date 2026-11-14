// A title that keeps to two lines and ends in an ellipsis, with its whole text on hover and on focus (the reviewer's rule for
// every title: design 7.7, "Titles are short"). The cut is the browser's (a line clamp), so no word is dropped and nothing is
// decided by counting words; the tip appears only when the text really is cut, and the cut text is reachable with the keyboard.
// `children` are drawn in place of the text when they carry a link; the link is then the focus stop, and the tip follows it.
import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import styles from "./ClampedText.module.css";

/** Whether the element's text is cut: it has more lines than it shows (or runs wider than its box). */
export function useIsCut(ref: React.RefObject<HTMLElement | null>, watch: unknown): boolean {
  const [cut, setCut] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setCut(el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1);
    measure();
    if (typeof ResizeObserver !== "function") return;
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    return () => seen.disconnect();
  }, [ref, watch]);
  return cut;
}

/** The tip with a title's whole text, drawn beside the clamped element it belongs to; the wrapper shows it on hover and focus. */
export function FullTextTip(props: { id: string; text: string }) {
  return (
    <span id={props.id} role="tooltip" className={styles.tip} data-full-text="">
      {props.text}
    </span>
  );
}

export function ClampedText(props: {
  /** The whole text: what the tip shows, and what the element says when it is cut. */
  text: string;
  /** What is drawn inside, when it is more than the text (a link around it). */
  children?: ReactNode;
  /** How many lines before the ellipsis; two by default. */
  lines?: number;
  /** Take a focus stop of its own when cut. Left off when the content holds a link, which is the stop. */
  focusable?: boolean;
  inline?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  const cut = useIsCut(ref, props.text);
  const style = { "--clamp-lines": props.lines ?? 2 } as CSSProperties;
  return (
    <span className={[styles.wrap, props.inline ? styles.wrapInline : "", props.className ?? ""].filter(Boolean).join(" ")} data-clamped={cut ? "" : undefined} data-clamp-wrap="">
      <span ref={ref} className={styles.clamp} style={style} tabIndex={cut && props.focusable !== false ? 0 : undefined} aria-describedby={cut ? id : undefined} data-clamp="">
        {props.children ?? props.text}
      </span>
      {cut && <FullTextTip id={id} text={props.text} />}
    </span>
  );
}
