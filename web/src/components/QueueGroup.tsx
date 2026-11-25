// A group of the Today queue (design 7.7): a small heading and its rows, in a list. The groups come in rank order and
// nothing nests inside a row beyond its items. A group may carry words after its label (`meta`), buttons at its right
// (`actions`) and a line before its rows (`note`).
import type { ReactNode } from "react";
import { GroupLabel } from "../ui/GroupLabel";
import styles from "./Today.module.css";

/** One group of the queue: its label (the shared group label, with how many lines it holds in a pill) and its lines. The count is drawn for the eye; the list itself tells a screen reader how many there are. */
export function QueueGroup(props: { id: string; title: string; count?: number; meta?: ReactNode; actions?: ReactNode; note?: ReactNode; tone?: "plain" | "danger"; sentence?: boolean; children?: ReactNode }) {
  const label = (
    <GroupLabel id={props.id} count={props.count} meta={props.meta} tone={props.tone} sentence={props.sentence} className={styles.groupHead}>
      {props.title}
    </GroupLabel>
  );
  return (
    <section className={styles.group} aria-labelledby={props.id} data-queue-group={props.id}>
      {props.actions ? (
        <div className={styles.groupHeadRow}>
          {label}
          <div className={styles.groupActions}>{props.actions}</div>
        </div>
      ) : (
        label
      )}
      {props.note}
      {props.children ? <ul className={styles.list}>{props.children}</ul> : null}
    </section>
  );
}
