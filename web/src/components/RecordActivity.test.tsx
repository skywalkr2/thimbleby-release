import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { RecordActivity } from "./RecordActivity";

// A screen reader is never told "0 items are open here" (UI/UX review S10): a to-do's own page holds the to-do, and a page with
// nothing open says nothing of a count.

const page = (over: Partial<S["RecordPageView"]> = {}) =>
  ({ kind: "action", id: "ACT-1", name: "Tidy the style sheet", open_actions: [], open_questions: [], completed_actions: [], earlier_occurrences: [], activity: [], facts: [], ...over }) as unknown as S["RecordPageView"];

const count = () => document.querySelector(".sr");

test("a to-do's own page says no count of items open", async () => {
  fakeApi({});
  renderApp(<RecordActivity page={page()} self />);
  expect(screen.queryByText(/items? (is|are) open here/)).toBeNull();
  expect(count()).toBeNull();
});

test("a page with nothing open says no count either", () => {
  fakeApi({});
  renderApp(<RecordActivity page={page()} />);
  expect(screen.queryByText(/items? (is|are) open here/)).toBeNull();
});
