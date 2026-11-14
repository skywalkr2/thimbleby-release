// A list filtered to nothing (design 7.12, "States"): a titled card that says which filter is on, how many things wait outside it
// when the screen knows, and one quiet button that puts the screen back to everything ("Show all sides" for a side filter, "Clear
// filter" otherwise). It is the empty state of every screen that has a filter, so "nothing here" and "nothing matching" are never
// the same sentence. In a place where other lines still follow it (`inline`) the two sentences run as one line.
import type { HTMLAttributes, ReactNode } from "react";
import { useWords } from "../lib/wording";
import { EmptyState } from "./EmptyState";

export function FilteredEmpty(
  props: Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
    /** The sentence that names the filter ("Nothing for Lantern Row Studio today."); the card's title. */
    text: ReactNode;
    /** What waits outside the filter ("3 things on your other sides need you."), when it is known. */
    others?: ReactNode;
    /** Puts the filter back to everything. */
    onClear: () => void;
    /** The button's words when they are not "Clear filter" (the filter's own word: "Show all sides"). */
    label?: string;
    /** One line with no mark, for a place where other lines still follow it. */
    inline?: boolean;
    /** The page-level card (see EmptyState). */
    card?: boolean;
  },
) {
  const { t } = useWords();
  const { text, others, onClear, label, inline, ...rest } = props;
  const action = { label: label ?? t("state.filtered.clear"), onClick: onClear };
  if (inline) return <EmptyState {...rest} inline text={others ? <>{text} {others}</> : text} action={action} data-filtered-empty="" />;
  return <EmptyState {...rest} title={typeof text === "string" ? text : undefined} text={others ?? (typeof text === "string" ? undefined : text)} action={action} data-filtered-empty="" />;
}
