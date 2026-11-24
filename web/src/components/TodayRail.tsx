// Today's rail (design 7.7): the cards beside the queue (below it under 1100px, and on the phone each folded to one line), in
// the order the person plans the day by: the Briefing, This week (its days off, the working days left and its goals, every day), the Schedule, Came in and how far
// setup is. The Schedule card is always drawn, so the side column is never blank; the others are drawn when they have something.
// From 1280px a line the person opens shows in the rail's column in place of the cards, so the queue holds still. The rail stays in
// view while the page scrolls, as long as all of it fits in the window. When nothing but the Schedule's own "nothing today" is there and the queue is empty, one line
// says so. What needs the person is the queue, not the rail, and a to-do is acted on in To-dos and questions, so
// neither the priorities nor the to-dos are cards. An add-on's Today panels follow the cards, each folded to one line.
import { useRef, useState, type Ref } from "react";
import { stickyTop, useStickyWhenFits } from "../lib/sticky";
import { useSetupOpen } from "../lib/setup-open";
import { useWords } from "../lib/wording";
import { settingsView, viewHref, type View } from "../lib/views";
import { BriefCard, briefClosed, hasBrief, useBrief, useBriefClosings } from "./BriefCard";
import { useCameInCard } from "./CameInCard";
import { PluginPanels } from "./PluginPanels";
import { RailFolds } from "./RailPanel";
import { useScheduleCard } from "./ScheduleCard";
import { useThisWeekCard } from "./ThisWeekCard";
import styles from "./Today.module.css";

/** The rail's cards. `onAddSource` opens Sources with the add form open; it is offered only once setup is finished (while it is
 * open the setup line offers it). With a `workspace` the Briefing card is the form that is due. `queueEmpty` is whether the
 * queue has nothing for the person, which is when an empty rail says so. */
export function TodayRail(props: {
  onView: (view: View) => void;
  onAddSource?: () => void;
  workspace?: string;
  onOpenRecord?: (kind: string, id: string) => void;
  queueEmpty?: boolean;
  /** The element a line's items are drawn into, from 1280px, and whether a line is open there (the cards then give way to it). */
  detailRef?: Ref<HTMLDivElement>;
  detailOpen?: boolean;
  /** The element the setup card is drawn into at the end of the rail, where the rail is beside the queue. */
  setupRef?: Ref<HTMLDivElement>;
}) {
  const { t } = useWords();
  const setupOpen = useSetupOpen();
  const add = setupOpen ? undefined : (props.onAddSource ?? (() => props.onView(settingsView("connections"))));
  const open = props.onOpenRecord ?? (() => {});
  // The Briefing card closing for the day changes what is drawn, so the rail draws again.
  const [, closed] = useState(0);
  useBriefClosings();
  const brief = useBrief(null);
  const briefing = props.workspace ? { settled: !brief.isPending, drawn: hasBrief(brief.data, props.workspace) } : { settled: true, drawn: false };
  // The Schedule card is always drawn and, with no calendar connected, links to Connections while setup is open too.
  const schedule = useScheduleCard(add, viewHref(settingsView("connections")));
  const cameIn = useCameInCard(add);
  // This week is in the rail every day; the Monday form, on Today or asked for, holds the same in full and takes its place.
  const [askedMonday, setAskedMonday] = useState(false);
  const mondayShown = askedMonday || (!!props.workspace && hasBrief(brief.data, props.workspace) && brief.data?.form === "monday");
  const week = useThisWeekCard(mondayShown);
  const settled = briefing.settled && schedule.settled && cameIn.settled && week.settled;
  const nothing = settled && !briefing.drawn && !schedule.drawn && !cameIn.drawn && !week.drawn;
  const briefCard =
    (briefing.drawn || (props.workspace && briefClosed(brief.data, props.workspace))) && props.workspace ? (
      <BriefCard workspace={props.workspace} onOpenRecord={open} onOpenView={props.onView} onClosed={() => closed((n) => n + 1)} onAsked={(form) => setAskedMonday(form === "monday")} />
    ) : null;
  const rail = useRef<HTMLDivElement>(null);
  const sticks = useStickyWhenFits(rail, stickyTop);
  return (
    <div ref={rail} className={styles.rail} role="group" aria-label={t("today.rail.label")} data-region="" data-sticky={sticks ? "" : undefined}>
      {props.detailRef && <div ref={props.detailRef} className={styles.railSlot} data-rail-detail="" />}
      <div className={styles.railCards} hidden={props.detailOpen}>
        <RailFolds>
          {briefCard}
          {week.drawn && week.card}
          {schedule.card}
          {cameIn.drawn && cameIn.card}
        </RailFolds>
        {props.setupRef && <div ref={props.setupRef} className={styles.railSlot} data-rail-setup="" />}
        {nothing && props.queueEmpty && (
          <p className={styles.railNothing} data-rail-nothing="">
            {t("today.rail.nothing_else")}
          </p>
        )}
        <PluginPanels onOpenRecord={open} />
      </div>
    </div>
  );
}
