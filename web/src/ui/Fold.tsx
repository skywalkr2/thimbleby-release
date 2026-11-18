// A fold: one quiet line that opens a list kept out of the way until the person wants it. The button says what is inside; the
// list is not drawn while closed, and the button's state is on it for the keyboard and for screen readers.
import { useId, useState, type ReactNode } from "react";
import { Button } from "./Button";
import styles from "./Fold.module.css";

export function Fold(props: { label: string; children: ReactNode; startOpen?: boolean }) {
  const [open, setOpen] = useState(!!props.startOpen);
  const id = useId();
  return (
    <div className={styles.fold} data-fold="">
      <Button variant="quiet" size="sm" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {props.label}
      </Button>
      {open && (
        <div id={id} className={styles.body}>
          {props.children}
        </div>
      )}
    </div>
  );
}
