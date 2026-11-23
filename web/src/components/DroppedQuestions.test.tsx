import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { besidePane, fakeApi, renderApp } from "../test-utils";
import { FollowUps } from "./FollowUps";

beforeEach(() => {
  besidePane();
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const dropped = (over: Partial<S["DroppedQuestionView"]>): S["DroppedQuestionView"] => ({
  id: "Q-1",
  title: "Is the index final?",
  text: "",
  to: "PER-2",
  to_name: "Robin Sample",
  reason: "Robin already told me in the meeting",
  dropped_at: "2026-11-20T10:00:00",
  projects: [],
  origin: null,
  ...over,
});

test("a dropped question is listed under Dropped with who, when and why, and Ask again opens it again with Undo", async () => {
  const user = userEvent.setup();
  // The server lists them newest first.
  let rows = [dropped({ id: "Q-2", title: "Which printer?", reason: null, dropped_at: "2026-11-22T09:00:00" }), dropped({})];
  const calls = fakeApi({
    "GET followups": () => [],
    "GET acts/waiting": () => [],
    "GET people": () => [],
    "GET questions/dropped": () => rows,
    "POST questions/Q-1/ask-again": () => {
      rows = rows.filter((r) => r.id !== "Q-1");
      return { changeset: "CS-1" };
    },
    "POST changesets/CS-1/undo": () => ({ restored: [0], declined: [], skipped: [] }),
  });
  renderApp(<FollowUps />);
  await user.click(await screen.findByRole("button", { name: "Dropped" }));
  const list = await screen.findByRole("list", { name: "Dropped questions" });
  const items = within(list).getAllByRole("listitem");
  // Newest first, each with its title, whom it was for and why it was dropped.
  expect(items[0]).toHaveTextContent("Which printer?");
  expect(items[0]).toHaveTextContent("For Robin Sample");
  expect(items[0]).toHaveTextContent("no reason given");
  expect(items[1]).toHaveTextContent("because Robin already told me in the meeting");
  // One action per row.
  expect(within(items[1]).getAllByRole("button")).toHaveLength(1);
  await user.click(within(items[1]).getByRole("button", { name: "Ask again: Is the index final?" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST questions/Q-1/ask-again")).toBe(true));
  expect(await screen.findByText("Asked again.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("Is the index final?")).toBeNull());
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-1/undo")).toBe(true));
});

test("the Dropped tab is not offered while nothing was dropped", async () => {
  fakeApi({ "GET followups": () => [], "GET acts/waiting": () => [], "GET people": () => [], "GET questions/dropped": () => [] });
  renderApp(<FollowUps />);
  await screen.findByText(/No follow-ups yet/);
  expect(screen.queryByRole("button", { name: "Dropped" })).toBeNull();
});
