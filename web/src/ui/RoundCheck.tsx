// The round tick in a row's leading slot (design 7.12): one press marks the item done, and Undo comes in the toast. It is a button
// with the action's name, never a check box, because it acts at once. The ring is 20px inside a 32px target (44px on a touch screen), empty at rest, with the check coming up on hover or focus.
import type { ButtonHTMLAttributes, Ref } from "react";
import styles from "./RoundCheck.module.css";

export interface RoundCheckProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "aria-label"> {
  /** What pressing it does, in words: it is the button's accessible name. */
  label: string;
  /** The tooltip, when it says less than the name ("Mark done" for "Mark done: <title>"). */
  tip?: string;
  /** The smaller mark, for a to-do among a day's entries. */
  small?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function RoundCheck(props: RoundCheckProps) {
  const { label, tip, small, className, ref, ...rest } = props;
  return (
    <button type="button" {...rest} ref={ref} aria-label={label} title={tip ?? label} className={[styles.check, small ? styles.small : "", className ?? ""].filter(Boolean).join(" ")}>
      <span className={styles.ring} aria-hidden="true" />
    </button>
  );
}
