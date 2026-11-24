import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

type Line = S["QueueLineView"];

const line = (kind: Line["kind"], over: Partial<Line> = {}): Line => ({
  key: kind,
  group: "review",
  kind,
  count: 1,
  untrusted: false,
  unpriced: 0,
  actions: [],
  questions: [],
  outcome: {},
  ...over,
});

function show(lines: Line[], extra: Routes = {}, onView = vi.fn()) {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
  const calls = fakeApi({
    "GET today/queue": () => lines,
    "GET changes": () => [],
    "GET followups": () => [],
    "GET plugin-today": () => [],
    "GET stages/records": () => [],
    "GET stages/ready": () => [],
    "GET stages/requests": () => [],
    "GET today/agenda": () => [],
    "GET today/todo": () => [],
    "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
    "GET watch": () => [],
    "GET projects": () => [],
    "GET people": () => [],
    "GET status": () => statusFixture({}, { assistant: { last_run_at: "2026-10-20T08:00:00Z" } }),
    "GET runtime-config": () => ({ instance: null }),
    ...extra,
  });
  const onOpenRecord = vi.fn();
  renderApp(
    <RestartProvider hellos={1}>
      <Today workspace="Workspace" onView={onView} onAddSource={vi.fn()} onOpenGuide={vi.fn()} onOpenRecord={onOpenRecord} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
  );
  return { calls, onOpenRecord, onView };
}

afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
});

const row = (key: string) => document.querySelector<HTMLElement>(`[data-line-key="${key}"]`)!;

// Rows with two answers (design 7.7, UI/UX review S-0733, S-0737, S-0740): one button for the change the assistant suggests, always the
// last in the row, the other answer a plain text button just before it, never a second button of the same weight; a status word that only
// repeats the group's header is left off; the lines of many people to send are one.

const buttons = (found: HTMLElement) => within(found).getAllByRole("button").filter((b) => !/More actions/.test(b.getAttribute("aria-label") ?? ""));

test("a stale to-do's one button is Drop it, with Keep it a plain button before it", async () => {
  show([line("stale", { key: "stale:A-1", group: "review", count: 1, actions: ["A-1"], waiting_days: 30, subject: "Tidy the style sheet", choices: ["keep", "drop", "snooze"] })]);
  await screen.findByText("Decide whether you are still doing: Tidy the style sheet");
  const [other, primary] = buttons(row("stale:A-1"));
  expect(other).toHaveTextContent("Keep it");
  expect(other).toHaveAttribute("data-variant", "quiet");
  expect(primary).toHaveTextContent("Drop it");
  expect(primary).toHaveAttribute("data-key", "primary");
});

test("a held drop that tells people is never the filled button, and Keep it stays before it", async () => {
  show([
    line("held", {
      key: "held:CS-1:1",
      group: "decide",
      changeset: "CS-1",
      op: 1,
      text: "Drop 'Confirm the seating plan'",
      held: { ask: "drop", item: "Confirm the seating plan", record: "ACT-1", owners: [], told: ["Casey Moor"], quote: "no longer needed", reporter: "Robin Sample" },
    }),
  ]);
  await screen.findByText("Drop 'Confirm the seating plan'?");
  const [other, primary] = buttons(row("held:CS-1:1"));
  expect(other).toHaveTextContent("Keep it");
  expect(other).toHaveAttribute("data-variant", "quiet");
  expect(primary).toHaveTextContent("Drop it and tell them");
  expect(primary).not.toHaveAttribute("data-weight", "filled");
});

test("a line with one status word its group already says does not say it again", async () => {
  show([line("review", { key: "review:1", group: "review", count: 2, outcome: { questions: 2 }, request: "REQ-1", changesets: ["CS-1"], changeset: "CS-1" })]);
  const found = await screen.findByRole("group", { name: /Look over/ });
  expect(within(found).queryByText("Review")).toBeNull();
});

test("the lines of many people to send are one line, with the people and items counted, that opens Follow-ups", async () => {
  const user = userEvent.setup();
  const part = (n: number) => line("send", { key: `send:PER-${n}`, group: "send", count: 2, person: `PER-${n}`, person_name: `Person ${n}`, questions: [`Q-${n}`], actions: [`A-${n}`] });
  const { onView } = show([line("sends", { key: "sends", group: "send", count: 6, parts: [part(1), part(2), part(3)], questions: ["Q-1", "Q-2", "Q-3"], actions: ["A-1", "A-2", "A-3"], ready_since: "2020-01-02" })]);
  const found = await screen.findByRole("group", { name: "Send to 3 people (6 items)" });
  expect(within(found).queryByText("Send")).toBeNull();
  await user.click(within(found).getByRole("button", { name: "Review & copy" }));
  expect(onView).toHaveBeenCalledWith("work/followups");
});

test("a follow-up says how long it has waited once", async () => {
  show([line("nudge", { key: "nudge:PER-2", group: "send", person: "PER-2", person_name: "Robin Sample", count: 1, waiting_days: 44, questions: ["Q-1"] })]);
  const found = await screen.findByRole("group", { name: "Follow up with Robin Sample" });
  expect(found.textContent?.match(/44/g)).toHaveLength(1);
});
