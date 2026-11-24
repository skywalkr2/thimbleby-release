// What Today's queue holds, counted and grouped in one place so the heading, the menu's count and the rows agree
// (design 7.7): the lines the engine ranks, the lines running plugins add, the stage tasks waiting for a go and what failed or is unsure on its way out. A line
// folded away (the week) is not counted.
import { useQuery } from "@tanstack/react-query";
import { api, type S } from "./api";
import { chosenArea, inArea, useStoredArea } from "./area-filter";
import { onAnySide, onSide, useSideFilter, type SideChoice } from "./sides";
import { useStageToday } from "../components/StageToday";
import { useActToday } from "./acts";
import { sidesOfAccount, useAccountToday } from "./account-today";

/** How many lines a card of Today's rail holds before one line says how many more there are, so the rail is never longer than
 * the queue beside it, when the setting (`ui.today.rail_rows`) is not known yet. */
export const RAIL_ROWS_DEFAULT = 3;

/** How many rows each card of Today's rail shows (`ui.today.rail_rows`), read from the runtime configuration the app holds. */
export function useRailRows(): number {
  const rc = useQuery({ queryKey: ["runtime-config"], queryFn: api.runtimeConfig, enabled: false, staleTime: Infinity });
  const rows = rc.data?.rail_rows;
  return rows && rows > 0 ? Math.floor(rows) : RAIL_ROWS_DEFAULT;
}

/** From how many things that need the person Today is a heavy day, and how many lines each group then shows before its button for
 * the rest (`ui.today.heavy_day_from`, `ui.today.group_rows`), when the settings are not known yet. */
export const HEAVY_DAY_DEFAULT = 30;
export const GROUP_ROWS_DEFAULT = 5;

export function useHeavyDay(): { from: number; rows: number } {
  const rc = useQuery({ queryKey: ["runtime-config"], queryFn: api.runtimeConfig, enabled: false, staleTime: Infinity });
  const from = rc.data?.heavy_day_from;
  const rows = rc.data?.group_rows;
  return { from: from && from > 0 ? Math.floor(from) : HEAVY_DAY_DEFAULT, rows: rows && rows > 0 ? Math.floor(rows) : GROUP_ROWS_DEFAULT };
}

/** The keys of the lines a heavy day tucks behind "Show N more": in each group but setup, the lines after its first `rows`, unless
 * the person opened that group. Every line is counted, whatever its kind. */
export function tuckedLines(lines: QueueLine[], rows: number, opened: ReadonlySet<string>): Set<string> {
  const tucked = new Set<string>();
  for (const group of GROUPS) {
    if (group === "setup" || opened.has(group)) continue;
    for (const line of inGroup(lines, group).slice(rows)) tucked.add(line.key);
  }
  return tucked;
}

export type QueueLine = S["QueueLineView"];
export type QueueGroupName = QueueLine["group"];

/** The groups in the order the engine ranks them (6.15); the screen never ranks. "Finish setting up" is last and is not among what
 * needs the person (design 7.7). */
export const GROUPS: readonly QueueGroupName[] = ["decide", "risk", "review", "send", "setup"];

/** Whether a line is a gap in setup: it is listed under "Finish setting up" and never counted among the things that need the person. */
export const isSetupLine = (line: QueueLine): boolean => line.group === "setup";

/** The kinds of line whose words are a count ("3 things need you"): with a count of zero there is nothing to say, so the
 * line is not shown. */
const COUNTED: ReadonlySet<QueueLine["kind"]> = new Set([
  "first_go",
  "catch_up_go",
  "intake_go",
  "intake_review",
  "batches",
  "restart",
  "paused",
  "limit",
  "borrow",
  "offline",
  "overdue",
  "review",
  "learned",
  "people_offers",
  "catch_up",
  "send",
  "sends",
  "nudge",
  "stale",
  "unfiled",
  "moved",
  "terms",
  "since_yesterday",
  "away",
]);

/** Whether a line has something to count: a line that counts things and holds none is left out. */
export const hasSomething = (line: QueueLine): boolean => !COUNTED.has(line.kind) || line.count > 0;

/** Several to-dos nobody has touched are one line ("3 to-dos untouched, the longest for 42 days"), in the place of the first of them: the
 * line says the fact once and opens To-dos, where each is kept or dropped. One stale to-do stays its own line with its choices. */
export function foldStale(lines: QueueLine[]): QueueLine[] {
  const stale = lines.filter((line) => line.kind === "stale" && line.count > 0);
  if (stale.length < 2) return lines;
  const folded: QueueLine = {
    ...stale[0],
    key: "stale",
    count: stale.length,
    actions: stale.flatMap((line) => line.actions ?? []),
    waiting_days: Math.max(...stale.map((line) => line.waiting_days ?? 0)),
    subject: null,
    choices: [],
  };
  return lines.flatMap((line) => (line === stale[0] ? [folded] : line.kind === "stale" && line.count > 0 ? [] : [line]));
}

/** The queue's lines; with a side picked, only that side's and the lines that belong to neither (the app's own). */
export function useQueue(side: SideChoice = "all") {
  const picked = useStoredArea();
  return useQuery({
    queryKey: ["today", "queue"],
    queryFn: api.todayQueue,
    // The area filter narrows to one area of life when the person picked one that some line is in.
    select: (lines) => {
      const area = chosenArea(lines, picked);
      return foldStale(lines.filter((line) => hasSomething(line) && (line.sides?.length ? onAnySide(line.sides, side, line.views) : onSide(line.side, side, line.views, !!line.project_name)) && inArea(line, area)));
    },
  });
}

/** How many lines need the person: the queue's (setup gaps aside), the plugins', the stages', the acts' and the accounts that are
 * not being read. Null until the queue has answered, so the
 * menu shows no number rather than a wrong one. */
export function useTodayCount(side: SideChoice = "all"): number | null {
  const queue = useQueue(side);
  const plugins = useQuery({ queryKey: ["plugin-today"], queryFn: api.pluginToday });
  const stage = useStageToday();
  const outgoing = useActToday();
  const accounts = useAccountToday(side);
  const failed = useTodayReadFailures().length > 0;
  const pending = useTodayReadsPending();
  if (!queue.data) return null;
  const count = queue.data.filter((line) => !isSetupLine(line)).length + (plugins.data?.length ?? 0) + stage.count + outgoing.count + accounts.count;
  // A read that failed or has not answered counts as nothing known, never as nothing: a zero from reads that could not
  // answer yet is "can't tell", so the empty card waits until every read has answered.
  return count === 0 && (failed || pending) ? null : count;
}

/** Whether any read Today's count depends on is still loading (no answer yet, and not failed). */
export function useTodayReadsPending(): boolean {
  const queue = useQuery({ queryKey: ["today", "queue"], queryFn: api.todayQueue });
  const plugins = useQuery({ queryKey: ["plugin-today"], queryFn: api.pluginToday });
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const stage = useStageToday();
  const outgoing = useActToday();
  return [queue, plugins, watch, outgoing.read, ...stage.reads].some((read) => read.isPending);
}

/** A read Today depends on that failed, with the words for what it was and the error it failed with. */
export interface ReadFailure {
  key: "sends" | "addons" | "stages" | "sources";
  /** The wording-sheet key of what could not be checked ("queue.read_failed.sends"). */
  wording: string;
  error: unknown;
  retry: () => void;
}

/** The reads besides the queue's own that Today's count and empty card depend on, as far as they have failed and not answered since:
 * what waits to go out, the add-ons' lines, the stages' tasks and the sources. Empty when every one answered. */
export function useTodayReadFailures(): ReadFailure[] {
  const plugins = useQuery({ queryKey: ["plugin-today"], queryFn: api.pluginToday });
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const stage = useStageToday();
  const outgoing = useActToday();
  const found: ReadFailure[] = [];
  const add = (key: ReadFailure["key"], reads: ReadonlyArray<{ isError: boolean; data: unknown; error: unknown; refetch: () => unknown }>) => {
    const bad = reads.find((read) => read.isError);
    if (bad) found.push({ key, wording: `queue.read_failed.${key}`, error: bad.error, retry: () => reads.forEach((read) => void read.refetch()) });
  };
  add("sends", [outgoing.read]);
  add("addons", [plugins]);
  add("stages", stage.reads);
  add("sources", [watch]);
  return found;
}

/** A side is picked and nothing of its own needs the person: what remains is the app's own lines, which belong to no side and stay
 * under every choice. The heading, the list's empty card and the lines agree on it, so none counts those as the side's. */
export function useSideBare(): boolean {
  const filter = useSideFilter();
  const queue = useQueue(filter.picked);
  const accounts = useAccountToday(filter.picked);
  const count = useTodayCount(filter.picked);
  const own = (queue.data ?? []).filter((line) => !isSetupLine(line));
  return (
    filter.choice !== "all" &&
    count !== null &&
    count > 0 &&
    count === own.length + accounts.count &&
    own.every((line) => line.side == null && !(line.sides ?? []).length) &&
    accounts.accounts.every((account) => sidesOfAccount(account).length === 0)
  );
}

/** The lines of one group, in the engine's order. */
export function inGroup(lines: QueueLine[], group: QueueGroupName): QueueLine[] {
  return lines.filter((line) => line.group === group);
}

/** Whether the lines name more than one project, which is when a row names its own. */
export function mixesProjects(lines: QueueLine[]): boolean {
  return new Set(lines.map((line) => line.project).filter(Boolean)).size > 1;
}

// The line the inspector showed last, for the rest of the session: returning to Today (or a live refresh) opens the same
// line, and when it is gone, the line now in its place.
let remembered: { key: string; index: number } | null = null;

export function rememberLine(key: string, index: number): void {
  remembered = { key, index };
}

export function recallLine(): { key: string; index: number } | null {
  return remembered;
}

/** Forgets the remembered line, so the inspector starts on the first one. */
export function forgetLine(): void {
  remembered = null;
}
