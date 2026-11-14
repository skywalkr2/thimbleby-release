// The Schedule's calendar toggles (design 7.7): each calendar the person reads, by name, with a tick box in its color, as a
// button that shows or hides its entries. Hidden is said in words as well as by the mark, so nothing is told by color alone. Shown only with more
// than one calendar; the choice is remembered on this browser, as the view is. The calendars are one "Calendars (3)" button that opens the
// list, never a row cut at the edge; in the phone's Filter sheet the list is the rows.
import { useState } from "react";
import { DialogTrigger } from "react-aria-components";
import { useWords } from "../lib/wording";
import { FilterPill } from "../ui/FilterPill";
import { useInFilterSheet } from "../ui/inFilterSheet";
import { Icon } from "../ui/Icon";
import { Popover } from "../ui/Popover";
import type { Calendars } from "./ScheduleEntry";
import styles from "./Schedule.module.css";

const KEY = "cockpit:schedule:hidden-calendars";

function stored(): Set<string> {
  try {
    const found: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return new Set(Array.isArray(found) ? found.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

/** The calendars the person hid on this screen, remembered on this browser. */
export function useHiddenCalendars(): [Set<string>, (id: string) => void] {
  const [hidden, setHidden] = useState<Set<string>>(stored);
  const toggle = (id: string) =>
    setHidden((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        window.localStorage.setItem(KEY, JSON.stringify([...next]));
      } catch {
        // Storage can be blocked; the choice then lasts until the page is closed.
      }
      return next;
    });
  return [hidden, toggle];
}

function Toggle(props: { calendar: NonNullable<Calendars["list"]>[number]; off: boolean; onToggle: (id: string) => void }) {
  const { t } = useWords();
  const { calendar, off } = props;
  return (
    <button type="button" className={styles.legendButton} aria-pressed={!off} data-calendar={calendar.id} onClick={() => props.onToggle(calendar.id)} title={calendar.name}>
      <span className={styles.tick} data-color={calendar.color ?? undefined} data-hidden={off ? "" : undefined} aria-hidden="true">
        {!off && <Icon name="check" size={12} />}
      </span>
      <span className={styles.legendName}>{calendar.name}</span>
      {off && <span className={styles.legendHidden}>{t("schedule.legend.hidden")}</span>}
    </button>
  );
}

export function ScheduleLegend(props: { calendars: Calendars; hidden: Set<string>; onToggle: (id: string) => void }) {
  const { t } = useWords();
  const list = props.calendars.list ?? [];
  const inSheet = useInFilterSheet();
  if (list.length < 2) return null;
  const items = (
    <>
      {list.map((calendar) => (
        <li key={calendar.id}>
          <Toggle calendar={calendar} off={props.hidden.has(calendar.id)} onToggle={props.onToggle} />
        </li>
      ))}
    </>
  );
  if (inSheet) {
    return (
      <div className={styles.legendSheet} data-schedule-legend="">
        <p className={styles.sheetCaption} id="schedule-calendars-label">
          {t("schedule.legend.label")}
        </p>
        <ul className={styles.legendRows} aria-labelledby="schedule-calendars-label">
          {items}
        </ul>
      </div>
    );
  }
  // The calendars are always one button that opens the list, never a row of chips that can run off its line.
  return (
    <div className={styles.toggles} data-schedule-legend="" data-collapsed="">
      <DialogTrigger>
        <FilterPill
          label={t("schedule.legend.name")}
          value={props.hidden.size > 0 ? t("schedule.legend.some", { shown: list.filter((c) => !props.hidden.has(c.id)).length, n: list.length }) : t("schedule.legend.all")}
          aria-label={t("schedule.legend.collapsed", { n: list.length })}
          data-calendars-open=""
        />
        <Popover label={t("schedule.legend.label")} size="sm" placement="bottom start">
          <ul className={styles.legendRows} aria-label={t("schedule.legend.label")}>
            {items}
          </ul>
        </Popover>
      </DialogTrigger>
    </div>
  );
}
