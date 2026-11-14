// Live updates: the server's event stream says when anything changed, and only the queries that change affects refresh.
// No polling. The browser's own offline and online events count too, so a lost connection shows within moments.
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { EVENTS_PATH } from "./api";
import { AuthEventSource } from "./event-stream";
import { leaveFetching } from "./ready";

export type LiveState = "connecting" | "live" | "offline";

/** How long a lost stream is given to come back (the browser retries by itself) before the app says it is offline. */
export const RETRY_BEFORE_OFFLINE_MS = 3000;
/** The longest "connecting" lasts: with no hello by then the app says it is offline, so the state always ends. */
export const CONNECT_LIMIT_MS = 10000;
/** When the browser says the network is gone and the app is served from this computer, the server is asked once, and
 * once more after this long, before the app says offline: a server on this computer answers whatever the network does. */
export const PROBE_RETRY_MS = 1500;
/** How often a stream the browser gave up on is opened afresh while the app is not connected. */
export const REOPEN_MS = 1500;

/** Whether the app is served from this computer. The browser's own online state says nothing about a server on the same
 * computer, so for such an app only the stream itself decides (a Wi-Fi change must not look like a broken app). */
export function servedHere(hostname: string = typeof location === "undefined" ? "" : location.hostname): boolean {
  const name = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return name === "localhost" || name.endsWith(".localhost") || name === "::1" || /^127(\.\d{1,3}){3}$/.test(name);
}

// A family is the first part of a query's key ("today"), or its first two parts ("today/queue") when only that one of the family
// shows the kind. What an assistant's request or change touches is the queue's lines, the list of changes, what waits, the status,
// the plugin's lines and the stage requests; Today's agenda and mail that arrived, and the stage records, don't show it.
const CHANGES = ["changes", "waiting", "handled", "brief", "notifications-waiting", "request-accounts", "asks", "plugin-today", "stages/requests", "status", "jobs", "today/queue", "text-review", "learned"];
// A source's own record also shows as mail that arrived, and its pages and records.
const SOURCES = ["changes", "waiting", "source", "handled", "request-accounts", "asks", "plugin-today", "stages", "status", "jobs", "today", "text-review", "learned"];
/** What was learned: the card lines, the review lists and Today's lines for them. */
const LEARNING = ["learned", "proposals", "catch-up", "changes", "today", "record"];
const FOLLOWUPS = ["followups", "open-items", "brief", "notifications-waiting", "record-page", "waiting", "today", "status", "plugin-today", "changes"];
const FILES = ["files", "text", "working-copies", "text-review", "file-kinds", "changes", "record", "plugin-today"];
const PLUGIN = ["plugin-today", "panels", "panel-rows", "panel-document", "record", "kind", "stages", "plugin-actions", "text", "working-copies", "today", "changes"];

/** The query families each kind of record affects (the first part of their keys). */
const AFFECTS: Record<string, string[]> = {
  request: CHANGES,
  changeset: CHANGES,
  run: CHANGES,
  source: SOURCES,
  signal: CHANGES,
  lesson: LEARNING,
  glossary_entry: LEARNING,
  routing_entry: LEARNING,
  style_note: LEARNING,
  rule: LEARNING,
  question: FOLLOWUPS,
  action: FOLLOWUPS,
  fact: ["notes", "changes", "today", "record", "record-page", "projects"],
  note: ["notes", "changes", "today", "record", "record-page", "projects"],
  person: ["people", "followups", "waiting", "today", "me", "setup", "organizations", "record", "record-page"],
  team: ["people", "organizations", "followups", "record", "record-page"],
  organization: ["organizations", "people", "record", "record-page"],
  project: ["projects", "business", "followups", "waiting", "today", "stages", "panels", "setup", "record", "record-page", "notes"],
  // What waits to go out (a message, an entry, a file): its screen, Today's lines for it and what changed.
  act: ["acts", "changes", "status"],
  file: FILES,
  working_copy: FILES,
  text_version: FILES,
  answer: ["asks", "status", "changes"],
  setting_proposal: ["asks", "status"],
  report: ["asks", "status"],
  job_run: ["jobs", "watch", "today", "status", "setup", "sync"],
  watch_run: ["watch", "watch-kinds", "waiting", "today", "status", "sign-ins", "jobs"],
  tool_run: ["jobs", "status", "files", "working-copies"],
  snapshot: ["status", "sync", "setup", "waiting"],
  setting_change: ["settings", "status", "setup", "panels", "today", "lists", "ai-accounts", "ai-endpoints", "watch", "packs", "runtime-config", "reminder-where", "notifications-waiting", "brief"],
  value_list: ["lists", "settings", "people", "projects"],
  // The audit trail has no screen yet, so writing an entry refreshes nothing.
  audit_entry: [],
  // Opening the list of what changed since yesterday clears Today's line for it. The list itself is kept as it was drawn.
  look: ["today"],
  // Opening a screen with a count of what is new there clears that count.
  screen_look: ["waiting"],
};

/** Whether a query belongs to one of the families: by the first part of its key, or by its first two ("today/queue"). */
export function inFamilies(key: readonly unknown[], wanted: ReadonlySet<string>): boolean {
  const first = String(key[0]);
  return wanted.has(first) || (key.length > 1 && wanted.has(`${first}/${String(key[1])}`));
}

/** Every family some kind of record names. */
const MAPPED: ReadonlySet<string> = new Set(Object.values(AFFECTS).flat().concat(PLUGIN));

/** Whether no kind of record names this query's family, so a write can't say whether it changed what the query shows. */
export function unmapped(key: readonly unknown[]): boolean {
  return !inFamilies(key, MAPPED);
}

/** Whether a query reads again after a change to these families: one of them, or a query no kind of record names, which
 * reads again after every change rather than staying stale. */
export function readsAgain(key: readonly unknown[], wanted: ReadonlySet<string>): boolean {
  return inFamilies(key, wanted) || unmapped(key);
}

/** The query keys' first parts to refresh for the kinds of record written, or null to refresh everything: an empty list
 * means something other than a record changed (a setting, a source's state), and a kind this table doesn't know is not
 * guessed at. A plugin's own kind (it has a slash) refreshes the plugin's screens. */
export function familiesFor(kinds: readonly string[]): string[] | null {
  if (!kinds.length) return null;
  const families = new Set<string>();
  for (const kind of kinds) {
    const known = AFFECTS[kind] ?? (kind.includes("/") ? PLUGIN : null);
    if (!known) return null;
    for (const family of known) families.add(family);
  }
  return [...families];
}

/** The ledger position a "changed" event's data says it announces up to, or null when it names none. */
export function positionOf(data: string): number | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === "object" && "position" in parsed && typeof parsed.position === "number") return parsed.position;
  } catch {
    // A bare number, or anything else, names no position.
  }
  return null;
}

/** What a "changed" event's data says: the kinds written, or null when it names none (an older server sends a number). */
export function kindsOf(data: string): string[] | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === "object" && "kinds" in parsed && Array.isArray(parsed.kinds)) {
      return parsed.kinds.filter((k): k is string => typeof k === "string");
    }
  } catch {
    // A bare number, or anything else, means everything may have changed.
  }
  return null;
}

/** How long after the person's own write the stream's echo of it is not read again for a screen the write is still reading. */
export const OWN_WRITE_WINDOW_MS = 1500;
interface OwnRefresh {
  at: number;
  kinds: ReadonlySet<string>;
  /** Where the ledger stood when the server answered the write, or null when it did not say. */
  position: number | null;
  /** The query families the write reads again, or null when it reads everything. */
  families: ReadonlySet<string> | null;
}
const ownRefreshes = new WeakMap<QueryClient, OwnRefresh>();

/** Records that a write of this app just answered and is about to read its screens again. */
export function noteOwnRefresh(client: QueryClient, kinds: readonly string[], now: number = Date.now(), position: number | null = null, families: readonly string[] | null = familiesFor(kinds)): void {
  ownRefreshes.set(client, { at: now, kinds: new Set(kinds), position, families: families ? new Set(families) : null });
}

// The stream may tell of a write before the write's own answer reaches the page. An event that comes while a write of this app is
// out is held until the write answers (or the window passes), so it can be told from another writer's change.
const writesOut = new WeakMap<QueryClient, { count: number; held: { data: string; timer: ReturnType<typeof setTimeout> }[] }>();

/** A write of this app has been sent and has not answered. */
export function writeSent(client: QueryClient): void {
  const out = writesOut.get(client) ?? { count: 0, held: [] };
  out.count += 1;
  writesOut.set(client, out);
}

/** The write answered (or failed), and its own refresh was noted: the events held meanwhile are told apart from it now. */
export function writeAnswered(client: QueryClient): void {
  const out = writesOut.get(client);
  if (!out) return;
  out.count = Math.max(0, out.count - 1);
  if (out.count > 0) return;
  const held = out.held.splice(0);
  for (const h of held) {
    clearTimeout(h.timer);
    applyEvent(client, h.data);
  }
}

/** Refreshes the queries an event's data says it affects, or all of them when it doesn't say. An event that only repeats
 * what the person's own write just wrote is not read again: the write's own reads came after its answer. */
export function invalidateFor(client: QueryClient, data: string): void {
  const out = writesOut.get(client);
  if (out && out.count > 0) {
    const entry = { data, timer: setTimeout(() => {
      const at = out.held.indexOf(entry);
      if (at >= 0) out.held.splice(at, 1);
      applyEvent(client, data);
    }, OWN_WRITE_WINDOW_MS) };
    out.held.push(entry);
    return;
  }
  applyEvent(client, data);
}

/** An event that only repeats the kinds the person's own write just wrote leaves alone a query that is reading right now (the
 * write's own refresh), so a write is not read twice at once. A query already refreshed is read again: the assistant may have
 * written the same kind meanwhile, and a read that started before that would otherwise stay on screen. A read that returns the
 * same data redraws nothing. Any other kind always reads.
 *
 * The one exception is exact: the server says where the ledger stood when it answered the write, and where an event's news
 * ends. An event that ends no later, and names only screens the write read again, announces nothing the write's reads (made
 * after its answer) missed, so even a read that has finished is not repeated. Anything past that position is another writer's
 * change and reads. */
function applyEvent(client: QueryClient, data: string): void {
  const kinds = kindsOf(data) ?? [];
  const families = familiesFor(kinds);
  const wanted = families ? new Set(families) : null;
  const own = ownRefreshes.get(client);
  const echo = own !== undefined && kinds.length > 0 && Date.now() - own.at < OWN_WRITE_WINDOW_MS && kinds.every((k) => own.kinds.has(k));
  const position = positionOf(data);
  const covered =
    own !== undefined &&
    Date.now() - own.at < OWN_WRITE_WINDOW_MS &&
    own.position !== null &&
    position !== null &&
    position <= own.position &&
    (own.families === null || (wanted !== null && [...wanted].every((f) => own.families?.has(f))));
  if (covered) return;
  void client.invalidateQueries({
    predicate: (query) => {
      if (wanted && !readsAgain(query.queryKey, wanted)) return false;
      if (echo && query.state.fetchStatus === "fetching") return false;
      return true;
    },
  });
  // A change this page did not make: its reads are not what the ready mark waits for. The page's own write just before it (the echo)
  // is read by that write, which counts.
  if (!echo) leaveFetching(client);
}

/** `hellos` counts how many times the stream has (re)connected, so a caller can wait for the next one. */
export function useLive(): { state: LiveState; lastUpdate: Date | null; hellos: number; refresh: () => void; reconnect: () => void } {
  const client = useQueryClient();
  const [state, setState] = useState<LiveState>(() => (typeof navigator !== "undefined" && navigator.onLine === false && !servedHere() ? "offline" : "connecting"));
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [hellos, setHellos] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const source = useRef<AuthEventSource | null>(null);
  /** Set when a stream that was working fails: the next "connecting" is a retry, with the shorter time. */
  const lost = useRef(false);

  useEffect(() => {
    if (typeof fetch === "undefined") return;
    const stream = new AuthEventSource(EVENTS_PATH);
    source.current = stream;
    stream.addEventListener("hello", () => {
      lost.current = false;
      setState("live");
      setHellos((n) => n + 1);
      setLastUpdate(new Date());
      void client.invalidateQueries();
      leaveFetching(client);
    });
    stream.addEventListener("changed", (event) => {
      setLastUpdate(new Date());
      invalidateFor(client, event.data);
    });
    // A lost stream is retried before the state changes: the browser reconnects by itself, and the timer below ends
    // "connecting" in the offline line when nothing comes back.
    stream.onerror = () => {
      lost.current = true;
      setState((cur) => (cur === "live" ? "connecting" : cur));
    };
    return () => stream.close();
  }, [client, attempt]);

  // "Connecting" always ends: in live (the hello) or, after the limit, in offline. A lost stream gets the shorter retry time.
  useEffect(() => {
    if (state !== "connecting") return;
    const limit = lost.current ? RETRY_BEFORE_OFFLINE_MS : CONNECT_LIMIT_MS;
    lost.current = false;
    const timer = setTimeout(() => setState("offline"), limit);
    return () => clearTimeout(timer);
  }, [state]);

  // While not connected, a stream the browser gave up on (closed) is opened afresh, so coming back needs no click.
  useEffect(() => {
    if (state === "live") return;
    const timer = setInterval(() => {
      if (source.current?.readyState === 2) setAttempt((n) => n + 1);
    }, REOPEN_MS);
    return () => clearInterval(timer);
  }, [state]);

  useEffect(() => {
    let gone = false;
    const reachable = async () => {
      try {
        await fetch("api/status", { cache: "no-store", credentials: "same-origin" });
        return true; // any answer, an error status included, means the server is there
      } catch {
        return false;
      }
    };
    const goOffline = () => {
      if (!servedHere()) {
        setState("offline");
        return;
      }
      void (async () => {
        if (await reachable()) return;
        await new Promise((resolve) => setTimeout(resolve, PROBE_RETRY_MS));
        if (!gone && !(await reachable())) setState("offline");
      })();
    };
    const goOnline = () => {
      setState("connecting");
      // A stream the server closed does not retry by itself; a fresh one is opened.
      if (source.current?.readyState === 2) setAttempt((n) => n + 1);
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    // The connection may already have been lost before this ran.
    if (navigator.onLine === false) goOffline();
    return () => {
      gone = true;
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  const refresh = useCallback(() => {
    setLastUpdate(new Date());
    void client.invalidateQueries();
  }, [client]);

  /** Opens the event stream afresh, for "Try now" while the connection is down. */
  const reconnect = useCallback(() => {
    setState((cur) => (cur === "offline" && typeof navigator !== "undefined" && navigator.onLine === false && !servedHere() ? cur : "connecting"));
    setAttempt((n) => n + 1);
  }, []);

  return { state, lastUpdate, hellos, refresh, reconnect };
}
