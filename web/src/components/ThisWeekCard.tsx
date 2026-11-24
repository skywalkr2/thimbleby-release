// The This week card of Today's rail (design 7.7): the week's days off with the working days left, and the goals to confirm or
// the ones kept, on every day of the week. It is not drawn while the Monday briefing is on Today (that form holds the same
// things in full), and a week with no day off and no goals offers nothing to say, so it is not drawn.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import { useWords } from "../lib/wording";
import { Failed, RailPanel } from "./RailPanel";
import { Goals, useBrief } from "./BriefCard";
import { daysOffSentence } from "./WeekAhead";

/** `hidden`: the Monday briefing is showing, so this card gives way to it. */
export function useThisWeekCard(hidden: boolean): { settled: boolean; drawn: boolean; card: ReactNode } {
  const { t, tn } = useWords();
  const week = useQuery({ queryKey: ["week-ahead"], queryFn: api.weekAhead });
  const monday = useBrief("monday");
  const goals = monday.data?.goals ?? null;
  const settled = !week.isPending && !monday.isPending;
  const hasGoals = !!goals && (goals.confirmed || goals.proposed.length > 0);
  const hasDaysOff = (week.data?.days_off.length ?? 0) > 0;
  const drawn = !hidden && (hasDaysOff || hasGoals);
  if (!drawn) return { settled, drawn: false, card: null };
  const days = week.data ? daysOffSentence(week.data, t) : "";
  const left = week.data?.working_days ?? 0;
  return {
    settled,
    drawn: true,
    card: (
      <RailPanel id="this-week" title={t("rail.week.title")} count={null} countText="" summary={week.data ? tn("rail.week.working_days", left) : ""}>
        {week.isError && <Failed text={t("week_ahead.load_failed")} retry={() => void week.refetch()} />}
        {days && (
          <p data-this-week-days-off="">
            {days}
          </p>
        )}
        {hasGoals && goals && <Goals goals={goals} />}
      </RailPanel>
    ),
  };
}
