// The alpha's numbers as plain lines: one place words them, for the screen that shows them and for the report that shares them,
// so what the person reads is what would be sent. Every word comes from the wording sheet.
import type { S } from "./api";
import { day } from "./dates";
import { formatNumber, useWriteAmount } from "./money";
import { useWords } from "./wording";

type Numbers = S["AlphaNumbers"];

export function useAlphaLines() {
  const { t, tn, locale } = useWords();
  const write = useWriteAmount();
  const since = (n: Numbers) => (n.since ? day(n.since) : "");
  const until = (n: Numbers) => (n.until ? day(n.until) : "");

  /** The days the numbers cover, said as the whole first week or as the days so far. */
  const range = (n: Numbers): string => {
    if (n.days_so_far === 0) return "";
    if (n.complete) return t("alpha.week", { from: since(n), to: until(n) });
    return tn("alpha.so_far", n.days_so_far, { from: since(n), to: until(n) });
  };

  const span = (minutes: number): string => {
    if (minutes < 120) return tn("alpha.minutes", minutes);
    const hours = Math.round(minutes / 60);
    return hours < 48 ? tn("alpha.hours", hours) : tn("alpha.days", Math.round(hours / 24));
  };

  /** The five numbers, one line each. */
  const lines = (n: Numbers): string[] => [
    t("alpha.days_used", { n: n.days_used, total: n.days_so_far }),
    n.cost_per_day > 0 ? t("alpha.cost", { amount: write(n.cost_per_day, 2, 4) }) : t("alpha.cost_none"),
    t("alpha.corrections", { n: formatNumber(n.corrections_per_day, locale, 0, 2) }),
    t("alpha.sent", { written: n.sent_as_written, edited: n.sent_edited }),
    n.first_result_minutes == null ? t("alpha.first_result_none") : t("alpha.first_result", { time: span(n.first_result_minutes) }),
  ];

  /** The words a shared report opens with: the range and the five lines. */
  const shared = (n: Numbers): string => [t("alpha.share_words", { range: range(n) }), ...lines(n)].join("\n");

  return { range, lines, shared };
}
