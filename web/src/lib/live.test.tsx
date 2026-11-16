import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { CONNECT_LIMIT_MS, PROBE_RETRY_MS, REOPEN_MS, RETRY_BEFORE_OFFLINE_MS, familiesFor, familiesOf, inFamilies, invalidateFor, kindsOf, servedHere, unmapped, useLive } from "./live";

test("each kind of record names the queries it affects", () => {
  expect(familiesFor(["request", "changeset"])).toEqual(expect.arrayContaining(["changes", "today/queue", "stages/requests", "plugin-today"]));
  // A request or change is not shown by Today\'s agenda, the mail that arrived or the stage records; a source is shown by them.
  expect(familiesFor(["request", "changeset", "signal"])).not.toContain("today");
  expect(familiesFor(["request", "changeset", "signal"])).not.toContain("stages");
  expect(familiesFor(["source"])).toEqual(expect.arrayContaining(["today", "stages"]));
  expect(familiesFor(["question"])).toEqual(expect.arrayContaining(["followups", "today"]));
  expect(familiesFor(["action"])).toEqual(expect.arrayContaining(["followups", "today"]));
  expect(familiesFor(["person"])).toEqual(expect.arrayContaining(["people"]));
  expect(familiesFor(["organization"])).toEqual(expect.arrayContaining(["organizations"]));
  expect(familiesFor(["project"])).toEqual(expect.arrayContaining(["projects"]));
  expect(familiesFor(["person"])).not.toContain("changes");
  // A plugin's own kind refreshes the plugin's screens.
  expect(familiesFor(["demo/goal"])).toEqual(expect.arrayContaining(["panel-rows", "plugin-today"]));
});

test("a correction and what was learned from it refresh the lines under cards and the review lists", () => {
  expect(familiesFor(["signal"])).toEqual(expect.arrayContaining(["learned"]));
  for (const kind of ["lesson", "glossary_entry", "routing_entry", "style_note", "rule"]) {
    expect(familiesFor([kind])).toEqual(expect.arrayContaining(["learned", "proposals", "catch-up", "today"]));
  }
});

test("no kinds, or a kind nobody knows, means refresh everything", () => {
  expect(familiesFor([])).toBeNull();
  expect(familiesFor(["person", "something_new"])).toBeNull();
});

test("an event's data is read as kinds, and a bare number names none", () => {
  expect(kindsOf('{"version": 3, "kinds": ["request", "changeset"]}')).toEqual(["request", "changeset"]);
  expect(kindsOf('{"version": 3, "kinds": []}')).toEqual([]);
  expect(kindsOf("7")).toBeNull();
  expect(kindsOf("not json")).toBeNull();
});

function seeded() {
  const client = new QueryClient();
  for (const key of ["changes", "followups", "people", "projects", "settings"]) client.setQueryData([key], []);
  const stale = () => Object.fromEntries(["changes", "followups", "people", "projects", "settings"].map((k) => [k, client.getQueryState([k])!.isInvalidated]));
  return { client, stale };
}

test("an event invalidates only the queries its kinds affect", () => {
  const { client, stale } = seeded();
  invalidateFor(client, '{"version": 2, "kinds": ["person"]}');
  expect(stale()).toEqual({ changes: false, followups: true, people: true, projects: false, settings: false });
});

test("a screen no kind of record names reads again after any change, so it is never left stale", () => {
  const client = new QueryClient();
  for (const key of [["people"], ["projects"], ["held"], ["promise", "p1"]]) client.setQueryData(key, []);
  invalidateFor(client, '{"version": 2, "kinds": ["person"]}');
  expect(client.getQueryState(["people"])!.isInvalidated).toBe(true);
  expect(client.getQueryState(["projects"])!.isInvalidated).toBe(false); // named by other kinds, and not by this one
  expect(client.getQueryState(["held"])!.isInvalidated).toBe(true);
  expect(client.getQueryState(["promise", "p1"])!.isInvalidated).toBe(true);
  expect([unmapped(["held"]), unmapped(["people"]), unmapped(["today", "queue"])]).toEqual([true, false, false]);
});

test("Handled for you reads again when mail is handed in or set aside", () => {
  const client = new QueryClient();
  client.setQueryData(["handled", "set-aside", null, "", null, null], []);
  client.setQueryData(["handled", "counts"], {});
  invalidateFor(client, '{"version": 2, "kinds": ["request"]}');
  expect(client.getQueryState(["handled", "set-aside", null, "", null, null])!.isInvalidated).toBe(true);
  expect(client.getQueryState(["handled", "counts"])!.isInvalidated).toBe(true);
  expect(familiesFor(["source"])).toContain("handled");
});

test("an empty or unknown kind list, and an older server's bare number, invalidate everything", () => {
  for (const data of ['{"version": 2, "kinds": []}', '{"version": 2, "kinds": ["mystery"]}', "5"]) {
    const { client, stale } = seeded();
    invalidateFor(client, data);
    expect(Object.values(stale()).every(Boolean)).toBe(true);
  }
});

// The stream is read by `AuthEventSource` (event-stream.test.ts); here it is a stand-in whose events the test sends.
const stand = vi.hoisted(() => {
  class FakeSource {
    static last: FakeSource | null = null;
    readyState = 0;
    onerror: (() => void) | null = null;
    listeners = new Map<string, (event: unknown) => void>();
    constructor(public url: string) {
      FakeSource.last = this;
    }
    addEventListener(name: string, fn: (event: unknown) => void) {
      this.listeners.set(name, fn);
    }
    close() {
      this.readyState = 2;
    }
  }
  return { FakeSource };
});
vi.mock("./event-stream", () => ({ AuthEventSource: stand.FakeSource }));
const { FakeSource } = stand;

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Runs `body` as a page served from `hostname`. */
function servedFrom(hostname: string, body: () => void) {
  const real = window.location;
  Object.defineProperty(window, "location", { configurable: true, value: { ...real, hostname } });
  try {
    body();
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: real });
  }
}

test("only an address on this computer counts as served here", () => {
  for (const name of ["localhost", "app.localhost", "127.0.0.1", "127.1.2.3", "::1", "[::1]"]) expect(servedHere(name)).toBe(true);
  for (const name of ["example.com", "192.168.1.5", "127.example.com", ""]) expect(servedHere(name)).toBe(false);
});

test("the stream's hello makes it live, and for a hosted app the browser going offline shows at once", () => {
  servedFrom("app.example.com", () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
    expect(result.current.state).toBe("connecting");
    act(() => FakeSource.last!.listeners.get("hello")!({}));
    expect(result.current.state).toBe("live");
    expect(result.current.hellos).toBe(1);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current.state).toBe("offline");
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current.state).toBe("connecting");
    act(() => FakeSource.last!.listeners.get("hello")!({}));
    expect(result.current.state).toBe("live");
  });
  vi.unstubAllGlobals();
});

test("an app served on this computer stays connected when the browser says the network is gone but the server answers", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  const real = window.location;
  Object.defineProperty(window, "location", { configurable: true, value: { ...real, hostname: "localhost" } });
  try {
    const client = new QueryClient();
    const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
    act(() => FakeSource.last!.listeners.get("hello")!({}));
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(fetch).toHaveBeenCalled();
    expect(result.current.state).toBe("live");
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: real });
  }
  vi.unstubAllGlobals();
});

test("an app served on this computer says offline only after the server fails to answer twice", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
  const real = window.location;
  Object.defineProperty(window, "location", { configurable: true, value: { ...real, hostname: "127.0.0.1" } });
  try {
    const client = new QueryClient();
    const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
    act(() => FakeSource.last!.listeners.get("hello")!({}));
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current.state).toBe("live"); // one failed try is not enough
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PROBE_RETRY_MS);
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe("offline");
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: real });
    vi.useRealTimers();
  }
  vi.unstubAllGlobals();
});

test("a lost stream is retried first and shows offline only when nothing comes back in time", () => {
  vi.useFakeTimers();
  const client = new QueryClient();
  const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
  act(() => FakeSource.last!.listeners.get("hello")!({}));
  act(() => FakeSource.last!.onerror!());
  expect(result.current.state).toBe("connecting");
  act(() => {
    vi.advanceTimersByTime(RETRY_BEFORE_OFFLINE_MS - 1);
  });
  expect(result.current.state).toBe("connecting");
  act(() => FakeSource.last!.listeners.get("hello")!({}));
  expect(result.current.state).toBe("live");
  act(() => FakeSource.last!.onerror!());
  act(() => {
    vi.advanceTimersByTime(RETRY_BEFORE_OFFLINE_MS);
  });
  expect(result.current.state).toBe("offline");
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("connecting always ends: with no hello it becomes offline, and a closed stream is opened afresh meanwhile", () => {
  vi.useFakeTimers();
  const client = new QueryClient();
  const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
  const first = FakeSource.last!;
  expect(result.current.state).toBe("connecting");
  first.readyState = 2; // the browser gave up on this stream
  act(() => {
    vi.advanceTimersByTime(REOPEN_MS);
  });
  expect(FakeSource.last).not.toBe(first);
  act(() => {
    vi.advanceTimersByTime(CONNECT_LIMIT_MS);
  });
  expect(result.current.state).toBe("offline");
  act(() => FakeSource.last!.listeners.get("hello")!({}));
  expect(result.current.state).toBe("live");
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("coming back online opens a new stream when the old one closed", () => {
  const client = new QueryClient();
  const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
  const first = FakeSource.last!;
  act(() => first.onerror!());
  first.readyState = 2;
  act(() => {
    window.dispatchEvent(new Event("online"));
  });
  expect(FakeSource.last).not.toBe(first);
  expect(result.current.state).toBe("connecting");
  vi.unstubAllGlobals();
});

test("a changed event refreshes by kind and updates the time", () => {
  const { client, stale } = seeded();
  const { result } = renderHook(() => useLive(), { wrapper: wrapper(client) });
  act(() => FakeSource.last!.listeners.get("changed")!({ data: '{"version": 4, "kinds": ["question"]}' }));
  expect(stale().followups).toBe(true);
  expect(stale().people).toBe(false);
  expect(result.current.lastUpdate).not.toBeNull();
  vi.unstubAllGlobals();
});

test("a family names a whole screen's queries by the first part of their key, or one of them by its first two parts", () => {
  const changeFamilies = new Set(familiesFor(["request", "changeset"]) ?? []);
  expect(inFamilies(["today", "queue"], changeFamilies)).toBe(true);
  expect(inFamilies(["today", "agenda"], changeFamilies)).toBe(false);
  expect(inFamilies(["today", "arrived"], changeFamilies)).toBe(false);
  expect(inFamilies(["stages", "requests"], changeFamilies)).toBe(true);
  expect(inFamilies(["stages", "records"], changeFamilies)).toBe(false);
  expect(inFamilies(["changes"], changeFamilies)).toBe(true);
  expect(inFamilies(["today", "agenda"], new Set(["today"]))).toBe(true);
});

test("news of a later change of the same kind, arriving while a screen re-reads after the person's own write, reads it again", async () => {
  // After Go, the app's worker writes the first lines moments after the person's own write; their news came while Today
  // was still reading for that write, was taken for its echo, and Today kept the read that had none of the lines.
  const { noteOwnRefresh } = await import("./live");
  const client = new QueryClient();
  let calls = 0;
  // Today watches its queue and already shows lines, as the screen does: a watched query with data reads again when
  // it is invalidated, even while a read is out.
  client.setQueryData(["today", "queue"], 0);
  const watching = new QueryObserver(client, {
    queryKey: ["today", "queue"],
    queryFn: () => new Promise<number>((resolve) => setTimeout(() => resolve(++calls), 30)),
  });
  const stop = watching.subscribe(() => undefined);
  await new Promise((r) => setTimeout(r, 5)); // its read is out now
  noteOwnRefresh(client, ["request"], Date.now(), 5);
  invalidateFor(client, '{"version": 2, "kinds": ["request"], "position": 9}');
  await new Promise((r) => setTimeout(r, 120));
  stop();
  expect(calls).toBeGreaterThan(1);
});

test("the echo of the person's own write, at or before its answered place, still reads nothing again", async () => {
  const { noteOwnRefresh } = await import("./live");
  const client = new QueryClient();
  client.setQueryData(["today", "queue"], 1);
  noteOwnRefresh(client, ["request"], Date.now(), 5, null); // the write read everything again
  invalidateFor(client, '{"version": 2, "kinds": ["request"], "position": 5}');
  expect(client.getQueryState(["today", "queue"])!.isInvalidated).toBe(false);
});

test("a change that wrote no record and names its screens reads only those, never everything", () => {
  const { client, stale } = seeded();
  invalidateFor(client, '{"version": 4, "kinds": [], "position": 9, "families": ["setup", "today"]}');
  expect(familiesOf('{"kinds": [], "families": ["setup"]}')).toEqual(["setup"]);
  expect(familiesOf("7")).toBeNull();
  // Settings, people and the rest of the record screens stay as they were: a step of setup changed none of them.
  expect(stale()).toEqual({ changes: false, followups: false, people: false, projects: false, settings: false });
});

test("a change that names no screens still reads everything", () => {
  const { client, stale } = seeded();
  invalidateFor(client, '{"version": 5, "kinds": [], "position": 9}');
  expect(Object.values(stale()).every(Boolean)).toBe(true);
});
