// A side shown as its dot and its name: one mark wherever a row, pane, card or line says which side something is on. The
// name is whole while its line has room and cut with an ellipsis only at the line's edge (the whole name is on hover and is what a
// screen reader reads); a side the person no longer has shows nothing.
import { useSideSlot } from "../lib/marks";
import { useSideFilter } from "../lib/sides";
import { MarkDot } from "./MarkDot";
import styles from "./SideMark.module.css";

/** The length `cutName` keeps by default, for a place that cannot cut by its own width (an account's name in a sentence). */
export const SIDE_CUT = 24;

export function cutName(text: string, at = SIDE_CUT): string {
  return text.length > at ? `${text.slice(0, at - 1).trimEnd()}…` : text;
}

/** The side's dot and name, or nothing when the side is unknown. Whether to show it at all is the caller's: a list filtered
 * to one side, or a person with one side, has no need of it. */
export function SideMark(props: { side: string | null | undefined; className?: string }) {
  const slot = useSideSlot()(props.side);
  const options = useSideFilter().options;
  const name = props.side ? (options.find((o) => o.id === props.side)?.name ?? "") : "";
  if (!name || slot === null) return null;
  return (
    <span className={[styles.mark, props.className ?? ""].filter(Boolean).join(" ")} data-side-mark="" title={name}>
      <MarkDot kind="side" slot={slot} />
      <span className={styles.name}>{name}</span>
    </span>
  );
}
