// The wait after Mail and calendar (design 7.8): the assistant's first reading at work, in plain words, with about how long it
// takes. It moves on to People by itself when the reading is done, and has a primary "Go on" while it works (the reading keeps going).
// Nothing is waited for when mail was left out or there is no AI account.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../lib/api";
import { waitWhen } from "../lib/olderRead";
import { listOf } from "../lib/packs";
import { useContinue } from "../lib/walkthrough-continue";
import { useWords } from "../lib/wording";
import { RestartLine } from "../shell/HeldLines";
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
  useContinue({ run: async () => true, label: state === "working" ? t("walkthrough.reading.go_on") : undefined });
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
  // What is still being read is named while the list is short ("Still reading: Your sent mail, Work account"), else counted.
  const pending = reading.pending ?? [];
  const fetching =
    pending.length > 0
      ? t("walkthrough.reading.still", { list: listOf(pending, t("walkthrough.mail.reads_join").trim()) })
      : t("walkthrough.reading.fetching", { read: reading.read, sources: reading.sources });
  // A source the mail service asked to wait on is waiting, with its time: not stuck, and the person can go on.
  const waiting = reading.waiting > 0 && reading.until ? tn("walkthrough.reading.waiting_some", reading.waiting, { when: waitWhen(reading.until, t) }) : "";
  return (
    <div data-reading="working" data-stage={stage}>
      {(reading.restart_waits ?? 0) > 0 && (
        <div data-reading-restart="">
          <RestartLine line={{ count: reading.restart_waits }} />
        </div>
      )}
      <p className="what" role="status">
        {stage === "fetching" ? fetching : stage === "waiting" ? waiting : t(`walkthrough.reading.${stage}`)}
      </p>
      {stage === "fetching" && waiting && (
        <p className="hint" data-reading-waiting="">
          {waiting}
        </p>
      )}
      {reading.found > 0 && <p className="hint">{tn("walkthrough.reading.found", reading.found)}</p>}
      <p className="hint">{t("walkthrough.reading.how_long")}</p>
    </div>
  );
}
