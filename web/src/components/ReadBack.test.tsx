import { vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { besidePane, fakeApi, renderApp } from "../test-utils";
import { HeldDetail } from "./HeldDetail";
import { WhatChanged } from "./WhatChanged";

// A rule the person stated shows its read-back beside Undo; a rule that contradicts one in force asks which wins.
beforeEach(() => besidePane());
afterEach(() => vi.unstubAllGlobals());

const back = (over: Partial<S["ReadBackView"]> = {}): S["ReadBackView"] => ({
  applies: {
    everywhere: false,
    targets: [{ kind: "action", kind_label: "action", field: "project" }],
    filter: [],
    projects: [{ id: "PRJ-1", name: "Launch reading" }],
    except: [],
    people: [],
    task_kinds: [],
  },
  unchanged: [{ why: "field", kind: "note", kind_label: "note", field: "project" }],
  overlaps: [{ id: "RULE-3", name: "names-a-project", text: "Every to-do names a project." }],
  count: 2,
  items: [
    { kind: "action", id: "ACT-1", title: "Send the interior file" },
    { kind: "action", id: "ACT-2", title: "Agree the cover copy" },
  ],
  matches_nothing: false,
  ...over,
});

function change(op: Partial<S["OpView"]>): S["ChangeItem"] {
  return {
    id: "REQ-1",
    version: 2,
    dismissed: false,
    stage_task: false,
    first_go: false,
    refused: false,
    state: "review",
    waiting: null,
    created_at: "2026-10-09T14:00:00Z",
    note: null,
    source: null,
    source_title: "A note",
    changeset: {
      id: "CS-1",
      summary: "",
      status: op.status === "held" ? "held" : "applied",
      reviewed: false,
      trust: "trusted",
      ops: [{ index: 0, op: "rule.add", status: "applied", reason: null, group: "op0", title: "Add the rule: every to-do says who it is for", meta: {}, ...op } as S["OpView"]],
    },
  };
}

test("a rule stated in a note shows the four lines and Undo, each overlapping rule linked and the items behind the count", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET changes": () => [change({ read_back: back() })],
    "POST changesets/CS-1/undo": () => ({ restored: [0], skipped: [] }),
  });
  renderApp(<WhatChanged />);
  const lines = await screen.findByRole("region", { name: "What this rule does" });
  const row = (name: string) => within(lines).getByText(name).closest("div")!;
  expect(row("Applies to")).toHaveTextContent("to-do project, in Launch reading");
  expect(row("Doesn't change")).toHaveTextContent("note project");
  expect(within(row("Overlaps with")).getByRole("link", { name: "Every to-do names a project." }).getAttribute("href")).toMatch(/#records\/rule\/RULE-3$/);
  expect(row("Right now it would change")).toHaveTextContent("2 open items");
  await user.click(within(lines).getByRole("button", { name: "Show the items" }));
  expect(within(lines).getByRole("link", { name: "Agree the cover copy" })).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: /More actions for Add the rule/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Undo this" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST changesets/CS-1/undo")?.body).toEqual({ ops: [0] }));
});

test("a rule that matches nothing now says so in words, and one about no record says nothing is counted", async () => {
  fakeApi({ "GET changes": () => [change({ read_back: back({ count: 0, items: [], matches_nothing: true }) })] });
  const view = renderApp(<WhatChanged />);
  const lines = await screen.findByRole("region", { name: "What this rule does" });
  expect(lines).toHaveTextContent("Nothing: no open item matches it right now");
  view.unmount();
  fakeApi({ "GET changes": () => [change({ read_back: back({ count: null, items: [], overlaps: [], unchanged: [] }) })] });
  renderApp(<WhatChanged />);
  const prose = await screen.findByRole("region", { name: "What this rule does" });
  expect(prose).toHaveTextContent("Nothing to count");
  expect(prose).toHaveTextContent("No other rule");
});

const HELD: S["HeldAsk"] = { ask: "contradiction", item: "A to-do never needs a project.", against: ["Every to-do names a project."], record: "RULE-3" };
const line = { changeset: "CS-1", op: 0, request: "REQ-1", title: null, waiting: "contradicts a rule you already have", held: HELD };

test("a held contradiction asks which rule wins: the new one retires the old and Undo takes both back", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET changes": () => [change({ status: "held", reason: "contradicts a rule you already have", held: HELD, read_back: back() })],
    "POST changesets/CS-1/ops/0/rule-answer": () => ({ ok: "CS-1", retired: "CS-9" }),
    "POST changesets/CS-1/ops/0/unrelease": () => ({ restored: [0], skipped: [] }),
    "POST changesets/CS-9/undo": () => ({ restored: [0], skipped: [] }),
  });
  renderApp(<HeldDetail line={line} />);
  await screen.findByRole("region", { name: "What this rule does" });
  expect(screen.getByText("Every to-do names a project.", { selector: "dd" })).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "Use the new rule" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST changesets/CS-1/ops/0/rule-answer")?.body).toEqual({ choice: "new", applies_to: null }));
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-9/undo")).toBe(true));
  expect(calls.some((c) => c.route === "POST changesets/CS-1/ops/0/unrelease")).toBe(true);
});

test("a held contradiction can keep the old rule, keep both, or narrow the new one first", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET changes": () => [change({ status: "held", reason: "x", held: HELD, read_back: back({ applies: { ...back().applies, projects: [] } }) })],
    "GET projects": () => [{ id: "PRJ-1", name: "Launch reading" }, { id: "PRJ-2", name: "Print run" }],
    "POST changesets/CS-1/ops/0/decline": () => ({ ok: "CS-1", request: null }),
    "POST changesets/CS-1/ops/0/rule-answer": () => ({ ok: "CS-1", retired: null }),
  });
  renderApp(<HeldDetail line={line} />);
  await user.click(await screen.findByRole("button", { name: "Keep the old rule" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-1/ops/0/decline")).toBe(true));
  await user.click(await screen.findByRole("button", { name: "Keep both" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST changesets/CS-1/ops/0/rule-answer")?.body).toEqual({ choice: "both", applies_to: null }));
  await user.click(await screen.findByRole("button", { name: "Narrow the new one" }));
  await user.click(await screen.findByRole("checkbox", { name: "Print run" }));
  await user.click(screen.getByRole("button", { name: "Save limits" }));
  await waitFor(() => {
    const sent = calls.filter((c) => c.route === "POST changesets/CS-1/ops/0/rule-answer").map((c) => c.body as { applies_to: { projects: string[] } });
    expect(sent.at(-1)?.applies_to.projects).toEqual(["PRJ-2"]);
  });
});
