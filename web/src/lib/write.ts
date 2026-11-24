// Saving, in one place: writes that name the same thing go out one at a time, what happened is said the moment the server
// answers, and afterwards only the screens that show what was written read again, without anyone waiting for them. A write never refreshes everything unless
// it can name nothing narrower (and that is counted).
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { answeredWrites } from "./api";
import { familiesFor, noteOwnRefresh, readInOrder, readsAgain, writeAnswered, writeSent } from "./live";

export interface WriteOptions<T> {
  /** What is being changed (a record id, or a screen's scope). Writes with the same key go out in order, one at a time. */
  key?: string;
  /** The query families (the first part of query keys) to read again afterwards. */
  touches?: readonly string[];
  /** Query families to read again besides the ones the kinds map to: a screen whose reads no record kind names. */
  also?: readonly string[];
  /** The kinds of record written; the families that show them are read again when `touches` is not given. */
  kinds?: readonly string[];
  /** Names one press of a button or one save of a form. While a write with the same name is out, asking again does nothing (`alreadyOut`); a
   * second press never sends the same change twice. Left out, writes are not told apart. */
  once?: string;
  /** Called the moment the server answers, before any screen reads again: the place to say what was done. */
  answered?: (result: T) => void;
}

/** How many writes could name nothing narrower than everything, since the app started (read by tests and diagnostics). */
export const broadRefreshes = { count: 0 };

const tails = new WeakMap<QueryClient, Map<string, Promise<unknown>>>();
const out = new WeakMap<QueryClient, Map<string, number>>();
const done = new WeakMap<QueryClient, Map<string, number>>();

/** How long after a write answered a second press of it is still the person's own double press. */
const OWN_PRESS_MS = 10_000;

/** Whether a write with this name (`once`) is out and not answered yet: a press of it is then ignored. */
export function alreadyOut(client: QueryClient, once: string): boolean {
  return (out.get(client)?.get(once) ?? 0) > 0;
}

/** How long after a write answered the same press, asked again, is the person's own second press of a double press. */
const DOUBLE_PRESS_MS = 700;

/** Whether a write with this name answered within the time of a double press: a press now is the second press of that one. */
export function justAnswered(client: QueryClient, once: string): boolean {
  const at = done.get(client)?.get(once);
  return at !== undefined && Date.now() - at < DOUBLE_PRESS_MS;
}

/** Whether a write with this name answered a moment ago: a refusal of "changed since you read it" is then the person's own second press. */
export function justDone(client: QueryClient, once: string): boolean {
  const at = done.get(client)?.get(once);
  return at !== undefined && Date.now() - at < OWN_PRESS_MS;
}

function mark(client: QueryClient, once: string, by: 1 | -1): void {
  let names = out.get(client);
  if (!names) out.set(client, (names = new Map()));
  const left = (names.get(once) ?? 0) + by;
  if (left > 0) names.set(once, left);
  else names.delete(once);
}

function noteDone(client: QueryClient, once: string): void {
  let names = done.get(client);
  if (!names) done.set(client, (names = new Map()));
  names.set(once, Date.now());
}

/** Reads again the named families, or everything when there are none to name. */
export function refreshFamilies(client: QueryClient, families: readonly string[] | null | undefined, kinds?: readonly string[], position: number | null = null): Promise<void> {
  if (kinds?.length || position !== null) noteOwnRefresh(client, kinds ?? [], Date.now(), position, families ?? null);
  if (!families) {
    broadRefreshes.count += 1;
    return readInOrder(client, () => true);
  }
  const wanted = new Set(families);
  return readInOrder(client, (query) => readsAgain(query.queryKey, wanted));
}

/** The kinds the server said the writes answered since `since` changed, or null when one of them named nothing. */
export function kindsAnsweredSince(since: number): string[] | null {
  const answered = answeredWrites.entries.filter((e) => e.seq > since);
  if (!answered.length || answered.some((e) => e.kinds === null)) return null;
  return [...new Set(answered.flatMap((e) => e.kinds ?? []))];
}

/** The latest ledger position the writes answered since `since` named, or null when one named none. */
export function positionAnsweredSince(since: number): number | null {
  const answered = answeredWrites.entries.filter((e) => e.seq > since);
  if (!answered.length || answered.some((e) => e.position === null)) return null;
  return Math.max(...answered.map((e) => e.position ?? 0));
}

/** Reads everything again. Only for a change of the whole app that no record names (a sign-in that finished, a part that failed
 * and is tried again); it is counted with the other broad refreshes. */
export function refreshEverything(client: QueryClient): Promise<void> {
  return refreshFamilies(client, null);
}

/** The moment before raw writes, for `refreshSince`. */
export function writeMark(): number {
  return answeredWrites.seq;
}

/** The moment just before the write that answered last: for a step that is told of a write already made (a saved setting). */
export function lastWriteMark(): number {
  return Math.max(0, answeredWrites.seq - 1);
}

/** Reads again what the writes answered since `mark` changed (everything when one named nothing). */
export function refreshSince(client: QueryClient, mark: number): Promise<void> {
  const kinds = kindsAnsweredSince(mark);
  return refreshFamilies(client, kinds?.length ? familiesFor(kinds) : null, kinds ?? undefined, positionAnsweredSince(mark));
}

/** Reads again what the records of the given kinds are shown by. */
export function refreshKinds(client: QueryClient, kinds: readonly string[]): Promise<void> {
  return refreshFamilies(client, familiesFor(kinds), kinds);
}

export function runWrite<T>(client: QueryClient, run: () => Promise<T>, options: WriteOptions<T> = {}): Promise<T> {
  const once = options.once;
  if (once !== undefined) mark(client, once, 1);
  const go = async (): Promise<T> => {
    const since = answeredWrites.seq;
    writeSent(client);
    try {
      const result = await run();
      if (once !== undefined) noteDone(client, once);
      options.answered?.(result);
      // A write that names nothing itself reads again what the server said it changed; one that changed no record reads
      // everything, as before. The reads follow the answer: nothing waits for them, so the next step starts at once.
      const kinds = options.kinds ?? (options.touches ? undefined : (kindsAnsweredSince(since) ?? undefined));
      const named = kinds?.length ? familiesFor(kinds) : null;
      const families = options.touches ?? (named && options.also ? [...new Set([...named, ...options.also])] : named);
      void refreshFamilies(client, families, kinds, positionAnsweredSince(since)).catch(() => undefined);
      return result;
    } finally {
      if (once !== undefined) mark(client, once, -1);
      // The stream's news of this write, if it came first, is told apart from another writer's now that the write's reads are noted.
      writeAnswered(client);
    }
  };
  const key = options.key;
  if (key === undefined) return go();
  let queues = tails.get(client);
  if (!queues) tails.set(client, (queues = new Map()));
  const previous = queues.get(key) ?? Promise.resolve();
  // The next write waits for the previous one's answer, whether it worked or not.
  const mine = previous.then(go, go);
  const tail = mine.catch(() => undefined);
  queues.set(key, tail);
  void tail.then(() => {
    if (queues.get(key) === tail) queues.delete(key);
  });
  return mine;
}

export function useWrite() {
  const client = useQueryClient();
  return useCallback(<T,>(run: () => Promise<T>, options?: WriteOptions<T>) => runWrite(client, run, options), [client]);
}
