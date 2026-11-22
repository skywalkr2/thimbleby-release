// What changed groups its rows (design 7.13): what needs the person first, then everything
// else under the day it was handed in. In a group, rows that read the same and carry nothing to look at are one run: the
// newest is drawn with its count ("×5"), and the rest are behind "Show 4 more like this", never dropped.
import { useQuery } from "@tanstack/react-query";
import { api, type S } from "./api";
import { clockDay } from "./dates";

type Item = S["ChangeItem"];

export type ChangeGroupKind = "needs" | "day";

export interface ChangeRun {
  /** The row that stands for the run: the newest of it. */
  head: Item;
  /** The rows that read the same, newest first, drawn only when the run is opened. */
  same: Item[];
  /** Rows that read the same from another account at about the same time (`ui.twin_window_minutes`): the same change seen twice,
   * drawn as the head row naming both accounts, never as rows of their own. */
  twins: Item[];
}

/** The minutes within which the same change from two accounts is one row (`ui.twin_window_minutes`), read from the runtime
 * configuration the app holds; zero when it is not known, which keeps every account's row. */
export function useTwinWindow(): number {
  const rc = useQuery({ queryKey: ["runtime-config"], queryFn: api.runtimeConfig, enabled: false, staleTime: Infinity });
  const minutes = rc.data?.twin_window_minutes;
  return minutes && minutes > 0 ? Math.floor(minutes) : 0;
}

/** The accounts a run's rows were read from, the head's first, each once; empty when the rows name none. */
export function accountsOf(run: ChangeRun): string[] {
  return [...new Set([run.head, ...run.twins].map((c) => c.source_title).filter((n): n is string => Boolean(n)))];
}

export interface ChangeGroup {
  id: string;
  kind: ChangeGroupKind;
  /** The day (yyyy-mm-dd) of a day group. */
  day?: string;
  runs: ChangeRun[];
}

/** Whether a row waits on the person: it stopped. (What is asked is answered on Today; here it is only said.) */
export const needsYou = (c: Item): boolean => !c.dismissed && (c.state === "needs_you" || c.state === "failed");

/** Whether a row carries nothing to look at, so that it may stand in a run with others that read the same. */
const plain = (c: Item): boolean =>
  (c.edits ?? []).length < 2 && !c.changeset?.ops.some((o) => o.status === "held" || o.ask?.status === "open") && !c.note && !(c.first_go && c.state === "needs_you");

/** The groups of the rows, in the order the rows come in. `titleOf` and `stateOf` say what a row reads as: rows with the same
 * title and the same state, side by side, are one run. */
export function groupChanges(rows: Item[], titleOf: (c: Item) => string, stateOf: (c: Item) => string, twinMinutes = 0): ChangeGroup[] {
  const groups: ChangeGroup[] = [];
  const add = (id: string, kind: ChangeGroupKind, item: Item, day?: string) => {
    let group = groups.find((g) => g.id === id);
    if (!group) {
      group = { id, kind, day, runs: [] };
      groups.push(group);
    }
    // The same change read from another account within the window is the same row, naming both accounts.
    const at = (c: Item) => Date.parse(c.created_at);
    const twin = (a: Item, b: Item) =>
      twinMinutes > 0 && plain(a) && plain(b) && Boolean(a.source && b.source && a.source !== b.source && a.source_title && b.source_title) &&
      titleOf(a) === titleOf(b) && stateOf(a) === stateOf(b) && Math.abs(at(a) - at(b)) <= twinMinutes * 60_000;
    const mate = group.runs.find((r) => twin(r.head, item) && !r.twins.some((w) => w.source === item.source));
    if (mate) {
      mate.twins.push(item);
      return;
    }
    const last = group.runs[group.runs.length - 1];
    const same = (a: Item, b: Item) => plain(a) && plain(b) && titleOf(a) === titleOf(b) && stateOf(a) === stateOf(b);
    if (last && same(last.head, item)) last.same.push(item);
    else group.runs.push({ head: item, same: [], twins: [] });
  };
  for (const item of rows) {
    if (needsYou(item)) add("needs", "needs", item);
    else {
      const when = clockDay(item.created_at);
      add(`day:${when}`, "day", item, when);
    }
  }
  // The groups stand in the order a person reads them: needs first, then days, newest day first.
  const rank = (g: ChangeGroup) => (g.kind === "needs" ? 0 : 1);
  return groups.map((g, i) => [g, i] as const).sort(([a, i], [b, j]) => rank(a) - rank(b) || (a.kind === "day" && b.kind === "day" ? (b.day ?? "").localeCompare(a.day ?? "") : i - j)).map(([g]) => g);
}

/** How many runs a group draws before "Show N more". */
export const RUNS_SHOWN = 25;

/** The runs of a group that are drawn: the first `RUNS_SHOWN`, or all once the group's own "Show more" was chosen. */
export const shownRuns = (group: ChangeGroup, all: ReadonlySet<string>): ChangeRun[] => (all.has(group.id) ? group.runs : group.runs.slice(0, RUNS_SHOWN));

/** The rows in the order the groups draw them (only the head of a run, plus the rest of a run that is open). */
export function drawn(groups: ChangeGroup[], open: ReadonlySet<string>, all: ReadonlySet<string> = new Set()): Item[] {
  return groups.flatMap((g) => shownRuns(g, all).flatMap((r) => (open.has(r.head.id) ? [r.head, ...r.same] : [r.head])));
}
