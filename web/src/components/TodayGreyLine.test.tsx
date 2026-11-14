import "@testing-library/jest-dom/vitest";
import { cleanup, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { namesAFolder, repeatsTitle } from "../lib/grey-line";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture } from "../test-utils";
import { Today } from "./Today";

// The grey line under each row's title says why or when, then the side, then the source; never a folder, and never words the title
// already says (design 7.7). One check over every kind of line Today can draw, each with the parts that fill its words.

type Line = S["QueueLineView"];

const DAY = "2026-10-27";
const AT = "2026-10-27T14:30:00+00:00";
const make = (kind: Line["kind"], over: Partial<Line> = {}): Line => {
  const group: Line["group"] = ["decision", "question", "who_is", "owner", "held", "go", "first_go", "restart", "catch_up_go", "intake_go", "sent_folder", "folder_rename", "work_access", "identity", "pack_tier", "invitation", "guests", "tie", "attention", "called_off", "called_off_todos"].includes(kind)
    ? "decide"
    : ["review", "intake_review", "batches", "batch_item", "rule_review", "learned", "catch_up", "unfiled", "terms", "stale", "needs_date", "pattern", "answer", "since_yesterday", "meeting_prep", "meeting_capture", "area"].includes(kind)
      ? "review"
      : ["send", "nudge", "reply", "sent_check", "quiet_promise", "escalate"].includes(kind)
        ? "send"
        : "risk";
  return { key: `${kind}:1`, group, kind, count: 2, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over };
};

const FILLED: Line[] = [
  make("decision", { text: "Matte or soft-touch?", question: "Q-1", due: DAY, person_name: "Pat Sample" }),
  make("question", { text: "Which printer should we use for the run?", question: "Q-2" }),
  make("who_is", { text: "R. Devlin" }),
  make("owner", { text: "Send the index to the printer", due: DAY }),
  make("first_go", { estimate_usd: 0.5 }),
  make("restart", { count: 1, waiting: "A setting changed" }),
  make("stuck", { waiting_since: AT }),
  make("failed", { count: 1, waiting: "The account refused the key" }),
  make("paused", { text: "main", account: "main", until: AT, waiting: "Resets at 4:00 PM", count: 3 }),
  make("offline", { waiting: "No network", waiting_since: AT, count: 3 }),
  make("overdue", { count: 3, subject: "Proof the chapter" }),
  make("promise", { text: "Send the proofs", due: DAY, person_name: "Pat Sample" }),
  make("reminder", { text: "Call the printer", due: DAY }),
  make("reply", { text: "Thanks for the proofs", person_name: "Pat Sample" }),
  make("account_check", { account: "backup-account", tier: "routine", model: "m1" }),
  make("switch_failed", { text: "main", account: "other", tier: "routine", count: 2 }),
  make("sent_folder", { account: "avery.lane@example.com", count: 1 }),
  make("sent_folder", { key: "sent_folder:many", count: 3, names: ["a@example.com", "b@example.com", "c@example.com"] }),
  make("folder_rename", { text: "workspace" }),
  make("model_watch", { account: "main", names: ["routine"], state: "newer" }),
  make("identity", { account: "agent", text: "agent@example.com", state: "changed" }),
  make("work_access", { account: "main" }),
  make("credential", { credential_kind: "account", credential_name: "main", waiting_days: 3, places: ["the main account"] }),
  make("no_account", { group: "setup", tier: "routine", names: ["routine"], count: 1 }),
  make("pack_tier", { tier: "writer", subject: "Writing", text: "routine" }),
  make("backup", { group: "setup", state: "unset" }),
  make("backup", { key: "backup:2", state: "overdue", age_hours: 52 }),
  make("extractor", { text: "Scanned pages can't be read", file_kind: "pdf" }),
  make("source_unread", { subject: "Inbox", problem_kind: "auth", waiting_since: AT, count: 1 }),
  make("review", { count: 3, subject: "Spring book" }),
  make("rule_review", { count: 2 }),
  make("learned", { count: 2 }),
  make("catch_up", { count: 4 }),
  make("send", { person_name: "Robin Sample", count: 2, questions: ["Q-2"], actions: ["ACT-2"] }),
  make("nudge", { person_name: "Robin Sample", waiting_days: 3, count: 1 }),
  make("escalate", { text: "Is the index final?", person_name: "Robin Sample", waiting_days: 5 }),
  make("stale", { subject: "Old idea", count: 1 }),
  make("needs_date", { count: 3 }),
  make("capacity", { count: 2, minutes: 90, needed_minutes: 240, due: DAY }),
  make("clash", { text: "Supplier call", other: "Fitting appointment", state: "overlap", minutes: 30, due: DAY, starts: AT, ends: AT, other_starts: AT, other_ends: AT, count: 2 }),
  make("tie", { text: "Call the printer", other: "Printer call", due: DAY }),
  make("guests", { text: "Venue walk-through", names: ["Pat Sample"], due: DAY }),
  make("attention", { text: "mail", state: "quiet", count: 3 }),
  make("unfiled", { count: 3 }),
  make("since_yesterday", { count: 5 }),
  make("invitation", { text: "Spring launch", due: DAY }),
  make("meeting_prep", { text: "Venue walk-through", at: AT }),
  make("meeting_capture", { text: "Budget check-in", at: AT, event: "EVT-1" }),
  make("called_off", { text: "Budget check-in", at: AT, event: "EVT-1", count: 2 }),
  make("quiet_promise", { text: "Send the proofs", person_name: "Pat Sample", waiting_days: 9, due: DAY, state: "to" }),
  make("date_reminder", { text: "Passport renewal", due: DAY }),
  make("answer", { text: "Matte" }),
  make("pattern", { text: "Rounding up", state: "moved", count: 2 }),
  make("terms", { count: 2 }),
  make("area", { text: "Garden" }),
];

function titleAndGrey(row: HTMLElement): { title: string; grey: string } {
  const title = row.querySelector("[data-row-title]")?.textContent ?? "";
  const grey = Array.from(row.querySelectorAll("[data-row-title] ~ p")).map((p) => p.textContent ?? "").join(" ");
  return { title, grey };
}

afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
  cleanup();
});

it("no grey line under a row repeats a run of three words from its title or names a folder", async () => {
  const found: string[] = [];
  for (let i = 0; i < FILLED.length; i += 12) {
    const lines = FILLED.slice(i, i + 12).map((l, n) => ({ ...l, key: `${l.kind}:${i + n}` }));
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    fakeApi({
      "GET today/queue": () => lines,
      "GET changes": () => [],
      "GET followups": () => [],
      "GET plugin-today": () => [],
      "GET stages/records": () => [],
      "GET stages/ready": () => [],
      "GET stages/requests": () => [],
      "GET today/agenda": () => [],
      "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
      "GET today/week": () => ({ first: DAY, last: DAY, due: [], waiting: [], meetings: [] }),
      "GET setup": () => ({ finished: true, steps: [], settled: 0, total: 0 }),
      "GET watch": () => [],
      "GET projects": () => [],
      "GET status": () => statusFixture({}, { assistant: { last_run_at: "2026-10-20T08:00:00Z" } }),
      "GET runtime-config": () => ({ instance: null }),
    });
    renderApp(
      <RestartProvider hellos={1}>
        <Today workspace="Workspace" onView={vi.fn()} onAddSource={vi.fn()} onOpenGuide={vi.fn()} onOpenRecord={vi.fn()} shortcuts={{ next: "j", previous: "k" }} />
      </RestartProvider>,
    );
    await waitFor(() => expect(document.querySelectorAll("[data-queue-line]").length).toBe(lines.length));
    for (const row of document.querySelectorAll<HTMLElement>("[data-queue-line]")) {
      const { title, grey } = titleAndGrey(row);
      if (!grey) continue;
      if (repeatsTitle(grey, title)) found.push(`${row.dataset.queueLine}: "${title}" / "${grey}" repeats the title`);
      if (namesAFolder(grey)) found.push(`${row.dataset.queueLine}: "${grey}" names a folder`);
    }
    cleanup();
    forgetLine();
  }
  expect(found).toEqual([]);
}, 120_000);
