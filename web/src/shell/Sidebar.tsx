// The sidebar (design 7.1, 7.13): Today with its count, then Work, then Records, then Sources, Add-ons and Settings at the
// bottom. Every entry is a real link, so it can be bookmarked, opened in a new tab and reached with Back. It is 232px with
// labels from 1024px (below that the main column would fall under its own 720px minimum) and a 64px icon rail below that, where each side's dot carries its initial and each icon has a tooltip; the person can collapse or pin it at any
// width, remembered on this device.
import { useState } from "react";
import { Link } from "react-aria-components";
import { useMediaQuery } from "../lib/media";
import { viewHref, type View } from "../lib/views";
import { useWords } from "../lib/wording";
import { GroupLabel } from "../ui/GroupLabel";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { MarkDot } from "../ui/MarkDot";
import { Tooltip } from "../ui/Tooltip";
import { useSideSlot } from "../lib/marks";
import { useNav, type NavEntry } from "./nav";
import { NavCount, navName } from "./NavCount";
import styles from "./Sidebar.module.css";

const KEY = "cockpit:sidebar";

function saved(): "collapsed" | "expanded" | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "collapsed" || v === "expanded" ? v : null;
  } catch {
    return null;
  }
}

/** Whether the sidebar shows labels: the person's choice for this device, or else by width (labels from 1024px). */
export function useSidebarMode(): { expanded: boolean; toggle: () => void } {
  const wide = useMediaQuery("(min-width: 1024px)");
  const [pref, setPref] = useState(saved);
  const expanded = pref ? pref === "expanded" : wide;
  const toggle = () => {
    const next = expanded ? "collapsed" : "expanded";
    setPref(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Storage can be blocked; the choice then lasts until the page closes.
    }
  };
  return { expanded, toggle };
}

function Entry(props: { entry: NavEntry; current: View; rail: boolean; sub?: boolean }) {
  const { entry } = props;
  const slot = useSideSlot()(entry.side);
  const link = (
    <Link
      href={viewHref(entry.view)}
      className={[styles.entry, props.sub ? styles.sub : ""].filter(Boolean).join(" ")}
      aria-current={props.current === entry.view ? "page" : undefined}
      aria-label={entry.count ? navName(entry) : undefined}
      data-view={entry.view}
      data-side-entry={slot !== null ? "" : undefined}
    >
      {slot !== null ? (
        <span className={styles.sideDot} aria-hidden="true" data-initial={props.rail ? "" : undefined}>
          {props.rail ? <span className={styles.initial} data-mark="side" data-color={String(slot)}>{[...entry.label.trim()][0]?.toUpperCase()}</span> : <MarkDot kind="side" slot={slot} />}
        </span>
      ) : entry.icon ? (
        <Icon name={entry.icon} />
      ) : (
        <span className={styles.glyph} aria-hidden="true">{entry.glyph}</span>
      )}
      <span className={styles.label}>
        {entry.label}
      </span>
      <NavCount entry={entry} className={styles.count} />
    </Link>
  );
  // The whole name shows on hover (the wrapper's title) and on focus (the tooltip; a link does not pass a pointer's hover to it), since a long label is cut
  // short, and on the icon rail the name is the only thing that tells the icons apart.
  return (
    <span className={styles.titled} title={entry.label} data-rail-title={props.rail ? "" : undefined}>
      <Tooltip text={entry.label} placement="right">{link}</Tooltip>
    </span>
  );
}

export function Sidebar(props: { current: View; expanded: boolean; onToggle: () => void }) {
  const { t } = useWords();
  const nav = useNav();
  const rail = !props.expanded;
  const entry = (e: NavEntry) => <Entry key={e.view} entry={e} current={props.current} rail={rail} sub={!!e.sub && !rail} />;
  return (
    <nav className={[styles.side, rail ? styles.rail : ""].filter(Boolean).join(" ")} aria-label={t("nav.label")}>
      <div className={styles.group}>
        {entry(nav.today)}
        {entry(nav.schedule)}
      </div>
      {/* With no side beside Personal the group has no heading, only a name for screen readers. */}
      <div className={styles.group} role="group" aria-label={nav.justMe ? nav.workTitle : undefined} aria-labelledby={nav.justMe ? undefined : "nav-work"}>
        {!nav.justMe && (
          <GroupLabel as="span" id="nav-work" className={styles.title}>
            {nav.workTitle}
          </GroupLabel>
        )}
        {nav.work.map(entry)}
      </div>
      {nav.sides.length > 0 && (
        <div className={styles.group} role="group" aria-labelledby="nav-sides">
          <GroupLabel as="span" id="nav-sides" className={styles.title}>
            {t("nav.sides")}
          </GroupLabel>
          {nav.sides.map(entry)}
        </div>
      )}
      <div className={styles.group} role="group" aria-labelledby="nav-records">
        <GroupLabel as="span" id="nav-records" className={styles.title}>
          {t("nav.records")}
        </GroupLabel>
        {nav.records.map(entry)}
      </div>
      <div className={styles.bottom}>
        {nav.bottom.map((e) => entry(e))}
        <div className={styles.toggle}>
          <IconButton
            icon="panel-left"
            label={t(props.expanded ? "nav.collapse" : "nav.expand")}
            onPress={props.onToggle}
            data-sidebar-toggle=""
          />
        </div>
      </div>
    </nav>
  );
}
