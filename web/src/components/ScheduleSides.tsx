// The key to the sides' colors on the Schedule (design 7.13): one line above the calendar with "● Name" for each side that has an entry in
// the range on screen, the name cut at 16 with the whole of it on hover and in its accessible name. When the chips do not fit the line,
// as many as fit are shown and "+N more" opens the side menu (every side with its color, which is also the filter). The line never wraps.
import { useLayoutEffect, useRef, useState } from "react";
import { chipsThatFit, KEY_CHIP_NAME } from "../lib/calendar";
import { useWords } from "../lib/wording";
import { MarkDot } from "../ui/MarkDot";
import { cutName } from "../ui/SideMark";
import { SideSheet, useSideOptions } from "./SideFilter";
import styles from "./Schedule.module.css";

export interface KeySide {
  id: string;
  name: string;
  slot: number;
}

export function ScheduleSides(props: { sides: KeySide[] }) {
  const { t, tn } = useWords();
  const { sides } = props;
  const options = useSideOptions();
  const row = useRef<HTMLUListElement>(null);
  const [shown, setShown] = useState(sides.length);
  const [open, setOpen] = useState(false);
  const names = sides.map((s) => `${s.id}:${s.name}`).join("|");
  useLayoutEffect(() => {
    const list = row.current;
    if (!list) return;
    const measure = () => {
      const items = Array.from(list.querySelectorAll<HTMLElement>("li[data-key-side]"));
      const more = list.querySelector<HTMLElement>("li[data-key-more]");
      // Draw everything, measure, then leave out what does not fit.
      for (const el of items) el.hidden = false;
      if (more) more.hidden = false;
      const gap = parseFloat(getComputedStyle(list).columnGap || "0") || 0;
      const fit = chipsThatFit(items.map((el) => el.getBoundingClientRect().width), gap, list.clientWidth, more ? more.getBoundingClientRect().width : 0);
      items.forEach((el, n) => (el.hidden = n >= fit));
      if (more) more.hidden = fit >= items.length;
      setShown(fit);
    };
    measure();
    const watch = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    watch?.observe(list);
    return () => watch?.disconnect();
  }, [names]);
  if (sides.length === 0) return null;
  const left = sides.length - shown;
  return (
    <>
      <ul ref={row} className={styles.sideKey} aria-label={t("schedule.sides.label")} data-side-key="">
        {sides.map((s) => (
          <li key={s.id} className={styles.sideKeyChip} data-key-side={s.id} title={s.name}>
            <MarkDot kind="side" slot={s.slot} />
            <span aria-hidden="true">{cutName(s.name, KEY_CHIP_NAME)}</span>
            <span className="sr">{s.name}</span>
          </li>
        ))}
        <li className={styles.sideKeyMore} data-key-more="" hidden>
          <button type="button" className={styles.sideKeyButton} aria-haspopup="dialog" aria-label={tn("schedule.sides.more_sr", Math.max(left, 1))} onClick={() => setOpen(true)}>
            {t("schedule.group.more_short", { n: Math.max(left, 1) })}
          </button>
        </li>
      </ul>
      {open && <SideSheet options={options} onClose={() => setOpen(false)} />}
    </>
  );
}
