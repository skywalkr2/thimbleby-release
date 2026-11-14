import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp, typeMoment } from "../test-utils";
import { MoveForm } from "./EventActs";

// Moving a meeting's start moves its end with it, so the meeting keeps its length (the browser test follows the whole path through the
// Schedule's pane; this is the form's own rule, which every place that moves a meeting shares).

const noop = async () => undefined;

test("changing the start moves the end by the same time, so the length stays", async () => {
  const user = userEvent.setup();
  renderApp(<MoveForm start="2026-11-12T17:00" end="2026-11-12T18:15" go="Move it" onCancel={() => undefined} onSubmit={noop} />);
  await typeMoment(user, screen.getByLabelText("Starts"), "2026-11-12T19:00");
  expect(screen.getByLabelText("Ends")).toHaveValue("Nov 12, 2026");
  expect(screen.getAllByLabelText("Time of day")[1]).toHaveValue("8:15 PM");
  // Into another day: the end goes with it.
  await typeMoment(user, screen.getByLabelText("Starts"), "2026-11-13T09:00");
  expect(screen.getByLabelText("Ends")).toHaveValue("Nov 13, 2026");
  expect(screen.getAllByLabelText("Time of day")[1]).toHaveValue("10:15 AM");
});

test("a meeting with no end keeps none when its start moves, and an end the person typed is theirs", async () => {
  const user = userEvent.setup();
  renderApp(<MoveForm start="2026-11-12T17:00" end="" go="Move it" onCancel={() => undefined} onSubmit={noop} />);
  await typeMoment(user, screen.getByLabelText("Starts"), "2026-11-12T19:00");
  expect(screen.getAllByLabelText("Time of day")[1]).toHaveValue("");
});
