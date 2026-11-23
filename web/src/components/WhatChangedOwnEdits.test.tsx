import { vi } from "vitest";
// What changed folds the person's own edits of one item on one day into one row that opens to the list of edits; the
// assistant's changes stay one row each (design 7.13; sweep X29).
import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { besidePane, fakeApi, renderApp } from "../test-utils";
import { WhatChanged } from "./WhatChanged";

beforeEach(() => besidePane());
afterEach(() => vi.unstubAllGlobals());

function edit(id: string, name: string, at: string, extra: Partial<S["ChangeItem"]> = {}): S["ChangeItem"] {
  return {
    id,
    version: 2,
    dismissed: false,
    stage_task: false,
    first_go: false,
    refused: false,
    state: "done",
    waiting: null,
    created_at: at,
    note: "Changed on screen",
    source: null,
    source_title: null,
    changeset: {
      id: `CS-${id}`,
      summary: "Changed on screen",
      status: "applied",
      reviewed: true,
      trust: "trusted",
      ops: [{ index: 0, op: "record.edit", status: "applied", reason: null, group: "op0", title: name, meta: {}, record: { kind: "action", id: "ACT-1" }, ask: null }],
    },
    ...extra,
  } as S["ChangeItem"];
}

/** The change of an edit with its one op named `op`, whatever the op's own words. */
const withOp = (id: string, op: string, title: string) => {
  const changeset = edit(id, title, "2026-11-02T10:00:00Z").changeset!;
  return { ...changeset, ops: [{ ...changeset.ops[0], op, title, record: null }] } as S["ChangesetView"];
};

const five = ["REQ-9", "REQ-8", "REQ-7", "REQ-6", "REQ-5"].map((id, i) => edit(id, "Pay the deposit", `2026-11-02T1${5 - i}:00:00Z`));
const folded = { ...five[0], edited: "Pay the deposit", edits: five.map((e) => ({ ...e, edits: [] })) } as S["ChangeItem"];

function show(items: S["ChangeItem"][]) {
  return fakeApi({ "GET changes": () => items, "GET people": () => [], "GET stages/requests": () => [], "GET stages/records": () => [] });
}

test("five edits of one item in a day are one row, and opening it lists the five", async () => {
  show([folded]);
  renderApp(<WhatChanged />);
  await screen.findByRole("button", { name: /^You changed Pay the deposit 5 times/ });
  expect(screen.getAllByRole("button", { name: /You changed/ })).toHaveLength(1);
  // Beside the list the row is chosen, so the detail holds each of the five as a change of its own.
  const detail = await screen.findByText(/Your 5 edits on/);
  expect(screen.getByRole("button", { name: /^You changed Pay the deposit 5 times/ })).toHaveAttribute("aria-expanded", "true");
  const user = userEvent.setup();
  const pane = detail.closest("ol")!;
  expect(within(pane).getAllByRole("listitem").filter((li) => li.hasAttribute("data-changeset"))).toHaveLength(5);
  await user.click(within(pane).getAllByRole("button", { name: /More actions/ })[0]);
  expect(await screen.findByRole("menuitem", { name: /Undo everything/ })).toBeInTheDocument();
});

test("edits on two days are two rows, and an edit alone is a row as before", async () => {
  const day2 = [edit("REQ-4", "Pay the deposit", "2026-11-01T10:00:00Z"), edit("REQ-3", "Pay the deposit", "2026-11-01T09:00:00Z")];
  const folded2 = { ...day2[0], edited: "Pay the deposit", edits: day2.map((e) => ({ ...e, edits: [] })) } as S["ChangeItem"];
  show([{ ...folded, edits: (folded.edits ?? []).slice(0, 3) } as S["ChangeItem"], folded2, edit("REQ-2", "Book the room", "2026-11-01T08:00:00Z")]);
  renderApp(<WhatChanged />);
  expect(await screen.findByRole("button", { name: /^You changed Pay the deposit 3 times/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^You changed Pay the deposit 2 times/ })).toBeInTheDocument();
  expect(screen.queryByText(/You changed Book the room/)).toBeNull();
});

test("a change the assistant made is a row of its own and is not folded", async () => {
  const assistant = edit("REQ-1", "Pay the deposit", "2026-11-02T09:00:00Z", { note: null, source: "SRC-1", source_title: "A message" });
  show([folded, assistant]);
  renderApp(<WhatChanged />);
  await screen.findByRole("button", { name: /^You changed Pay the deposit 5 times/ });
  expect(screen.getByRole("button", { name: /^A message/ })).toBeInTheDocument();
});

test("the people the person took from those offered are one row that says what they did, never that the assistant did", async () => {
  const taken = ["REQ-3", "REQ-2", "REQ-1"].map((id, i) =>
    edit(id, `Added Person ${3 - i}`, `2026-11-02T1${3 - i}:00:00Z`, { own: true, changeset: withOp(id, "person.keep_offer", `Added Person ${3 - i}`) }),
  );
  show([{ ...taken[0], fold: "people_added", edits: taken.map((e) => ({ ...e, edits: [] })) } as S["ChangeItem"]]);
  renderApp(<WhatChanged />);
  await screen.findByRole("button", { name: "You added 3 people" });
  expect(await screen.findByText(/The people you added on/)).toBeInTheDocument();
  expect(screen.queryByText(/did \d things?/)).toBeNull();
  expect(screen.getAllByText(/Added 1 person/).length).toBeGreaterThan(0);
});

test("a change the person made with an op the list has no words for reads as theirs", async () => {
  show([edit("REQ-1", "Pay the deposit", "2026-11-02T09:00:00Z", { own: true, changeset: withOp("REQ-1", "action.retitle", "Pay the deposit") })]);
  renderApp(<WhatChanged />);
  expect(await screen.findByText(/You changed 1 thing/)).toBeInTheDocument();
  expect(screen.queryByText(/did 1 thing/)).toBeNull();
});
