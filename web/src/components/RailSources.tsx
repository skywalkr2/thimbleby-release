// What the rail's cards share (design 7.7): the clock, what a card says about its sources when it has no rows, the sources'
// problems and their names. A card that has nothing is not drawn, so a card asks here whether there is a button to connect
// or a problem to tell.
import { useQuery } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { CardSaid } from "./cardSaid";
import { api } from "../lib/api";
import { anyReading, failedReads, railProblem } from "../lib/sources";
import { settingsView, viewHref } from "../lib/views";
import { ButtonLink } from "../ui/Button";
import { useWords } from "../lib/wording";

/** The current time, refreshed every minute, for the "now" line and for telling today's mail from older mail. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** What a card says about its sources when it has no rows: a button to connect one while none is set up or reading (only when
 * `onAdd` is given), or the problems of the sources that couldn't be read, one line each. A card with neither and no rows has
 * nothing to say and is not drawn. */
export function useSourceState(
  onAdd: (() => void) | undefined,
  label: string,
  kind: "mail" | "calendar",
): { button?: { label: string; run: () => void }; problems: string[] } {
  const { t } = useWords();
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  if (!watch.data) return { problems: [] };
  if (!anyReading(watch.data)) return onAdd ? { button: { label, run: onAdd }, problems: [] } : { problems: [] };
  // A source that couldn't be read is said so, with why and what to do, and never leaves the card looking up to date.
  return { problems: failedReads(watch.data, kind).map((source) => railProblem(source, t)) };
}

/** What a source that couldn't be read says, one line each. */
export function SourceProblems(props: { problems: string[] }) {
  const { t } = useWords();
  const said = useContext(CardSaid).toLowerCase();
  if (props.problems.length === 0) return null;
  // A card says each thing once: a source the card's own sentence already names ("Your calendar couldn't be read ...") is not
  // listed again; the button to Connections stays.
  const own = (problem: string) => said !== "" && said.includes(problem.replace(/ couldn't be read\.$/, "").toLowerCase());
  const listed = props.problems.filter((problem) => !own(problem));
  return (
    <>
      {listed.length > 0 && (
        <ul className="plain-list" data-source-problems="">
          {listed.map((problem) => (
            <li key={problem} className="source-problem" role="alert">
              {problem}
            </li>
          ))}
        </ul>
      )}
      <ButtonLink size="sm" href={viewHref(settingsView("connections"))} data-source-problems-open="">
        {t("sources.rail_open")}
      </ButtonLink>
    </>
  );
}

/** Source names are only worth showing when rows come from more than one source. */
export function useSourceNames(sources: string[]): (id: string) => string {
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const many = new Set(sources).size > 1;
  const names = new Map((watch.data ?? []).map((s) => [s.id, s.label]));
  return (id) => (many ? (names.get(id) ?? "") : "");
}
