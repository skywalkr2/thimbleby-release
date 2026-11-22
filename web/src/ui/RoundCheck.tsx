// The round tick in a row's leading slot (design 7.12): one press marks the item done, and Undo comes in the toast. It is a button
// with the action's name, never a check box, because it acts at once. The ring is 20px inside a 32px target (44px on a touch screen), empty at rest, with the check coming up on hover or focus.
import { useCallback, useEffect, useRef, useState, type ButtonHTMLAttributes, type Ref } from "react";
import styles from "./RoundCheck.module.css";

export interface RoundCheckProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "aria-label"> {
  /** What pressing it does, in words: it is the button's accessible name. */
  label: string;
  /** The tooltip, when it says less than the name ("Mark done" for "Mark done: <title>"). */
  tip?: string;
  /** The smaller mark, for a to-do among a day's entries. */
  small?: boolean;
  /** Filled at once when pressed, before the save answers; the save's failure empties it again. */
  checked?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function RoundCheck(props: RoundCheckProps) {
  const { label, tip, small, checked, className, ref, ...rest } = props;
  return (
    <button type="button" {...rest} ref={ref} aria-label={label} data-checked={checked ? "" : undefined} title={tip ?? label} className={[styles.check, small ? styles.small : "", className ?? ""].filter(Boolean).join(" ")}>
      <span className={styles.ring} aria-hidden="true" />
    </button>
  );
}

/** The press every round check shares: the mark fills at once, the save runs after it, and a save that did not happen (it
 * returns nothing, or throws) empties the mark again so the row reads as not done. */
export function useCheckNow(run: () => Promise<unknown>): [boolean, () => void] {
  const [checked, setChecked] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const press = useCallback(() => {
    setChecked(true);
    const back = () => {
      if (alive.current) setChecked(false);
    };
    run().then((result) => {
      if (result === undefined) back();
    }, back);
  }, [run]);
  return [checked, press];
}
