// A date or a due phrase is one unit (design 7.12): it stays whole on its line, and a line that is too short moves the whole unit
// down rather than splitting "Due" from "today" or "Sun," from "Nov 15".
import type { ReactNode } from "react";
import styles from "./NoBreak.module.css";

export function NoBreak(props: { children: ReactNode; className?: string }) {
  return <span className={[styles.unit, props.className ?? ""].filter(Boolean).join(" ")}>{props.children}</span>;
}
