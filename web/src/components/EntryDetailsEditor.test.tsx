import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeApi, renderApp } from "../test-utils";
import { EntryEditor } from "./EntryDetailsEditor";

// An entry that runs past midnight can be edited: its end is on the day after its start, so its end time of day is earlier than
// its start, and saving keeps the end on that later day.

const record = {
  kind: "event",
  id: "EVT-1",
  version: 3,
  fields: { id: "EVT-1", title: "Late class", start: "2026-11-10T23:38:00", end: "2026-11-11T00:38:00", where: "", trust: "trusted" },
  long_text: [],
} as never;

test("an entry ending after midnight saves a changed place, and its end stays on the next day", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET projects": () => [],
    "GET sides": () => ({ sides: [], just_me: true }),
    "POST records/edit": () => ({ changeset: "CS-1" }),
  });
  renderApp(<EntryEditor record={record} onClose={() => {}} />);
  expect(screen.queryByText(/before it starts|after it starts/i)).toBeNull();
  await user.type(await screen.findByLabelText("Place"), "The studio");
  const save = screen.getByRole("button", { name: "Save" });
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
  await waitFor(() => expect(calls.find((c) => c.route === "POST records/edit")).toBeDefined());
  expect(calls.find((c) => c.route === "POST records/edit")?.body).toEqual({
    kind: "event",
    id: "EVT-1",
    fields: { where: "The studio" },
    read_version: 3,
  });
});

test("moving the day of an entry that ends after midnight moves its end with it", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET projects": () => [],
    "GET sides": () => ({ sides: [], just_me: true }),
    "POST records/edit": () => ({ changeset: "CS-1" }),
  });
  renderApp(<EntryEditor record={record} onClose={() => {}} />);
  const day = await screen.findByLabelText("Day");
  await user.clear(day);
  await user.type(day, "2026-11-12");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST records/edit")).toBeDefined());
  expect(calls.find((c) => c.route === "POST records/edit")?.body).toMatchObject({
    fields: { start: "2026-11-12T23:38:00", end: "2026-11-13T00:38:00" },
  });
});
