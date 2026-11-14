// The underlined strip of views one screen switches between (the Schedule's Day, Week, Month and Timeline). It is a tab list: one tab
// is in the tab order, the arrow keys, Home and End move between the tabs and choose the one they land on, and a screen reader hears
// which view is chosen. It is the screen's view switch; the segmented control stays for a choice inside a view.
import { useRef, type KeyboardEvent } from "react";
import styles from "./ViewTabs.module.css";

export interface ViewTab<T extends string> {
  value: T;
  label: string;
}

export function ViewTabs<T extends string>(props: { label: string; options: ViewTab<T>[]; value: T; onChange: (value: T) => void; className?: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const at = Math.max(0, props.options.findIndex((o) => o.value === props.value));
  const move = (event: KeyboardEvent<HTMLButtonElement>, from: number) => {
    const last = props.options.length - 1;
    const to = event.key === "ArrowRight" ? (from === last ? 0 : from + 1) : event.key === "ArrowLeft" ? (from === 0 ? last : from - 1) : event.key === "Home" ? 0 : event.key === "End" ? last : -1;
    if (to < 0) return;
    event.preventDefault();
    props.onChange(props.options[to].value);
    refs.current[to]?.focus();
  };
  return (
    <div role="tablist" aria-label={props.label} className={[styles.strip, props.className ?? ""].filter(Boolean).join(" ")}>
      {props.options.map((o, n) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[n] = el;
          }}
          type="button"
          role="tab"
          aria-selected={props.value === o.value}
          tabIndex={n === at ? 0 : -1}
          className={styles.tab}
          onClick={() => props.onChange(o.value)}
          onKeyDown={(e) => move(e, n)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
