// The filter pill's button form (design 7.12): the same pill as FilterChip, for a filter whose choices open in a sheet ("Side: All",
// or the phone's "Filter (2)"). It is one shape and one label pattern with FilterChip at every width: the filter's name, a colon,
// then the choice, with a caret.
import type { ReactNode } from "react";
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from "react-aria-components";
import styles from "./FilterChip.module.css";

export function FilterPill(props: Omit<AriaButtonProps, "children" | "className"> & { label: string; value?: string; mark?: ReactNode; className?: string; title?: string }) {
  const { label, value, mark, className, ...rest } = props;
  return (
    <AriaButton {...rest} className={[styles.chip, styles.button, className ?? ""].filter(Boolean).join(" ")} data-filter-pill="">
      <span className={value ? styles.name : styles.bare}>{label}</span>
      {mark}
      {value && <span className={styles.value}>{value}</span>}
    </AriaButton>
  );
}
