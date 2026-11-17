// The wait after Mail and calendar (design 7.8): the assistant's first reading at work, in plain words, with about how long it
// takes. It moves on to People by itself when the reading is done, and has a way on while it works (the reading keeps going).
// Nothing is waited for when mail was left out or there is no AI account.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../lib/api";
import { useContinue } from "../lib/walkthrough-continue";
import { useWords } from "../lib/wording";
import { Icon } from "../ui/Icon";
import { Skeleton } from "../ui/Skeleton";

/** How often the reading is looked at while it works. */
const LOOK_EVERY_MS = 2000;

export function WalkthroughReading(props: {
  /** The reading was done, and the person came here by going forward: go on to the next screen. */
  onDone: () => void;
  /** Whether a finished reading moves on by itself (not when the person came back to look at it). */
  autoAdvance: boolean;
}) {
  const { t, tn } = useWords();
  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: api.setup,
    refetchInterval: (q) => (q.state.data?.reading.state === "working" ? LOOK_EVERY_MS : false),
  });
  const reading = setup.data?.reading;
  const state = reading?.state;
  const moved = useRef(false);
  useContinue({ run: async () => true, label: state === "working" ? t("walkthrough.reading.go_on") : undefined, quiet: state === "working" });
  useEffect(() => {
    if (state === "done" && props.autoAdvance && !moved.current) {
      moved.current = true;
      props.onDone();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, props.autoAdvance]);
  if (!reading) return <Skeleton rows={2} />;
  if (reading.state === "none") {
    return (
      <p className="hint" data-reading="none">
        {t(`walkthrough.reading.none.${reading.why ?? "no_mail"}`)}
      </p>
    );
  }
  if (reading.state === "done") {
    return (
      <p className="what" data-reading="done">
        <Icon name="check" size={16} /> {t("walkthrough.reading.done")}
      </p>
    );
  }
  const stage = reading.stage ?? "fetching";
  return (
    <div data-reading="working" data-stage={stage}>
      <p className="what" role="status">
        {stage === "fetching" ? t("walkthrough.reading.fetching", { read: reading.read, sources: reading.sources }) : t(`walkthrough.reading.${stage}`)}
      </p>
      {reading.found > 0 && <p className="hint">{tn("walkthrough.reading.found", reading.found)}</p>}
      <p className="hint">{t("walkthrough.reading.how_long")}</p>
    </div>
  );
}
