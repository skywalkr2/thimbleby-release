// The Done tab of To-dos (design 7.13, S-0428, answer 2): the last days' finished to-dos, newest first, grouped by day, each saying who
// closed it, with "Not done after all" to reopen it, and "Older ones are in search" at the end; the tab has no count.
import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { addDays, todayOn } from "../lib/dates";
import { person, project } from "../lib/records-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { OpenItems } from "./OpenItems";
import { byDay } from "./DoneList";

const today = todayOn(new Date());
const done = (id: string, text: string, over: Partial<S["DoneActionView"]> = {}): S["DoneActionView"] => ({
  id,
  version: 4,
  text,
  closed_at: `${today}T15:00:00+00:00`,
  day: today,
  closed_by: "you",
  done_by: [],
  reported_by: null,
  reason: null,
  source_kind: null,
  notice: null,
  source_by: null,
  source_day: null,
  origin: null,
  project: "PRJ-1",
  project_name: "Harbor",
  side_name: null,
  side: null,
  views: [],
  ...over,
});

const finished = [
  done("A-1", "Pay the deposit"),
  done("A-2", "Send the signed sheet", { closed_by: "assistant", reason: "I sent it back on Tuesday", source_kind: "reply", source_by: "Quinn Sample", source_day: addDays(today, -1), origin: { kind: "source", source: "SRC-1" }, day: addDays(today, -1), closed_at: `${addDays(today, -1)}T10:00:00+00:00` }),
  done("A-3", "Return the form", { done_by: ["Robin Sample"], day: addDays(today, -3), closed_at: `${addDays(today, -3)}T10:00:00+00:00` }),
];

function api(extra: Routes = {}, rows = finished) {
  return fakeApi({
    "GET open-items": () => ({ actions: [], questions: [], stale_days: 21, rows_shown: 15 }),
    "GET open-items/done": () => ({ actions: rows, days: 30 }),
    "GET people": () => [person("P-1", "Quinn Sample")],
    "GET projects": () => [project("PRJ-1", "Harbor")],
    "POST actions/A-2/status": () => ({ ok: "A-2", request: null }),
    ...extra,
  });
}

async function openDone() {
  const user = userEvent.setup();
  renderApp(<OpenItems />);
  await user.click(await screen.findByRole("button", { name: "Done" }));
  return user;
}

test("the tab lists what was finished by day, newest first, and each row says who closed it", async () => {
  api();
  await openDone();
  const list = await screen.findByRole("list", { name: "Finished to-dos" });
  const days = within(list).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(days[0]).toBe("Today");
  expect(days[1]).toBe("Yesterday");
  expect(days).toHaveLength(3);
  const rows = Array.from(list.querySelectorAll<HTMLElement>("[data-done-item]"));
  expect(rows.map((r) => r.textContent)).toEqual([
    expect.stringContaining("Pay the deposit"),
    expect.stringContaining("Send the signed sheet"),
    expect.stringContaining("Return the form"),
  ]);
  expect(rows[0]).toHaveTextContent("Done by you");
  // The assistant's close says its name and the words it quoted; a close credited to somebody else names them.
  expect(rows[1]).toHaveTextContent(/^Send the signed sheetClosed by Helper · Quinn Sample replied on /);
  expect(rows[2]).toHaveTextContent("Done by Robin Sample");
  expect(screen.getByText("Older ones are in search.")).toBeInTheDocument();
  // No row holds a quotation mark or any of the message's words until it is opened.
  expect(list.textContent).not.toMatch(/[“”"]/);
  expect(list.textContent).not.toContain("I sent it back on Tuesday");
});

test("opening a row the assistant closed shows the exact words in quotation marks, whose they are, and the way to the message", async () => {
  api();
  const user = await openDone();
  const row = (await screen.findByText("Send the signed sheet")).closest<HTMLElement>("[data-done-item]")!;
  await user.click(within(row).getByRole("button", { name: "Show the words" }));
  expect(within(row).getByText("“I sent it back on Tuesday”")).toBeInTheDocument();
  expect(row).toHaveTextContent(/From Quinn Sample's reply, /);
  expect(within(row).getByRole("button", { name: "Not done after all: Send the signed sheet" })).toBeInTheDocument();
  await user.click(within(row).getByRole("button", { name: "Hide the words" }));
  expect(row.textContent).not.toContain("I sent it back on Tuesday");
});

test("a notice, a meeting and a close with no input named each say only what the app holds", async () => {
  const rows = [
    done("A-1", "Pay the printer", { closed_by: "assistant", reason: "Your bill is paid.", source_kind: "notice", notice: "bill", source_day: addDays(today, -2) }),
    done("A-2", "Book the room", { closed_by: "assistant", reason: "It is over.", source_kind: "calendar", source_day: addDays(today, -2) }),
    done("A-3", "Call the venue", { closed_by: "assistant", reason: "Done.", source_kind: null }),
  ];
  api({}, rows);
  await openDone();
  const list = await screen.findByRole("list", { name: "Finished to-dos" });
  const items = Array.from(list.querySelectorAll<HTMLElement>("[data-done-item]"));
  expect(items[0]).toHaveTextContent(/Closed by Helper · the payment notice on /);
  expect(items[1]).toHaveTextContent("Closed by Helper · the meeting has passed");
  expect(items[2]).toHaveTextContent("Closed by Helper · today");
  expect(list.textContent).not.toMatch(/[“”"]/);
});

test("the Done tab has no count, though the other tabs do", async () => {
  const open = { id: "A-9", version: 1, text: "Tidy the shelf", state: "open", owners: [{ person: "P-1", name: "Quinn Sample" }], due: null, project: "PRJ-1", project_name: "Harbor", parent_name: null, notes: null, since: "2026-10-01", on_hold: null, blocker: null, duplicate: null, origin: null, untouched_days: null, owner_question: null, to_send: false, needs_you: true };
  api({ "GET open-items": () => ({ actions: [open], questions: [], stale_days: 21, rows_shown: 15 }) });
  renderApp(<OpenItems />);
  const tab = await screen.findByRole("button", { name: "Done" });
  expect(tab.textContent).toBe("Done");
  expect(await screen.findByRole("button", { name: /^To-dos/ })).toHaveTextContent("1");
});

test("Not done after all reopens it at once, from the row, and says so with Undo", async () => {
  const calls = api();
  const user = await openDone();
  const row = (await screen.findByText("Send the signed sheet")).closest<HTMLElement>("[data-done-item]")!;
  await user.click(within(row).getByRole("button", { name: "Not done after all: Send the signed sheet" }));
  await waitFor(() => expect(calls.filter((c) => c.route === "POST actions/A-2/status").pop()?.body).toEqual({ status: "open" }));
  expect(await screen.findByText("Back on your list: Send the signed sheet")).toBeInTheDocument();
});

test("with nothing finished in the window the tab says so, and the window is the setting's", async () => {
  api({ "GET open-items/done": () => ({ actions: [], days: 14 }) });
  await openDone();
  expect(await screen.findByText("Nothing was finished in the last 14 days.")).toBeInTheDocument();
});

test("with nothing open, See what you finished opens the Done tab", async () => {
  api();
  renderApp(<OpenItems />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "See what you finished" }));
  expect(await screen.findByRole("list", { name: "Finished to-dos" })).toBeInTheDocument();
});

test("rows are grouped by the day they were closed, keeping the order they came in", () => {
  const rows = [done("A-1", "a"), done("A-2", "b"), done("A-3", "c", { day: "2026-10-01" })];
  expect(byDay(rows).map((g) => [g.day, g.rows.map((r) => r.id)])).toEqual([
    [today, ["A-1", "A-2"]],
    ["2026-10-01", ["A-3"]],
  ]);
});
