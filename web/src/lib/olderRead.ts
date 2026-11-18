// What a read of older mail says when the service slowed it down or failed partway: what was kept and when the rest
// continues, in the person's own time and plain words (never the service's text).
import { clockTime } from "./dates";

type Say = (key: string, vars?: Record<string, string | number>) => string;

/** What stopped a read, as the server states it: the kind of stop, when the rest continues by itself, and whether it gave
 * up and waits for the person. */
export type Stop = { stopped?: string | null; continues_at?: string | null; gave_up?: boolean };

/** One sentence for a stop: when the rest continues, that it waits for the person, or what to do about a stop the person
 * has to deal with. Empty when the read did not stop. */
export function stopWords(stop: Stop, t: Say): string {
  if (!stop.stopped) return "";
  if (stop.gave_up) return t("read.stopped.gave_up");
  if (stop.continues_at && ["throttled", "outage", "offline"].includes(stop.stopped)) {
    return t(`read.stopped.${stop.stopped}`, { time: clockTime(stop.continues_at) });
  }
  return t(["auth", "no_access"].includes(stop.stopped) ? `read.stopped.${stop.stopped}` : "read.stopped.other");
}
