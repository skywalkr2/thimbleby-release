// The side filter on Today and Follow-ups (design 6.32, 7.8): All, Personal and each side of the person's work, shown only to a
// person who has set one, and remembered on this browser as the theme is. One option for each side of the person's work. It is
// there only for a person who has set one, and nothing is drawn without a side; the pick is the same on every screen and is
// remembered on this browser. A screen that has something waiting for the person passes it as `waiting`, and each choice
// then says how many wait in it, in words for a screen reader. A screen with tabs passes `counts` (what the open tab holds) and
// `holds` (what it holds in all), so the numbers match the list and a short list has no bar.
// On a phone, below 1100px of window, and wherever the choices are more than four or have a long name (a strip would cut it), there is no strip:
// one button in the page header names the pick and opens a sheet with the choices as a list to pick from.
import { useState } from "react";
import { useIsNarrow, useMediaQuery } from "../lib/media";
import { countText } from "../lib/counts";
import { filterBarShown } from "../lib/filterbar";
import { useSideSlot } from "../lib/marks";
import { UNASSIGNED, useSideFilter, type SideChoice } from "../lib/sides";
import { useTabCounts, type WaitingScreen } from "../lib/waiting";
import { useWords } from "../lib/wording";
import { Icon } from "../ui/Icon";
import { MarkDot } from "../ui/MarkDot";
import { FilterPill } from "../ui/FilterPill";
import { useInFilterSheet } from "../ui/inFilterSheet";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Sheet } from "../ui/Sheet";
import styles from "./SideFilter.module.css";

/** The window width below which the strip gives way to the button and its sheet. */
export const SIDE_STRIP_BELOW = "(max-width: 1100px)";
/** The most choices, and the longest name, a strip draws at any width: a segmented control is for a few short choices, so more
 * than this (or a name longer than this) is the one button and its sheet, where no name is ever cut. */
export const SIDE_STRIP_MAX_CHOICES = 4;
export const SIDE_STRIP_MAX_NAME = 18;

/** A strip of choices is for a few short names; with more than this many sides (Personal counts as one), or a side's name longer than this, the one button and its sheet
 * stand in for it at every width (a name is never cut short in a row of choices). */

interface SideOptionRow {
  value: SideChoice;
  label: string;
  count: number;
  countWords?: string;
  mark?: React.ReactNode;
}

/** The sheet of every side with its color, which is also the filter: one tap picks and closes. The Schedule's "+N more" opens it too. */
export function SideSheet(props: { options: SideOptionRow[]; onClose: () => void }) {
  const { t } = useWords();
  const filter = useSideFilter();
  return (
    <Sheet title={t("sides.filter.sheet")} onClose={props.onClose}>
      <p className={styles.hint}>{t("sides.filter.sheet_hint")}</p>
      <ul className={styles.options} aria-label={t("sides.filter.label")}>
        {props.options.map((o) => (
          <li key={o.value}>
            <button
              type="button"
              className={styles.option}
              aria-current={o.value === filter.picked ? "true" : undefined}
              aria-label={o.count ? `${o.label}, ${o.countWords ?? o.count}` : undefined}
              data-side-option={o.value}
              onClick={() => {
                filter.set(o.value);
                props.onClose();
              }}
            >
              {o.mark}
              <span className={styles.name}>{o.label}</span>
              {o.count ? (
                <span className={styles.count} aria-hidden="true">
                  {countText(o.count)}
                </span>
              ) : null}
              <span className={styles.tick} aria-hidden="true">
                {o.value === filter.picked && <Icon name="check" size={18} />}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}

/** Every choice of the side filter (All, each side and each of its views), each side with its dot: what the sheet lists. */
export function useSideOptions(): SideOptionRow[] {
  const { t } = useWords();
  const filter = useSideFilter();
  const slotOf = useSideSlot();
  const row = (value: SideChoice, label: string, side?: string): SideOptionRow => {
    const slot = side ? slotOf(side) : null;
    return { value, label, count: 0, mark: slot !== null ? <MarkDot kind="side" slot={slot} /> : undefined };
  };
  return [
    row("all", t("sides.filter.all")),
    ...filter.options.flatMap((o) => [row(o.id, o.name, o.id), ...filter.views.filter((v) => v.side === o.id).map((v) => row(v.id, t("sides.filter.view", { side: v.sideName, view: v.name }), o.id))]),
    ...(filter.unassigned ? [row(UNASSIGNED, t("sides.filter.unassigned"))] : []),
  ];
}

export function SideFilter(props: {
  waiting?: WaitingScreen;
  /** How many rows the tab on screen holds under a choice. It replaces the screen-wide count of what waits, so a count never
   * contradicts the list under it (an empty tab shows none). */
  counts?: (choice: SideChoice) => number;
  /** How many rows the list holds before any filter: a list with fewer than the filter bar's minimum draws no bar, unless a side is
   * picked (the person can always take it off). */
  holds?: number;
  /** Whether the rows on screen are on more than one side, so the choice can change the list. Given, it stands in for `holds`: a
   * screen that draws its filter by what it can change, not by how long the list is. A side that is picked stays drawn. */
  canChange?: boolean;
  /** Draw each side's dot before its name, so the choices are also the key to the sides' colors on the screen below. */
  marks?: boolean;
}) {
  const { t, tn } = useWords();
  const filter = useSideFilter();
  const slotOf = useSideSlot();
  const counted = useTabCounts(props.waiting ?? "changed");
  const narrow = useIsNarrow();
  const tight = useMediaQuery(SIDE_STRIP_BELOW);
  const [open, setOpen] = useState(false);
  const inSheet = useInFilterSheet();
  if (!filter.offered) return null;
  // A short list has no bar at all, whatever the views are: that is known before they are read.
  if (props.canChange !== undefined) {
    if (!props.canChange && filter.picked === "all") return null;
  } else if (props.holds !== undefined && !filterBarShown(props.holds, filter.picked !== "all")) return null;
  // The shape of the control depends on how many choices there are, views included: hold a placeholder until both are read.
  if (!filter.ready) return <span className={styles.pending} aria-hidden="true" data-side-pending="" />;
  const option = (value: SideChoice, label: string, side?: string) => {
    const count = props.counts ? props.counts(value) : props.waiting ? counted(value) : 0;
    const slot = props.marks && side ? slotOf(side) : null;
    return { value, label, count, countWords: count ? tn("sides.filter.waiting", count) : undefined, mark: slot !== null ? <MarkDot kind="side" slot={slot} /> : undefined };
  };
  const options = [
    option("all", t("sides.filter.all")),
    // A side's views follow it, each named with its side so a choice is never a bare name.
    ...filter.options.flatMap((o) => [option(o.id, o.name, o.id), ...filter.views.filter((v) => v.side === o.id).map((v) => option(v.id, t("sides.filter.view", { side: v.sideName, view: v.name }), o.id))]),
    ...(filter.unassigned ? [option(UNASSIGNED, t("sides.filter.unassigned"))] : []),
  ];
  if (inSheet) {
    // Inside the Filter sheet the choices are the list itself, so one tap picks and nothing opens over the sheet.
    return (
      <div className={styles.inSheet}>
        <p className={styles.sheetCaption}>{t("sides.filter.label")}</p>
        <ul className={styles.options} aria-label={t("sides.filter.label")}>
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                className={styles.option}
                aria-current={o.value === filter.picked ? "true" : undefined}
                aria-label={o.count ? `${o.label}, ${o.countWords ?? o.count}` : undefined}
                data-side-option={o.value}
                onClick={() => filter.set(o.value)}
              >
                {o.mark}
                <span className={styles.name}>{o.label}</span>
                {o.count ? (
                  <span className={styles.count} aria-hidden="true">
                    {countText(o.count)}
                  </span>
                ) : null}
                <span className={styles.tick} aria-hidden="true">
                  {o.value === filter.picked && <Icon name="check" size={18} />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const crowded = options.length > SIDE_STRIP_MAX_CHOICES || options.some((o) => o.label.length > SIDE_STRIP_MAX_NAME);
  if (narrow || tight || crowded) {
    const current = options.find((o) => o.value === filter.picked) ?? options[0];
    return (
      <>
        <FilterPill
          className={styles.open}
          label={t("sides.filter.name")}
          value={current.label}
          mark={current.mark}
          aria-haspopup="dialog"
          aria-label={t("sides.filter.open", { name: current.label })}
          title={current.label}
          data-side-select=""
          onClick={() => setOpen(true)}
        />
        {open && <SideSheet options={options} onClose={() => setOpen(false)} />}
      </>
    );
  }
  return <SegmentedControl<SideChoice> label={t("sides.filter.label")} value={filter.picked} onChange={filter.set} options={options} />;
}
