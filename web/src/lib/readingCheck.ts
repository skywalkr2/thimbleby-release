// What a reading check of an account says (design 6.32): the lines the drawer shows, from the gate's own counts the server sends,
// in the person's words. The service's own words never come here, only its status and a reason code.
import type { S } from "./api";
import { clockTime } from "./dates";

type Say = (key: string, vars?: Record<string, string | number>) => string;
type Count = (key: string, n: number, vars?: Record<string, string | number>) => string;

export type Check = S["ReadingCheckView"];

const ENDINGS = ["read", "throttled", "offline", "outage", "auth", "no_access"];

/** The lines of a check, in the order the drawer lists them: how it ended, requests sent, each refusal and its wait, requests held
 * back, until when nothing more is sent, and the pace the gate settled on. */
export function checkLines(check: Check, t: Say, tn: Count): string[] {
  const lines = [
    t(`reading_check.headline.${ENDINGS.includes(check.ended) ? check.ended : "other"}`, { read: check.read, asked: check.asked }),
    tn("reading_check.requests", check.requests),
  ];
  if (check.refusals.length === 0) lines.push(t("reading_check.no_refusals"));
  else lines.push(tn("reading_check.refusals", check.refusals.length));
  for (const refusal of check.refusals) {
    const time = clockTime(refusal.at);
    lines.push(
      refusal.status == null
        ? t("reading_check.refusal_no_status", { time, reason: refusal.reason })
        : t("reading_check.refusal", { time, status: refusal.status, reason: refusal.reason }),
    );
    if (refusal.until) {
      const until = clockTime(refusal.until);
      lines.push(refusal.wait_seconds == null ? t("reading_check.wait_no_time", { until }) : tn("reading_check.wait", Math.round(refusal.wait_seconds), { until }));
    }
  }
  if (check.held > 0) lines.push(tn("reading_check.held", check.held));
  if (check.waiting_until) lines.push(t("reading_check.waiting", { until: clockTime(check.waiting_until) }));
  if (check.pace_per_second != null && check.declared_per_second != null) {
    const pace = rate(check.pace_per_second);
    const declared = rate(check.declared_per_second);
    lines.push(pace === declared ? t("reading_check.pace_same", { pace }) : t("reading_check.pace", { pace, declared }));
  }
  return lines;
}

/** A pace in requests a second, with as few digits as say it: 2, 0.5, 0.25. */
const rate = (n: number): string => String(Math.round(n * 100) / 100);
