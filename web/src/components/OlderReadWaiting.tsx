// The line under an account that says where a read of its older mail stopped and when it carries on (design 6.32): what was kept so
// far and the time the rest continues, in the person's own words. One line per source whose read waits; nothing when none does. Used
// by the Mail step's account row and the account's card on Connections, so both say the same.
import type { S } from "../lib/api";
import { firstReadLines, onceEach, stopWords } from "../lib/olderRead";
import { useWords } from "../lib/wording";

type Source = S["WatchSourceView"];

export function OlderReadWaiting(props: { sources: Source[] }) {
  const { t, tn } = useWords();
  const each = props.sources.flatMap((s) => {
    const stopped = s.older_read;
    if (!stopped) return [];
    const head = stopped.taken > 0 ? tn("coverage.look_back.done", stopped.taken, { source: s.label }) : "";
    return [[s.id, [head, stopWords({ stopped: stopped.kind, continues_at: stopped.at, gave_up: stopped.gave_up, taken: stopped.taken, about: stopped.about }, t)].filter(Boolean).join(" ")] as const];
  });
  // Two sources in the same state say the same words (the inbox and the sent mail, both queued): the line is said once.
  const waiting = onceEach(each, ([, words]) => words);
  // From sign-in on, what each account's first read is doing, said the same for the first account and the second.
  const first = firstReadLines(props.sources, t);
  return (
    <>
      {first.map((words, i) => (
        <p className="hint" key={words} data-first-read={i === 0 ? "taking" : "waiting"} role="status">
          {words}
        </p>
      ))}
      {waiting.map(([id, words]) => (
        <p className="hint" key={id} data-older-read={id} role="status">
          {words}
        </p>
      ))}
    </>
  );
}
