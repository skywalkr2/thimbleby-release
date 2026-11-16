// A service's own reply to a failed read, behind a button and shown whole when open (design 7.9): the sentence a person reads is the
// app's, and this is for the one who wants the reply word for word. Nothing is drawn when there is no reply to show.
import { useId, useState } from "react";
import { failureDetail } from "../lib/sources";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import type { S } from "../lib/api";
import styles from "./ProblemDetails.module.css";

export function ProblemDetails(props: { source: S["WatchSourceView"] }) {
  const { t } = useWords();
  const [open, setOpen] = useState(false);
  const id = useId();
  const detail = failureDetail(props.source);
  if (!detail) return null;
  return (
    <span className={styles.details}>
      <Button variant="quiet" size="sm" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((was) => !was)}>
        {t(open ? "problem.hide_details" : "problem.show_details")}
      </Button>
      {open && (
        <span id={id} className={styles.reply} data-problem-details="">
          {detail}
        </span>
      )}
    </span>
  );
}
