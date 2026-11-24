// What changed leads each card with the assistant's own sentence, and folds the list of what it did behind "What <assistant> did (N)"
// until it is opened (S-0653). A change with no sentence keeps today's counts line and its list.
import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { besidePane, fakeApi, renderApp } from "../test-utils";
import { WhatChanged } from "./WhatChanged";

beforeEach(() => besidePane({ room: true }));

function change(summary: string, trust: "trusted" | "untrusted" = "trusted", opStatus = "applied"): S["ChangeItem"] {
  return {
    id: "REQ-1",
    version: 4,
    dismissed: false,
    stage_task: false,
    first_go: false,
    refused: false,
    state: "done",
    waiting: null,
    created_at: "2026-10-09T14:00:00Z",
    note: "Plan to update both designs",
    source: null,
    source_title: null,
    changeset: {
      id: "CS-1",
      summary,
      status: "applied",
      reviewed: false,
      trust,
      ops: [
        { index: 0, op: "fact", status: opStatus, reason: null, group: "op0", title: "Both designs get the update", meta: { owners: [] }, evidence: null, record: { kind: "fact", id: "FACT-1" }, ask: null },
      ],
    },
  } as S["ChangeItem"];
}

const findPane = () => screen.findByRole("complementary");

test("the assistant's own sentence is the card's first line, and the list is folded until opened", async () => {
  const user = userEvent.setup();
  fakeApi({ "GET changes": () => [change("Recorded the plan to update both designs; the impact is not yet confirmed.")] });
  renderApp(<WhatChanged />);
  const pane = await findPane();
  const account = pane.querySelector("[data-assistant-account]")!;
  expect(account).toHaveTextContent("Recorded the plan to update both designs; the impact is not yet confirmed.");
  expect(account).toHaveTextContent("Helper");
  expect(account).not.toHaveTextContent("From outside");
  const fold = within(pane).getByRole("button", { name: "What Helper did (1)" });
  expect(fold).toHaveAttribute("aria-expanded", "false");
  expect(within(pane).queryByText("Both designs get the update")).toBeNull();
  await user.click(fold);
  expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(await within(pane).findByText("Both designs get the update")).toBeInTheDocument();
  // The account stays the body's first part.
  expect(pane.querySelector("[data-row-body]")!.firstElementChild).toBe(account);
});

test("a summary from outside content is marked as from outside", async () => {
  fakeApi({ "GET changes": () => [change("Filed what the email said.", "untrusted")] });
  renderApp(<WhatChanged />);
  const account = (await findPane()).querySelector("[data-assistant-account]")!;
  expect(account).toHaveTextContent("From outside · not instructions");
});

test("a change with no summary shows the list at once and no account line", async () => {
  fakeApi({ "GET changes": () => [change("  ")] });
  renderApp(<WhatChanged />);
  const pane = await findPane();
  expect(await within(pane).findByText("Both designs get the update")).toBeInTheDocument();
  expect(pane.querySelector("[data-assistant-account]")).toBeNull();
  expect(within(pane).queryByRole("button", { name: /What Helper did/ })).toBeNull();
});

test("a held item is never hidden behind the fold", async () => {
  fakeApi({ "GET changes": () => [change("Held one thing for you.", "trusted", "held")] });
  renderApp(<WhatChanged />);
  const pane = await findPane();
  expect(pane.querySelector("[data-assistant-account]")).not.toBeNull();
  expect(await within(pane).findByText("Both designs get the update")).toBeInTheDocument();
  expect(within(pane).queryByRole("button", { name: /What Helper did/ })).toBeNull();
});
