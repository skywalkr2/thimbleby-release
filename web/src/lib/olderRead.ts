// What a read of older mail says when the service slowed it down or failed partway: what was kept and when the rest
// continues, in the person's own time and plain words (never the service's text).
import { clockTime, shortWaitMinutes } from "./dates";

type Say = (key: string, vars?: Record<string, string | number>) => string;

/** When a wait ends, in words: a wait of about a minute or less "in a minute or so", one shorter than `ui.short_wait_minutes` "in a few
 * minutes", and a longer one "around" the time of day. Every place that says when a read carries on says it through this. */
export function waitWhen(until: string, t: Say): string {
  const minutes = minutesUntil(until);
  if (minutes <= 1.5) return t("read.wait.minute");
  if (minutes < shortWaitMinutes()) return t("read.wait.few");
  return t("read.wait.around", { time: clockTime(until) });
}

/** Minutes from now to a moment the server wrote; a moment that can't be read counts as a long wait, so a time of day is shown. */
function minutesUntil(until: string): number {
  const minutes = (new Date(until).getTime() - Date.now()) / 60000;
  return Number.isFinite(minutes) ? minutes : Infinity;
}

/** Whether a wait is short enough to say in words (`ui.short_wait_minutes`). */
export const isShortWait = (until: string): boolean => minutesUntil(until) < shortWaitMinutes();

/** What stopped a read, as the server states it: the kind of stop, when the rest continues by itself, and whether it gave
 * up and waits for the person. */
export type Stop = { stopped?: string | null; continues_at?: string | null; gave_up?: boolean; taken?: number | null; about?: number | null };

/** One sentence for a stop: when the rest continues, that it waits for the person, or what to do about a stop the person
 * has to deal with. Empty when the read did not stop. */
export function stopWords(stop: Stop, t: Say): string {
  if (!stop.stopped) return "";
  if (stop.gave_up) return t("read.stopped.gave_up");
  // Waiting for the worker's lane, or between its slices: nothing failed, so there is no time to give.
  if (stop.stopped === "queued" || stop.stopped === "reading") {
    // With how many there will be about, and some already in, the line counts: "400 of about 1,700".
    if (stop.about && stop.taken) return t("read.stopped.of", { taken: stop.taken, about: stop.about });
    return t(`read.stopped.${stop.stopped}`);
  }
  if (stop.continues_at && ["throttled", "outage", "offline"].includes(stop.stopped)) {
    // Nothing taken yet: the read starts then, rather than "the rest" continuing.
    const key = stop.taken === 0 ? `read.stopped.${stop.stopped}.start` : `read.stopped.${stop.stopped}`;
    return t(key, { when: waitWhen(stop.continues_at, t) });
  }
  return t(["auth", "no_access"].includes(stop.stopped) ? `read.stopped.${stop.stopped}` : "read.stopped.other");
}

/** The parts of a source that say whether it was read once and what its latest try was. */
type FirstReadState = {
  label: string;
  enabled?: boolean;
  read_at?: string | null;
  account_state?: string | null;
  last?: { outcome: string; retry_at?: string | null } | null;
  /** A source whose older mail is being read, or that has looked back already, has had its first read. */
  older_read?: { gave_up?: boolean } | null;
  looked_back_to?: string | null;
};

/** Whether a source's first read is still to come, so its account's card says what it is doing: it is on, its sign-in is good, it was
 * never read, and its latest try was none yet or the service asking to wait (any other outcome has its own line). */
export function firstReadPending(s: FirstReadState): boolean {
  if (s.enabled === false || s.read_at || s.account_state === "signed_out" || s.account_state === "expired") return false;
  if (s.older_read != null || s.looked_back_to) return false;
  return !s.last || s.last.outcome === "throttled";
}

/** Whether anything about these sources is still being read (a first read to come, or older mail queued, between slices or waiting),
 * so the screen that shows them looks again every few seconds. */
export function stillReading(sources: (FirstReadState & { older_read?: { gave_up?: boolean } | null })[]): boolean {
  return sources.some((s) => firstReadPending(s) || (s.older_read != null && !s.older_read.gave_up));
}

/** The lines for the sources of an account that were never read: one for those being taken a first look at, one for those the service
 * asked to wait on, with the earliest time. Empty when every source was read. */
export function firstReadLines(sources: FirstReadState[], t: Say): string[] {
  const pending = sources.filter(firstReadPending);
  const waiting = pending.filter((s) => s.last?.outcome === "throttled" && s.last.retry_at);
  const taking = pending.filter((s) => !waiting.includes(s));
  const lines: string[] = [];
  if (taking.length > 0) lines.push(t("read.first_look.taking"));
  if (waiting.length > 0) {
    const until = waiting.map((s) => s.last?.retry_at ?? "").sort()[0] ?? "";
    lines.push(t("read.first_look.waiting", { when: waitWhen(until, t) }));
  }
  return lines;
}
