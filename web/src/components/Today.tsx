// The Today screen (design 7.7): what needs the person as a ranked queue, the line that has the cursor in the inspector
// (from 1680px; from 1280px up to it a line's items open in the rail's column, below that under the line), and the rail:
// the week and its goals, the schedule, what came in and how far setup is.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { longDay, onTheClock } from "../lib/dates";
import { useIsNarrow, useMediaQuery } from "../lib/media";
import { showRow, useReveal } from "../lib/reveal";
import { onSide, setSideChoice, useSideFilter } from "../lib/sides";
import { useQueue, useSideBare, useTodayCount } from "../lib/today";
import { settingsView, type View } from "../lib/views";
import { useWords } from "../lib/wording";
import { useNoneText } from "./Coverage";
import { useNextSetupStep } from "../lib/setup-next";
import { AreaFilter } from "./AreaFilter";
import { SideFilter } from "./SideFilter";
import { opensItems } from "./TodayDetail";
import { LearningNotice } from "./LearningNotice";
import { TodayQueue, type QueueHandlers, type Selection } from "./TodayQueue";
import { TodayNext } from "./TodayNext";
import { TodayRail } from "./TodayRail";
import styles from "./Today.module.css";

import { PageHeader } from "../ui/PageHeader";
/** The width from which the inspector sits beside the queue (the layout's third column). */
const INSPECTOR_FROM = "(min-width: 1680px)";
/** The width from which the rail sits beside the queue. */
const RAIL_BESIDE = "(min-width: 1100px)";
/** The width from which a line's items open in the rail's column, so the queue holds still (below the inspector's width). */
const RAIL_DETAIL = "(min-width: 1280px)";

export function Today(props: {
  workspace: string;
  onView: (view: View) => void;
  onAddSource: () => void;
  onOpenGuide: (step?: string) => void;
  /** Opens the form that hands something to the assistant. */
  onHandIn?: () => void;
  onOpenAnswer?: (request: string) => void;
  /** Opens the form that adds an AI account, in Settings. */
  onAddAccount?: () => void;
  onOpenRecord: (kind: string, id: string) => void;
  /** The configured shortcut keys, for the inspector's "j / k". */
  shortcuts?: Record<string, string>;
}) {
  const { t, tn } = useWords();
  const beside = useMediaQuery(INSPECTOR_FROM);
  const wideWindow = useMediaQuery(RAIL_BESIDE);
  const roomForDetail = useMediaQuery(RAIL_DETAIL);
  const narrowLayout = useIsNarrow();
  const railBeside = wideWindow && !narrowLayout;
  const inRail = railBeside && roomForDetail && !beside;
  // Where the rail takes a line's items and the setup card, once drawn (null until then).
  const [detailSlot, setDetailSlot] = useState<HTMLElement | null>(null);
  const [setupSlot, setSetupSlot] = useState<HTMLElement | null>(null);
  const filter = useSideFilter();
  const queue = useQueue();
  const count = useTodayCount(filter.picked);
  const bare = useSideBare();
  const none = useNoneText();
  // With setup unfinished, "nothing needs you" would be untrue: setup is what is next, and the heading says which step.
  const setupNext = useNextSetupStep();
  const [selected, setSelected] = useState<Selection | null>(null);
  // The heading is a greeting for the time of day, with the person's first name once it is known.
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const first = (me.data?.full_name ?? "").trim().split(/\s+/)[0] ?? "";
  const hour = Math.floor(onTheClock(new Date()).minutes / 60);
  const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  const greeting = first ? t(`today.greeting.${part}`, { name: first }) : t(`today.greeting.${part}.plain`);

  // Another part of the screen asks for an answer or a question to be looked at: its line opens, with the cursor on it.
  const [shown, setShown] = useState<string | null>(null);
  // A line the side filter hides is still the one asked for, so the filter goes back to All to show it.
  const reveal = (side: Parameters<typeof onSide>[0]) => {
    if (!onSide(side, filter.choice)) setSideChoice("all");
  };
  const open = (find: (l: NonNullable<typeof queue.data>[number]) => boolean) => {
    const found = queue.data?.find((l) => opensItems(l) && find(l));
    if (!found) return false;
    reveal(found.side);
    setSelected({ key: found.key, sendBack: false });
    setShown(found.key);
    return true;
  };
  useReveal("changeset", (id) => open((l) => l.changeset === id));
  useReveal("question", (id) => open((l) => l.question === id));
  // A line named by its key (the briefing links to the queue line of what it lists): it opens, with the cursor on it.
  useReveal("line", (key) => {
    const found = queue.data?.find((l) => l.key === key);
    if (!found) return false;
    reveal(found.side);
    setSelected({ key: found.key, sendBack: false });
    setShown(found.key);
    return true;
  });
  const shownRow = useRef<string | null>(null);
  useEffect(() => {
    if (!shown || shownRow.current === shown) return;
    shownRow.current = shown;
    showRow(document.querySelector<HTMLElement>(`[data-line-key="${CSS.escape(shown)}"]`));
  }, [shown, selected]);

  const handlers: QueueHandlers = {
    onOpenAiAccounts: () => props.onView(settingsView("ai")),
    onOpenHandover: () => props.onView("handover"),
    onOpenRules: () => props.onView("records/rules-review"),
    onOpenKnowledge: () => props.onView("records/knowledge"),
    onOpenAnswer: props.onOpenAnswer,
    onAddAccount: props.onAddAccount,
    onOpenSources: () => props.onView(settingsView("connections")),
    onOpenRecord: props.onOpenRecord,
    onOpenGuide: props.onOpenGuide,
    onHandIn: props.onHandIn,
    onOpenView: props.onView,
  };
  return (
    <div className={styles.today}>
      <div className={styles.head}>
        <PageHeader
          title={greeting}
          subtitle={
            <>
              {longDay(new Date())}
              {count === null ? null : count === 0 ? (
                <>
                  {" · "}
                  {setupNext ? t("today.needs.setup_next", { step: setupNext.label }) : filter.choice === "all" ? none : t("sides.today.none", { side: filter.named })}
                </>
              ) : (
                <>
                  {" · "}
                  {/* With a side picked the count says it is that side's, and a side with nothing of its own says so: the badge in the menu counts every side. */}
                  {filter.choice === "all" ? <strong>{tn("today.needs.count", count)}</strong> : bare ? t("sides.today.none", { side: filter.named }) : <strong>{tn("today.needs.count_side", count, { side: filter.named })}</strong>}
                </>
              )}
              <TodayNext />
            </>
          }
          filters={
            <>
              <SideFilter />
              <AreaFilter />
            </>
          }
        />
      </div>
      <LearningNotice />
      <TodayQueue
        selected={selected}
        onSelect={setSelected}
        beside={beside}
        handlers={handlers}
        shortcuts={props.shortcuts}
        workspace={props.workspace}
        detailSlot={inRail ? detailSlot : undefined}
        setupSlot={railBeside ? setupSlot : undefined}
      />
      <TodayRail
        onView={props.onView}
        onAddSource={props.onAddSource}
        workspace={props.workspace}
        onOpenRecord={props.onOpenRecord}
        queueEmpty={count === 0}
        detailRef={inRail ? setDetailSlot : undefined}
        detailOpen={inRail && selected !== null}
        setupRef={railBeside ? setSetupSlot : undefined}
      />
    </div>
  );
}
