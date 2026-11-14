import "@testing-library/jest-dom/vitest";
import { act, cleanup, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { useShortcuts } from "../lib/keys";
import { showNewLines } from "../lib/queue-hold";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

type Line = S["QueueLineView"];

function line(kind: Line["kind"], over: Partial<Line> = {}): Line {
  const group: Line["group"] = ["decision", "question", "who_is", "owner", "held", "go", "first_go", "restart"].includes(kind)
    ? "decide"
    : kind === "review" || kind === "intake_review" || kind === "batches" || kind === "batch_item"
      ? "review"
      : kind === "send" || kind === "nudge"
        ? "send"
        : "risk";
  return { key: `${kind}:1`, group, kind, count: 1, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over };
}


const decision: Line = line("decision", { key: "question:Q-1", text: "Matte or soft-touch?", question: "Q-1", project: "PRJ-1", project_name: "Spring book" });
const send: Line = line("send", { key: "send:PER-2", person: "PER-2", person_name: "Robin Sample", count: 2, questions: ["Q-2"], actions: ["ACT-2"] });

const pm = (questions: S["FollowupQuestion"][] = []): S["FollowupSection"] => ({
  person: "PER-1",
  name: "Pat Example",
  is_pm: true,
  questions,
  actions: [],
  message: "",
  to_send: 0,
});
const decisionQuestion: S["FollowupQuestion"] = {
  id: "Q-1",
  title: "Matte or soft-touch?",
  text: "",
  links: [],
  kind: "decision",
  status: "open",
  sent: null,
  waiting_days: null,
  chase_due: false, chases: 0,
  about: null,
  options: [],
};
const robin: S["FollowupSection"] = {
  person: "PER-2",
  name: "Robin Sample",
  is_pm: false,
  questions: [{ ...decisionQuestion, id: "Q-2", title: "Is the index final?", kind: "question" }],
  actions: [{ id: "ACT-2", text: "Send the index", due: null, project_name: "", told: null, to_send: true, told_days: null, followed_up: null, chase_due: false, chases: 0 }],
  message: "Hi Robin,\n\nIs the index final?",
  to_send: 2,
};

function change(id: string): S["ChangeItem"] {
  return {
    id,
    version: 4,
    dismissed: false,
    stage_task: false,
    first_go: false,
    refused: false,
    state: "review",
    waiting: null,
    created_at: "2026-10-09T14:00:00Z",
    note: null,
    source: null,
    source_title: "Email from Sam Example",
    changeset: {
      id: "CS-1",
      summary: "Three actions.",
      status: "applied",
      reviewed: false,
      trust: "untrusted",
      ops: [{ index: 0, op: "action.add", status: "applied", reason: null, group: "op0", title: "Send two spine options", meta: { owners: [] }, evidence: null, record: { kind: "action", id: "ACT-7" }, ask: null }],
    },
  } as S["ChangeItem"];
}

/** The window's shortcut keys, as the app registers them. */
function Keys() {
  useShortcuts({ next: "j", previous: "k", primary: "a", show_new: "N", next_pane: "]", previous_pane: "[" }, { undo: () => undefined, hand_in: () => undefined, ask: () => undefined, help: () => undefined, show_new: showNewLines });
  return null;
}

const emptyWeek: S["ThisWeekView"] = { first: "2026-10-19", last: "2026-10-23", due: [], waiting: [], meetings: [] };

function show(lines: Line[], extra: Routes = {}, over: { wide?: boolean; unnamed?: boolean } = {}) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: !!over.wide && /min-width: 1680px/.test(query),
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  const calls = fakeApi({
    "GET today/queue": () => lines,
    "GET changes": () => [change("REQ-1")],
    "GET followups": () => [pm([decisionQuestion]), robin],
    "GET plugin-today": () => [],
    "GET stages/records": () => [],
    "GET stages/ready": () => [],
    "GET stages/requests": () => [],
    "GET today/agenda": () => [],
    "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
    "GET today/week": () => emptyWeek,
    "GET setup": () => ({ finished: false, steps: [], settled: 0, total: 3 }),
    "GET watch": () => [],
    "GET projects": () => [],
    // An assistant that has already worked on something: an empty Today then says nothing needs the person.
    "GET status": () => statusFixture({}, { assistant: { last_run_at: "2026-10-20T08:00:00Z" } }),
    "GET runtime-config": () => ({ instance: null }),
    ...extra,
  });
  const onView = vi.fn();
  const onOpenGuide = vi.fn();
  const onHandIn = vi.fn();
  const { client } = renderApp(
    <RestartProvider hellos={1}>
      <Keys />
      <Today workspace="Workspace" onView={onView} onAddSource={vi.fn()} onOpenGuide={onOpenGuide} onHandIn={onHandIn} onOpenRecord={vi.fn()} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
    {},
    { unnamed: over.unnamed },
  );
  /** What the live stream does when something changed elsewhere: the screen asks again. */
  const refresh = () => act(() => client.invalidateQueries());
  return { calls, onView, refresh, onOpenGuide, onHandIn };
}


afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
});

const KINDS: Line["kind"][] = [
  "decision", "question", "who_is", "owner", "held", "go", "first_go", "catch_up_go", "intake_go", "intake_review", "batches", "batch_item",
  "refused", "no_effect", "restart", "stuck", "handover", "failed", "paused", "borrow", "offline", "overdue", "promise", "reminder",
  "reminder_digest", "reply", "sent_check", "account_check", "switch_failed", "account_move", "sent_folder", "folder_rename", "model_watch",
  "model_moved", "identity", "work_access", "credential", "no_account", "pack_tier", "backup", "extractor", "source_unread", "review",
  "rule_review", "learned", "catch_up", "send", "nudge", "escalate", "stale", "needs_date", "capacity", "clash", "tie", "guests", "attention",
  "unfiled", "moved", "since_yesterday", "away", "invitation", "meeting_prep", "meeting_capture", "quiet_promise", "date_reminder", "answer",
  "area", "pattern", "terms", "project_ending", "restore",
];

// U4 P130 (U4-0b): every kind of line, with none of its optional parts (no change, no project, no person, no date, no items),
// is drawn without taking Today down. A kind that cannot be drawn bare is named in the failure.
it("each kind of line with none of its optional parts is drawn, and Today stays", async () => {
  const broke: string[] = [];
  const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
  for (const kind of KINDS) {
    show([line(kind), decision]);
    const stayed = await screen.findByText("Matte or soft-touch?", { selector: "li *" }, { timeout: 3000 }).then(
      () => true,
      () => false,
    );
    if (!stayed) broke.push(kind);
    cleanup();
    forgetLine();
  }
  quiet.mockRestore();
  expect(broke).toEqual([]);
}, 120_000);

// U4 P130: one card missing a field its renderer reads is replaced by a fallback and the rest of Today is drawn.
it("one card missing a field its renderer reads shows a fallback, and the rest of Today is drawn", async () => {
  const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
  // A card whose text is not text (a record from an older or other version): its renderer reads `text.trim()`.
  const broken = { ...decision, key: "question:Q-BAD", text: 5 } as unknown as Line;
  // React reports an error nobody caught to the window; the test takes it so that only the screen's answer is judged.
  const taken = (e: ErrorEvent) => e.preventDefault();
  window.addEventListener("error", taken);
  show([broken, decision, send]);
  try {
    expect(await screen.findByText("Matte or soft-touch?", { selector: "li *" })).toBeInTheDocument();
    expect(await screen.findByText("Send 2 items to Robin Sample")).toBeInTheDocument();
    expect(await screen.findByText(/couldn.t be shown/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  } finally {
    window.removeEventListener("error", taken);
    quiet.mockRestore();
  }
});
