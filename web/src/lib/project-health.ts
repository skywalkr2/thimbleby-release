// What the app sees about a project beside the status the person typed (design 7.13): the words that say why the status
// may be out of date. The server decides whether they disagree (`status_disagrees`); this only says it in words.
import type { S } from "./api";

type T = (key: string, vars?: Record<string, string | number>) => string;
type TN = (key: string, n: number, vars?: Record<string, string | number>) => string;

type Seen = Pick<S["ProjectView"], "overdue_actions" | "quiet_weeks" | "target_passed" | "status_disagrees" | "completed">;

/** Whether the status should be marked: it says all is well and what the app sees says otherwise. A finished project never is. */
export const statusDisagrees = (p: Seen): boolean => p.status_disagrees && !p.completed;

/** "6 overdue · no change in 6 weeks · target day passed": only the signs that are there, in that order. */
export function healthWords(p: Seen, t: T, tn: TN): string {
  return [
    p.overdue_actions > 0 && tn("project.health.overdue", p.overdue_actions),
    p.quiet_weeks != null && tn("project.health.quiet", p.quiet_weeks),
    p.target_passed && t("project.health.target_passed"),
  ]
    .filter((x): x is string => !!x)
    .join(" · ");
}
