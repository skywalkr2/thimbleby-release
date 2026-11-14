// The page's ready mark: the main region carries `data-ready` (holding the address it is ready at) while the screen's first reads
// have answered and no write or screen load is pending, and loses it while one is. Until a screen is first ready, a read that
// already has its data (the refresh the event stream asks for when it connects) is not waited for: on a busy machine it restarts
// before it ends, and the screen is complete without it. Once the screen is ready, a read again (the refresh after a write)
// holds the mark until it answers, so the mark means the page shows what was just written. A test, or anything else that must
// wait for the screen, waits for the mark instead of a number of seconds. One hook, used once by the app shell; screens do nothing.
import { useIsFetching, useIsMutating, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

let pending = 0;
let epoch = 0;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

/** Counts one request in flight; the returned function ends it. Every write through the API client and every screen load does this;
 * reads go through the query cache (see `firstRead`). */
export function trackRequest(): () => void {
  pending += 1;
  // The mark comes off at once, not when React next draws, so a wait that starts right after the click that sent this does not see it.
  if (typeof document !== "undefined") document.getElementById("main")?.removeAttribute("data-ready");
  changed();
  let ended = false;
  return () => {
    if (ended) return;
    ended = true;
    pending -= 1;
    changed();
  };
}

// The reads that are not the mark's to wait for, by client: those already on their way when the screen became ready, and those
// the event stream started for a change somebody else made. Another person's (or another window's) writes can come as fast as
// the screen reads, and a mark that waited for each would be off for as long as they go on; the screen is complete without them.
const leaving = new WeakMap<QueryClient, Set<string>>();
const leavingOf = (client: QueryClient) => {
  let held = leaving.get(client);
  if (!held) {
    const set = (held = new Set<string>());
    leaving.set(client, set);
    // A read that starts again (this page's own write reading its screens, which restarts one already on its way) is the mark's to wait for.
    client.getQueryCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "fetch") set.delete(event.query.queryHash);
    });
  }
  return held;
};

/** Called right after the event stream started reads for a change that is not this page's own write: they do not hold the mark. */
export function leaveFetching(client: QueryClient): void {
  const held = leavingOf(client);
  for (const query of client.getQueryCache().findAll({ fetchStatus: "fetching" })) held.add(query.queryHash);
  // The mark counts its reads again now that some are left out.
  epoch += 1;
  changed();
}

/** A read that has nothing to show yet: the screen always waits for it. */
const firstRead = (query: { state: { data: unknown } }) => query.state.data === undefined;

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const requestsPending = () => pending;
const leftEpoch = () => epoch;

const onHash = (listener: () => void) => {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
};
const hashNow = () => location.hash;

/** The address the screen is ready at: set when nothing is being read or written and has stayed so for one turn of the event loop, so a read that the
 * answer just started (a part that draws only after its parent's data) is seen before the screen is called ready. */
export function useReady(): string | null {
  const client = useQueryClient();
  // The address the screen was last ready at: from then on, every read counts, not only the first ones, except the re-reads that
  // were already on their way when it became ready (the refresh that came with the stream), which are left to end by themselves.
  const settled = useRef<string | null>(null);
  const left = leavingOf(client);
  const hash = useSyncExternalStore(onHash, hashNow);
  const counts = (query: { state: { data: unknown }; queryHash: string }) => firstRead(query) || (settled.current === hash && !left.has(query.queryHash));
  const fetching = useIsFetching({ predicate: counts });
  const mutating = useIsMutating();
  const requests = useSyncExternalStore(subscribe, requestsPending);
  useSyncExternalStore(subscribe, leftEpoch);
  const idle = fetching === 0 && mutating === 0 && requests === 0;
  const [ready, setReady] = useState<string | null>(null);
  // A re-read that has ended is counted again the next time it starts.
  useEffect(
    () =>
      client.getQueryCache().subscribe((event) => {
        if (event.type === "updated" && event.query.state.fetchStatus === "idle") left.delete(event.query.queryHash);
      }),
    [client, left],
  );
  useEffect(() => {
    // A new address starts the wait again: its screen has not drawn yet, whatever was ready before.
    setReady(null);
    if (!idle) return;
    const timer = setTimeout(() => {
      const quiet = client.isFetching({ predicate: counts }) === 0 && client.isMutating() === 0 && pending === 0;
      if (quiet) {
        settled.current = hash;
        left.clear();
        leaveFetching(client);
      }
      setReady(quiet ? hash : null);
    }, 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `counts` only reads the address and the ref, both current when the timer runs
  }, [idle, hash, client]);
  return ready;
}

/** Marks the main region. It is mounted inside the screen's own boundary, so it starts again for each screen and takes the mark off
 * when the screen goes. */
export function ReadyMark(): null {
  const ready = useReady();
  useEffect(() => {
    const main = document.getElementById("main");
    if (!main) return;
    if (ready !== null) main.setAttribute("data-ready", ready);
    else main.removeAttribute("data-ready");
  }, [ready]);
  useEffect(() => () => document.getElementById("main")?.removeAttribute("data-ready"), []);
  return null;
}
