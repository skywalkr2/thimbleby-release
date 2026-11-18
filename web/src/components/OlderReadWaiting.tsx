// The line under an account that says where a read of its older mail stopped and when it carries on (design 6.32): what was kept so
// far and the time the rest continues, in the person's own words. One line per source whose read waits; nothing when none does. Used
// by the Mail step's account row and the account's card on Connections, so both say the same.
import type { S } from "../lib/api";
import { stopWords } from "../lib/olderRead";
import { useWords } from "../lib/wording";

type Source = S["WatchSourceView"];

export function OlderReadWaiting(props: { sources: Source[] }) {
  const { t, tn } = useWords();
  const waiting = props.sources.flatMap((s) => {
    const stopped = s.older_read;
    if (!stopped) return [];
    const head = stopped.taken > 0 ? tn("coverage.look_back.done", stopped.taken, { source: s.label }) : "";
    return [[s.id, [head, stopWords({ stopped: stopped.kind, continues_at: stopped.at, gave_up: stopped.gave_up }, t)].filter(Boolean).join(" ")] as const];
  });
  return (
    <>
      {waiting.map(([id, words]) => (
        <p className="hint" key={id} data-older-read={id} role="status">
          {words}
        </p>
      ))}
    </>
  );
}
