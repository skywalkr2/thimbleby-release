import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { person, project } from "../lib/records-fixtures";
import { besidePane, fakeApi, renderApp, type Routes } from "../test-utils";
import { OpenItems } from "./OpenItems";

// To-dos is list | detail (design 7.13): from 1024px the chosen to-do's page stands beside the list; below it a row opens the page.
afterEach(() => vi.unstubAllGlobals());

// jsdom has no layout: the split is `whole` wide and the pane (or the probe that stands for it) 420px, so ListDetail can tell whether the
// pane fits beside the list (the list keeps at least its `fit`).
function widths(whole: number) {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => whole);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(() => 420);
}
afterEach(() => vi.restoreAllMocks());

const todo = (id: string, text: string): S["OpenActionView"] => ({
  id,
  version: 3,
  text,
  state: "open",
  owners: [{ person: "P-1", name: "Quinn Sample" }],
  due: null,
  project: "PRJ-1",
  project_name: "Harbor",
  parent_name: null,
  notes: null,
  since: "2026-10-01",
  on_hold: null,
  blocker: null,
  duplicate: null,
  origin: null,
  untouched_days: null,
  owner_question: null,
  to_send: false,
  needs_you: true,
});

const rowsOf = [todo("A-1", "Send the proof to the printer"), todo("A-2", "Order the sample copies")];

const page = (id: string, text: string): Routes => ({
  [`GET record?kind=action&id=${id}`]: () => ({ kind: "action", id, version: 3, fields: { id, text, status: "open" }, long_text: [] }),
  [`GET record-pages/${id}?kind=action`]: () => ({ kind: "action", id, version: 3, name: text, details: [], open_actions: [], open_questions: [], completed_actions: [], facts: [], fact_source: null, activity: [] }),
  [`GET promise/${id}`]: () => ({ action: id, version: 3, quote: null, basis: null, promised_to: [], owners: [{ id: "P-1", name: "Quinn Sample" }], due: null, due_words: null, due_check: false, news: [], origin: null }),
  [`GET plugin-actions?kind=action&id=${id}`]: () => [],
  [`GET task-kinds?kind=action&id=${id}`]: () => [],
});

function api() {
  return fakeApi({
    "GET open-items": () => ({ actions: rowsOf, questions: [], stale_days: 21, rows_shown: 15 }),
    "GET people": () => [person("P-1", "Quinn Sample")],
    "GET projects": () => [project("PRJ-1", "Harbor")],
    "GET kinds/action": () => ({ kind: "action", fields: [] }),
    "GET settings": () => ({ fingerprint: "fp", items: [] }),
    "GET lists": () => [],
    "GET organizations": () => [],
    ...page("A-1", rowsOf[0].text),
    ...page("A-2", rowsOf[1].text),
  });
}

test("beside the list the first to-do is chosen as the list opens and shown in the pane, and choosing another shows it", async () => {
  besidePane();
  widths(1200);
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const pane = await screen.findByRole("complementary", { name: "Send the proof to the printer" });
  // The pane's title is the to-do's, linking to its own page; the page's own actions are in it.
  expect(within(pane).getByRole("link", { name: "Send the proof to the printer" })).toHaveAttribute("href", expect.stringContaining("A-1"));
  await waitFor(() => expect(within(pane).getByRole("button", { name: "Mark done" })).toBeInTheDocument());
  const list = screen.getByRole("list", { name: "Open to-dos" });
  const [first, second] = within(list).getAllByRole("listitem").filter((r) => r.hasAttribute("data-row"));
  expect(first).toHaveAttribute("aria-current", "true");
  await user.click(within(second).getByText("Order the sample copies"));
  expect(await screen.findByRole("complementary", { name: "Order the sample copies" })).toBeInTheDocument();
  expect(screen.queryByRole("complementary", { name: "Send the proof to the printer" })).toBeNull();
  expect(second).toHaveAttribute("aria-current", "true");
});

test("below the pane width no to-do is chosen, and a row's title is the link to the to-do's own page", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const link = await screen.findByRole("link", { name: "Send the proof to the printer" });
  expect(link).toHaveAttribute("href", expect.stringContaining("A-1"));
  await user.click(link);
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("where the pane would overlay the list nothing is chosen as the list opens and no pane shows; choosing a row shows it, and its Close button closes it", async () => {
  besidePane();
  widths(800);
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const list = await screen.findByRole("list", { name: "Open to-dos" });
  const [first, second] = within(list).getAllByRole("listitem").filter((r) => r.hasAttribute("data-row"));
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(first).not.toHaveAttribute("aria-current");
  await user.click(within(second).getByText("Order the sample copies"));
  expect(await screen.findByRole("complementary", { name: "Order the sample copies" })).toBeInTheDocument();
  await user.click(within(screen.getByRole("complementary")).getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull());
});

test("Edit details in the pane opens one editor, the drawer, and none in the list; Save closes it and the list shows the new title", async () => {
  besidePane();
  widths(1200);
  const user = userEvent.setup();
  let title = rowsOf[0].text;
  fakeApi({
    "GET open-items": () => ({ actions: [{ ...rowsOf[0], text: title }, rowsOf[1]], questions: [], stale_days: 21, rows_shown: 15 }),
    "GET people": () => [person("P-1", "Quinn Sample")],
    "GET projects": () => [project("PRJ-1", "Harbor")],
    "GET kinds/action": () => ({ kind: "action", fields: [] }),
    "GET settings": () => ({ fingerprint: "fp", items: [] }),
    "GET lists": () => [],
    "GET organizations": () => [],
    "POST records/edit": (body) => {
      title = (body as { fields: { text: string } }).fields.text;
      return { changeset: "CS-1" };
    },
    ...page("A-1", rowsOf[0].text),
    ...page("A-2", rowsOf[1].text),
  });
  renderApp(<OpenItems />);
  const pane = await screen.findByRole("complementary", { name: "Send the proof to the printer" });
  await user.click(await within(pane).findByRole("button", { name: "Edit details" }));
  const drawer = await screen.findByRole("dialog", { name: "Edit to-do" });
  // One editor: the drawer's title field is the only one on the screen.
  expect(screen.getAllByRole("textbox", { name: "Title", hidden: true })).toHaveLength(1);
  const field = within(drawer).getByRole("textbox", { name: "Title" });
  await user.clear(field);
  await user.type(field, "Send the proof to the binder");
  await user.click(within(drawer).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit to-do" })).toBeNull());
  expect(screen.queryByRole("textbox", { name: "Title", hidden: true })).toBeNull();
  const list = screen.getByRole("list", { name: "Open to-dos" });
  expect(await within(list).findByText("Send the proof to the binder")).toBeInTheDocument();
});
