// Rendering components against a fake API: routes map "METHOD path" to a handler that returns the JSON body.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "./lib/api";
import type { ReactNode } from "react";
import { ToastProvider } from "./lib/toasts";
import { WordingProvider } from "./lib/wording";
import { OwnRequestsProvider } from "./components/HandIn";

/** A route's handler gets the request's body and its query. A route written without a query answers the same path with one. */
export type Routes = Record<string, (body: unknown, query?: URLSearchParams) => unknown>;

/** Return this from a route to answer with a refusal, as the server does: a status and its text. */
export class Refuse {
  constructor(
    public status: number,
    public detail: string,
    public headers: Record<string, string> = {},
  ) {}
}

export function fakeApi(routes: Routes) {
  const calls: Array<{ route: string; body: unknown; headers?: HeadersInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^api\//, "");
    const route = `${init?.method ?? "GET"} ${path}`;
    // JSON bodies are parsed for the handler; a file's bytes are passed as they are.
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    calls.push({ route, body, headers: init?.headers });
    const [bare, query] = path.split("?");
    const handler = routes[route] ?? (query !== undefined ? routes[`${init?.method ?? "GET"} ${bare}`] : undefined);
    if (!handler) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    // A handler may answer later (a promise), to stand for a slow server.
    const answer = await handler(body, new URLSearchParams(query ?? ""));
    if (answer instanceof Refuse) return new Response(JSON.stringify({ detail: answer.detail }), { status: answer.status, headers: answer.headers });
    return new Response(JSON.stringify(answer), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function renderApp(ui: ReactNode, overrides: Record<string, string> = {}, options: { unnamed?: boolean; locale?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rendered = render(
    <WordingProvider overrides={overrides} base={{ assistant: "Helper" }} unnamed={options.unnamed} locale={options.locale}>
      <QueryClientProvider client={client}>
        <ToastProvider seconds={0}>
          <OwnRequestsProvider>{ui}</OwnRequestsProvider>
        </ToastProvider>
      </QueryClientProvider>
    </WordingProvider>,
  );
  // The client is returned too, for a test that makes the app fetch again, as the live stream does.
  return Object.assign(rendered, { client });
}

/** A status answer with nothing wrong, for tests to change a part of. */
export function statusFixture(over: Partial<S["Status"]> = {}, parts: { backup?: Partial<S["BackupStatus"]>; spend?: Partial<S["SpendStatus"]>; ai?: S["AiState"]; assistant?: Partial<S["AssistantStatus"]> } = {}): S["Status"] {
  return {
    backup: { configured: false, last_success: null, age_hours: null, needs_attention: false, last_error: null, encrypted: false, ...parts.backup },
    ai: parts.ai ?? { state: "ok", detail: null },
    assistant: { last_run_at: null, last_run_failed: false, runs_today: [], queued: 0, oldest_queued_since: null, chains: [], paused: [], working_count: 0, loop_restarted_at: null, loop_stuck_since: null, ...parts.assistant },
    spend: { today_usd: 0, month_usd: 0, per_day_usd: 2, per_month_usd: 30, warn: false, warn_today: false, warn_month: false, maybe_today_usd: 0, maybe_month_usd: 0, ...parts.spend },
    requests: { queued: 0, running: 0, review: 0, needs_you: 0 },
    version: 1,
    has_stages: false,
    restart_needed: null,
    can_restart: false,
    ...over,
  };
}

/** The runtime configuration a test app starts with. */
export function rcFixture(extra: Partial<S["RuntimeConfig"]> = {}): S["RuntimeConfig"] {
  return {
    api_base: "api",
    assistant_name: "Helper",
    assistant_named: true,
    base_path: "",
    demo: false,
    feedback_to: "feedback@example.com",
    report_enabled: true,
    narrow_below_px: 640,
    logo: false,
    theme: "system",
    density: "comfortable",
    language: "en-US",
    timezone: "UTC",
    pm: null,
    shortcuts: { undo: "u", hand_in: "n", help: "?", ask: "/" },
    toast_seconds: 0,
    toast_undo_seconds: 0,
    request_timeout_seconds: 30,
    long_request_timeout_seconds: 300,
    title_words: 12,
    rail_rows: 3,
    heavy_day_from: 30,
    group_rows: 5,
    twin_window_minutes: 10,
    short_wait_minutes: 5,
    time_format: "auto",
    time_step: 15,
    version: "9.8.7",
    wording: {},
    workspace_name: "Workspace",
    ...extra,
  };
}

/** A moment at :42 past an hour, at least `hours` hours from now: a wait long enough to be said by the time of day. */
export const inHours = (hours: number): string => new Date(Math.ceil((Date.now() + hours * 3_600_000) / 3_600_000) * 3_600_000 + 42 * 60_000).toISOString();

/** The walkthrough screen each core setup step is on, as the server sorts them; any other step is an optional extra. */
const SCREEN_OF: Record<string, S["SetupStepView"]["group"]> = {
  workspace: "you",
  work: "work",
  ai: "ai",
  mail: "mail",
  backup: "backup",
  people: "people",
};

/** A setup step as the server sends it, sorted into its screen the way the server does. */
export function setupStep(id: string, extra: Partial<S["SetupStepView"]> = {}): S["SetupStepView"] {
  return {
    id,
    done: false,
    skipped: false,
    label: "",
    explanation: "",
    action: null,
    plugin: null,
    group: SCREEN_OF[id] ?? "done",
    counted: id in SCREEN_OF,
    place: null,
    reason: null,
    ...extra,
  };
}

/** The setup answer for a list of steps, with the walkthrough closed unless a test says otherwise. */
export function setupView(
  steps: S["SetupStepView"][],
  over: {
    finished?: boolean;
    local?: boolean;
    first_go_waiting?: number;
    first_go_given?: boolean;
    reading?: Partial<S["ReadingView"]>;
    people_by_hand?: boolean;
    sides_later?: boolean;
    walkthrough?: Partial<S["WalkthroughView"]>;
  } = {},
): S["SetupView"] {
  // The server numbers the counted steps and counts the settled ones; the fixtures do the same.
  let place = 0;
  const numbered = steps.map((s) => (s.counted && s.place == null ? { ...s, place: ++place } : s));
  const counted = numbered.filter((s) => s.counted);
  return {
    steps: numbered,
    finished: over.finished ?? false,
    total: counted.length,
    settled: counted.filter((s) => s.done || s.skipped).length,
    local: over.local ?? true,
    first_go_waiting: over.first_go_waiting ?? 0,
    first_go_given: over.first_go_given ?? true,
    reading: { state: "none", why: "no_mail", sources: 0, read: 0, found: 0, waiting: 0, restart_waits: 0, ...over.reading },
    people_by_hand: over.people_by_hand ?? false,
    sides_later: over.sides_later ?? false,
    walkthrough: { open: false, step: "you", closed: false, finished: false, ...over.walkthrough },
  };
}

/** The window is wide enough (1024px or more) for a list's detail to stand beside it, as the list | detail views lay it out.
 * Stubs the media queries; call `vi.unstubAllGlobals()` after the test (the views' tests do it in `afterEach`). */
export function besidePane(): void {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: /min-width:\s*1024px/.test(query), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
}

/**
 * The choices of the app's list to pick from (ui/Select), as a copy of its listbox. The list is a button that opens a panel, so
 * its options are not on the page until it is opened: this opens it, takes a copy of the open listbox (the options with their
 * words, values and selected marks) and closes it again, so a test reads what a list offers the way it read a browser select.
 */
export async function snapshotOf(select: HTMLElement): Promise<HTMLElement> {
  const user = userEvent.setup();
  const open = select.getAttribute("aria-expanded") === "true";
  if (!open) await user.click(select);
  // The panel draws after the click's own render, which on a busy machine can be a moment later.
  const list = await waitFor(() => {
    const found = document.getElementById(select.getAttribute("aria-controls") ?? "");
    if (!found) throw new Error("The list did not open.");
    return found;
  }, { timeout: 3000 });
  const copy = list.cloneNode(true) as HTMLElement;
  // In a fragment of its own, so the names that point at other parts of the list (a group's heading) can be found.
  document.createDocumentFragment().appendChild(copy);
  await user.keyboard("{Escape}");
  return copy;
}

/** The options of a list, in order, as copies (see `snapshotOf`). */
export async function optionsOf(select: HTMLElement): Promise<HTMLElement[]> {
  return Array.from((await snapshotOf(select)).querySelectorAll<HTMLElement>('[role="option"]'));
}

// The app's own date and time boxes (ui/DateField, TimeField) show a day and a time the way the reader's locale writes them and
// are typed into the same way, so a test names them by what a person does: type a day, type a time, read what the box holds.
import { parseDay, parseTime } from "./lib/date-input";
import { todayOn } from "./lib/dates";

/** The ISO day a date box shows ("Oct 28, 2026" is "2026-10-28"); empty when it shows none. */
export function dayValue(box: HTMLElement): string {
  const text = (box as HTMLInputElement).value;
  return text ? (parseDay(text, { today: todayOn(new Date()) }) ?? `unreadable: ${text}`) : "";
}

/** The "HH:MM" a time box shows ("9:30 AM" is "09:30"); empty when it shows none. */
export function timeValue(box: HTMLElement): string {
  const text = (box as HTMLInputElement).value;
  return text ? (parseTime(text) ?? `unreadable: ${text}`) : "";
}

/** The time box beside a date box that has one (a date with a time). */
export const timeBesideDay = (day: HTMLElement): HTMLElement => (day.closest('[data-ui="datetime"]') as HTMLElement).querySelector('[data-kind="time"]') as HTMLElement;

/** The "YYYY-MM-DDTHH:MM" a date-with-time field holds, read from the day box that has the label. */
export function momentValue(day: HTMLElement): string {
  const d = dayValue(day);
  const t = timeValue(timeBesideDay(day));
  return d && t ? `${d}T${t}` : "";
}

/** Types a date and a time ("2026-11-03T14:00") into the two boxes of a date-with-time field, given the day box. */
export async function typeMoment(user: ReturnType<typeof userEvent.setup>, day: HTMLElement, iso: string): Promise<void> {
  const time = timeBesideDay(day);
  await user.clear(day);
  await user.type(day, iso.slice(0, 10));
  await user.clear(time);
  await user.type(time, iso.slice(11, 16));
  await user.tab();
}

/** The headings of the groups a copy of a list holds (see `snapshotOf`), in order. */
export const groupNames = (snapshot: HTMLElement): string[] =>
  Array.from(snapshot.querySelectorAll<HTMLElement>('[role="group"]')).map((g) => snapshot.querySelector(`[id="${g.getAttribute("aria-labelledby")}"]`)?.textContent ?? "");

/** The rows of a list that are things, not the add row, a group's heading or its "Show more". */
export const thingRows = (list: HTMLElement): HTMLElement[] =>
  within(list)
    .getAllByRole("listitem")
    .filter((li) => !li.hasAttribute("data-inline-add") && li.querySelector("ul, ol") === null && li.querySelector("[data-row-menu], a, [data-row]") !== null);

/** `thingRows`, once the list holds at least one. */
export async function findThingRows(list: HTMLElement): Promise<HTMLElement[]> {
  return waitFor(() => {
    const rows = thingRows(list);
    if (rows.length === 0) throw new Error("the list holds no rows yet");
    return rows;
  });
}
