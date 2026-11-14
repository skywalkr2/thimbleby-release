import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { person, project } from "../lib/records-fixtures";
import { fakeApi, Refuse, renderApp, type Routes, snapshotOf, typeMoment } from "../test-utils";
import { todayOn } from "../lib/dates";
import { chooseFilters } from "../lib/open-items";
import { dateAndTime } from "./ReminderLine";
import { OpenItems } from "./OpenItems";
import { setSideChoice } from "../lib/sides";

const WEB = "https" + "://";

const action = (id: string, text: string, over: Partial<S["OpenActionView"]> = {}): S["OpenActionView"] => ({
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
  ...over,
});

const question = (id: string, title: string, over: Partial<S["OpenQuestionView"]> = {}): S["OpenQuestionView"] => ({
  id,
  version: 2,
  title,
  text: "",
  kind: "question",
  state: "waiting",
  to: "P-2",
  to_name: "Robin Sample",
  project_name: "Harbor",
  projects: ["PRJ-1"],
  since: "2026-10-08",
  waiting_days: 6,
  chases: 0,
  held_until: null,
  origin: null,
  ...over,
});

const actions = [
  action("A-1", "Send the proof to the printer", {
    due: "2026-10-12",
    state: "overdue",
    parent_name: "Upper Shelf",
    notes: "Ask about the paper too",
    origin: { kind: "link", url: `${WEB}docs.example.com/plan`, source: "S-1" },
  }),
  action("A-2", "Order the sample copies", { owners: [{ person: "P-2", name: "Robin Sample" }], project: "PRJ-2", project_name: "Lighthouse", due: "2026-10-30", needs_you: false }),
  action("A-3", "Tidy the style sheet", { state: "stale", untouched_days: 30 }),
  action("A-4", "Book the room", { owners: [], state: "no_owner", owner_question: "Q-9" }),
  action("A-5", "Wait for the printer's quote", { state: "on_hold", on_hold: "the printer's quote", needs_you: false }),
];
const questions = [
  question("Q-1", "Is the acknowledgments page final?"),
  question("Q-2", "Which cover finish?", { state: "yours", to: "P-1", to_name: "Quinn Sample", waiting_days: null, since: "2026-10-10" }),
];

function api(extra: Routes = {}, shown: { actions?: S["OpenActionView"][]; questions?: S["OpenQuestionView"][]; rowsShown?: number } = {}) {
  return fakeApi({
    "GET open-items": () => ({ actions: shown.actions ?? actions, questions: shown.questions ?? questions, stale_days: 21, rows_shown: shown.rowsShown ?? 15 }),
    "GET people": () => [person("P-1", "Quinn Sample"), person("P-2", "Robin Sample"), person("P-3", "Sam Twin")],
    "GET projects": () => [project("PRJ-1", "Harbor"), project("PRJ-2", "Lighthouse")],
    "POST actions/A-1/status": () => ({ ok: "A-1", request: null }),
    "POST records/edit": () => ({ changeset: "CS-1" }),
    "POST changesets/CS-1/undo": () => ({ restored: [0], skipped: [] }),
    ...extra,
  });
}

async function rows() {
  const list = await screen.findByRole("list", { name: "Open to-dos" });
  return within(list).getAllByRole("listitem").filter((row) => row.hasAttribute("data-row"));
}

test("the time this screen is open and in view is counted as time spent looking over the assistant's work, once, when the person leaves it", async () => {
  const start = Date.now();
  const clock = vi.spyOn(Date, "now").mockReturnValue(start);
  const calls = api({ "POST quality/review-time": () => ({ seconds: 30 }) });
  renderApp(<OpenItems />);
  await rows();
  clock.mockReturnValue(start + 30_000);
  cleanup();
  clock.mockRestore();
  expect(calls.filter((c) => c.route === "POST quality/review-time").map((c) => c.body)).toEqual([{ screen: "open", seconds: 30 }]);
});

test("every open to-do is a row with its owners, due date, project and the project it is part of, and where it came from", async () => {
  api();
  renderApp(<OpenItems />);
  const all = await rows();
  expect(all).toHaveLength(5);
  const first = all[0];
  expect(first).toHaveTextContent("Send the proof to the printer");
  expect(first).toHaveTextContent("Quinn Sample");
  expect(first).toHaveTextContent("Oct 12");
  expect(first).toHaveTextContent("Harbor");
  expect(first).toHaveTextContent("Upper Shelf");
  expect(within(first).getByRole("link", { name: "Where it came from" })).toHaveAttribute("href", `${WEB}docs.example.com/plan`);
  // The group's label says it is late; the row says the day, in words, with an icon.
  expect(first.querySelector("[data-due=late]")).toHaveTextContent(/Oct 12/);
  expect(screen.getByRole("heading", { level: 3, name: "Overdue" })).toBeInTheDocument();
  // Groups: overdue, then what is coming up, then what waits on someone else.
  expect(all[1]).toHaveTextContent("Not touched for 30 days");
  expect(all[2]).toHaveTextContent("No owner");
  expect(all[3]).toHaveTextContent("Order the sample copies");
  expect(all[4]).toHaveTextContent("Paused: the printer's quote");
});

test("a to-do has a round button to mark it done", async () => {
  api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  const done = within(first).getByRole("button", { name: /^Mark done: / });
  expect(done.querySelector("span")).toHaveAttribute("aria-hidden", "true");
  expect(within(first).queryByRole("checkbox")).toBeNull();
});

test("a to-do's owner, date and source share one meta line on a phone", async () => {
  api(
    {},
    {
      actions: [
        action("A-1", "Send the venue list", {
          due: "2026-10-12",
          origin: { kind: "link", url: `${WEB}docs.example.com/plan`, source: "S-1" },
        }),
      ],
      questions: [],
    },
  );
  document.documentElement.setAttribute("data-narrow", "");
  try {
    renderApp(<OpenItems />);
    const [first] = await rows();
    const main = first.querySelector(":scope > div:nth-child(2)")!;
    expect(main.querySelectorAll(":scope > p")).toHaveLength(1);
    const origin = within(first).getByRole("link", { name: "Where it came from" });
    expect(origin).toBeVisible();
    expect(origin.closest(".origin")).toHaveClass("inline");
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});

test("the add row is the first line of the to-dos on every width, and its More options opens the form for details", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const list = await screen.findByRole("list", { name: "Open to-dos" });
  const add = within(list).getByRole("textbox", { name: "Add a to-do" });
  expect(add.closest("li")).toBe(list.firstElementChild);
  // It is not a row of the list: it takes no part in the list's count.
  expect(add.closest("li")).not.toHaveAttribute("data-row");
  // There is no second Add button in the header: the row is the one way in, and More options carries the words over.
  expect(screen.queryByRole("button", { name: "Add a to-do" })).toBeNull();
  expect(within(list).queryByRole("button", { name: "More options" })).toBeNull();
  await user.type(add, "Call the printer");
  await user.click(within(list).getByRole("button", { name: "More options" }));
  expect(await screen.findByRole("textbox", { name: "What to do" })).toHaveValue("Call the printer");
});

test("the established wide to-do layout has no phone-only inline add row", async () => {
  document.documentElement.removeAttribute("data-narrow");
  api(
    {},
    {
      actions: [
        action("A-1", "Send the venue list", {
          origin: { kind: "link", url: `${WEB}docs.example.com/plan`, source: "S-1" },
        }),
      ],
      questions: [],
    },
  );
  renderApp(<OpenItems />);
  const list = await screen.findByRole("list", { name: "Open to-dos" });
  expect(within(list).queryByRole("button", { name: "Add a to-do…" })).toBeNull();
  expect(within(list).getByRole("link", { name: "Where it came from" }).closest(".origin")).not.toHaveClass("inline");
});

test("the to-do filters remain compact choice controls", async () => {
  api();
  renderApp(<OpenItems />);
  await rows();
  expect(screen.getByRole("combobox", { name: "Who" })).toBeVisible();
  expect(screen.getByRole("combobox", { name: "State" })).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Project" })).toBeVisible();
});

test("the to-do menu is sectioned and marks Drop as a dangerous action", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  const menu = await screen.findByRole("menu");
  expect(within(menu).getAllByRole("group")).toHaveLength(3);
  expect(menu.querySelectorAll('[role="separator"]')).toHaveLength(2);
  expect(within(menu).getByRole("menuitem", { name: "Drop" })).toHaveAttribute("data-danger", "");
});

test("Not mine to track is in the menu of a to-do and a question that a watched source handed in, and of no other", async () => {
  const user = userEvent.setup();
  const from = { kind: "source" as const, source: "S-2", watch: "news" };
  api({}, {
    actions: [action("A-1", "Chase the page", { origin: from }), action("A-2", "Typed by me")],
    questions: [question("Q-1", "When is the page due?", { origin: from })],
  });
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Chase the page/ }));
  expect(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "Not mine to track" })).toBeVisible();
  await user.keyboard("{Escape}");
  await user.click(within(second).getByRole("button", { name: /More actions for Typed by me/ }));
  expect(within(await screen.findByRole("menu")).queryByRole("menuitem", { name: "Not mine to track" })).toBeNull();
});

test("a row whose date is to be checked says so beside the date and is not shown as overdue", async () => {
  api({}, { actions: [action("A-1", "Send the proof", { due: "2026-10-12", due_check: true, state: "open" }), action("A-2", "Review it", { due: "2026-10-12" })] });
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  expect(first).toHaveTextContent(/due Mon, Oct 12 \(check this date\)/);
  expect(within(first).queryByText("Overdue")).toBeNull();
  expect(second).not.toHaveTextContent("check this date");
});

test("a to-do whose owner hasn't been told says to send, and the others don't", async () => {
  api({}, { actions: [action("A-1", "Send the proof", { to_send: true }), action("A-2", "Review it", { to_send: false })] });
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  expect(within(first).getByText("To send")).toBeInTheDocument();
  expect(within(second).queryByText("To send")).toBeNull();
});

test("a row's notes are on hover and read by a screen reader too", async () => {
  api();
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  const title = within(first).getByText("Send the proof to the printer");
  expect(title.closest("[title]")).toHaveAttribute("title", "Ask about the paper too");
  const described = title.closest("[aria-describedby]")!.getAttribute("aria-describedby")!;
  expect(document.getElementById(described)).toHaveTextContent("Ask about the paper too");
  expect(second.querySelector("[title]:not([data-key='primary'])")).toBeNull();
});

test("the questions are another list: who each waits on and since when", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  await user.click(await screen.findByRole("button", { name: /Questions/ }));
  const list = await screen.findByRole("list", { name: "Open questions" });
  const [waiting, yours] = within(list).getAllByRole("listitem");
  expect(waiting).toHaveTextContent("Is the acknowledgments page final?");
  expect(waiting).toHaveTextContent("Waiting on Robin Sample");
  expect(waiting).toHaveTextContent("since Oct 8");
  expect(waiting).toHaveTextContent("6 days");
  expect(yours).toHaveTextContent("Waiting on you");
  expect(yours).toHaveTextContent("since Oct 10");
});

test("a question waiting on you says Answer on Today, and takes you there; it has no answer form on this screen", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  await user.click(await screen.findByRole("button", { name: /Questions/ }));
  const list = await screen.findByRole("list", { name: "Open questions" });
  const yours = within(list).getAllByRole("listitem")[1];
  expect(within(yours).queryByRole("button", { name: "Answer" })).toBeNull();
  expect(within(yours).queryByRole("textbox")).toBeNull();
  window.location.hash = "";
  await user.click(within(yours).getByRole("button", { name: "Answer on Today" }));
  expect(window.location.hash).toBe("#today");
  window.location.hash = "";
});

test("project, person and state each narrow the list, from lists to pick from", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  await rows();
  const project = screen.getByRole("combobox", { name: "Project" });
  expect(within(await snapshotOf(project)).getAllByRole("option").map((o) => o.textContent)).toEqual(["All projects", "Harbor", "Lighthouse"]);
  await user.selectOptions(project, "PRJ-2");
  expect(await rows()).toHaveLength(1);
  expect((await rows())[0]).toHaveTextContent("Order the sample copies");
  await user.selectOptions(project, "");
  const who = screen.getByRole("combobox", { name: "Who" });
  expect(within(await snapshotOf(who)).getAllByRole("option").map((o) => o.textContent)).toEqual(["Everyone", "Quinn Sample", "Robin Sample"]);
  await user.selectOptions(who, "P-1");
  expect((await rows()).map((r) => r.textContent).join(" ")).not.toContain("Order the sample copies");
  expect(await rows()).toHaveLength(3);
  await user.selectOptions(who, "");
  await user.selectOptions(screen.getByRole("combobox", { name: "State" }), "stale");
  expect(await rows()).toHaveLength(1);
  expect((await rows())[0]).toHaveTextContent("Tidy the style sheet");
});

test("on a phone the person, state and project filters are one Filter sheet, with how many are on", async () => {
  const user = userEvent.setup();
  document.documentElement.setAttribute("data-narrow", "");
  try {
    api();
    renderApp(<OpenItems />);
    await rows();
    expect(screen.queryByRole("combobox", { name: "Project" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Filter" }));
    const sheet = await screen.findByRole("dialog", { name: "Filter" });
    await user.selectOptions(within(sheet).getByRole("combobox", { name: "Project" }), "PRJ-2");
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(await screen.findByRole("button", { name: "Filter (1)" })).toBeVisible();
    expect(await rows()).toHaveLength(1);
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});

test("the state list for questions is its own", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  await user.click(await screen.findByRole("button", { name: /Questions/ }));
  const state = await screen.findByRole("combobox", { name: "State" });
  expect(within(await snapshotOf(state)).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any state", "Waiting on you", "Waiting on them"]);
  await user.selectOptions(state, "yours");
  const list = await screen.findByRole("list", { name: "Open questions" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(1);
});

test("Mark done acts at once, and its one Undo is beside the row, not in the toast", async () => {
  const user = userEvent.setup();
  const calls = api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /^Mark done: / }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST actions/A-1/status")?.body).toEqual({ status: "done" }));
  expect(await screen.findByText("Marked done: Send the proof to the printer")).toBeInTheDocument();
  // One Undo for the act, beside the row's own words: the toast says what was done and draws no second one.
  const region = screen.getByRole("region", { name: "Notifications" });
  expect(within(region).queryByRole("button", { name: "Undo" })).toBeNull();
});

test("a ticked to-do keeps its place struck through, says it was done just now and has Undo in the row, until the person moves on", async () => {
  const user = userEvent.setup();
  let ticked = false;
  const calls = api({
    "GET open-items": () => ({ actions: ticked ? actions.filter((a) => a.id !== "A-1") : actions, questions, stale_days: 21 }),
    "POST actions/A-1/status": (body) => {
      ticked = (body as { status: string }).status === "done";
      return { ok: "A-1", request: null };
    },
  });
  renderApp(<OpenItems />);
  const [first] = await rows();
  const text = "Send the proof to the printer";
  await user.click(within(first).getByRole("button", { name: /^Mark done: / }));
  const done = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[data-done-row]");
    if (!found) throw new Error("not yet");
    return found;
  });
  expect(done).toHaveTextContent(text);
  expect(done).toHaveTextContent("Done just now");
  await user.click(within(done).getByRole("button", { name: `Undo: ${text}` }));
  await waitFor(() => expect(calls.filter((c) => c.route === "POST actions/A-1/status").pop()?.body).toEqual({ status: "open" }));
  await waitFor(() => expect(document.querySelector("[data-done-row]")).toBeNull());
});

test("a tab with nothing in it says so, and only rows the filters hid say that nothing matches", async () => {
  const user = userEvent.setup();
  api({}, { questions: [] });
  renderApp(<OpenItems />);
  await rows();
  await user.click(screen.getByRole("button", { name: /^Questions/ }));
  expect(await screen.findByText(/No questions are open/)).toBeInTheDocument();
  expect(screen.queryByText("Nothing matches these filters.")).toBeNull();
});

test("a note typed on Mark done reaches the assistant with the act", async () => {
  const user = userEvent.setup();
  const calls = api({ "POST actions/A-1/status": () => ({ ok: "A-1", request: "R-1" }) });
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Add a note" }));
  const box = await screen.findByRole("textbox", { name: /note/i });
  await waitFor(() => expect(box).toHaveFocus());
  await user.type(box, "Done, the printer has it{Enter}");
  await waitFor(() => expect(calls.find((c) => c.route === "POST actions/A-1/status")?.body).toEqual({ status: "done", note: "Done, the printer has it" }));
});

test("Edit has who does it: it picks a person from a list, saves on Save, and says they will be listed to be told", async () => {
  const user = userEvent.setup();
  const calls = api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  const picker = await screen.findByRole("combobox", { name: "Owner" });
  await user.selectOptions(picker, "P-3");
  // Nothing is saved on choosing: the change waits for Save, and the form says what follows from it.
  expect(calls.some((c) => c.route === "POST records/edit")).toBe(false);
  expect(screen.getByText("Sam Twin will be listed under Follow-ups, for you to tell them. Nothing is sent.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls.find((c) => c.route === "POST records/edit")?.body).toEqual({
      kind: "action",
      id: "A-1",
      read_version: 3,
      fields: { owners: [{ person: "P-3" }] },
    }),
  );
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-1/undo")).toBe(true));
});

test("on a shared to-do, Edit changes one owner and leaves the rest", async () => {
  const user = userEvent.setup();
  const shared = action("A-7", "Agree on the back-cover copy", {
    owners: [
      { person: "P-1", name: "Quinn Sample" },
      { person: "P-2", name: "Robin Sample" },
    ],
  });
  const calls = api({}, { actions: [shared] });
  renderApp(<OpenItems />);
  const [row] = await rows();
  await user.click(within(row).getByRole("button", { name: /More actions for Agree on the back-cover copy/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  await user.selectOptions(await screen.findByRole("combobox", { name: "Whose part" }), "P-2");
  await user.selectOptions(await screen.findByRole("combobox", { name: "Reassign to" }), "P-3");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST records/edit")?.body).toMatchObject({ fields: { owners: [{ person: "P-1" }, { person: "P-3" }] } }));
});

test("editing a to-do keeps the team the owner acted for, and the project can be changed in the same form", async () => {
  const user = userEvent.setup();
  const teamed = action("A-6", "Print the posters", { owners: [{ person: "P-1", name: "Quinn Sample", team: "TEAM-1" }] });
  const calls = api({}, { actions: [teamed] });
  renderApp(<OpenItems />);
  const [row] = await rows();
  await user.click(within(row).getByRole("button", { name: /More actions for Print the posters/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  await user.selectOptions(await screen.findByRole("combobox", { name: "Owner" }), "P-3");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST records/edit")?.body).toMatchObject({ fields: { owners: [{ person: "P-3", team: "TEAM-1" }] } }));
});

test("Edit changes the words and the due date from the row, sending only what changed", async () => {
  const user = userEvent.setup();
  const calls = api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  const text = await screen.findByRole("textbox", { name: "Title" });
  await waitFor(() => expect(text).toHaveFocus());
  await user.clear(text);
  await user.type(text, "Send the corrected proof to the printer");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls.find((c) => c.route === "POST records/edit")?.body).toEqual({
      kind: "action",
      id: "A-1",
      read_version: 3,
      fields: { text: "Send the corrected proof to the printer" },
    }),
  );
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
});

test("Edit changes the owner from a list, with Undo, and keeps the team the owner acted for", async () => {
  const user = userEvent.setup();
  const teamed = action("A-6", "Print the proofs", { owners: [{ person: "P-1", name: "Quinn Sample (Print)", team: "T-1" }] });
  const calls = api({}, { actions: [teamed] });
  renderApp(<OpenItems />);
  const [row] = await rows();
  await user.click(within(row).getByRole("button", { name: /More actions for Print the proofs/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  await user.selectOptions(await screen.findByRole("combobox", { name: "Owner" }), "P-3");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST records/edit")?.body).toMatchObject({ fields: { owners: [{ person: "P-3", team: "T-1" }] } }));
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-1/undo")).toBe(true));
});

test("a to-do that nearly repeats another offers Merge with it, at once and with one Undo; one that doesn't offers nothing", async () => {
  const user = userEvent.setup();
  const twin = action("A-8", "Order the sample copies today", {
    duplicate: { id: "A-9", text: "Order the sample copies for the reviewers", version: 4 },
  });
  const calls = api({ "POST actions/A-8/merge": () => ({ changeset: "CS-1" }) }, { actions: [twin, actions[1]] });
  renderApp(<OpenItems />);
  const [row, other] = await rows();
  await user.click(within(other).getByRole("button", { name: /More actions for Order the sample copies$/ }));
  expect(screen.queryByRole("menuitem", { name: /Merge with/ })).toBeNull();
  await user.keyboard("{Escape}");
  await user.click(within(row).getByRole("button", { name: /More actions for Order the sample copies today/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Merge with “Order the sample copies for the reviewers”" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST actions/A-8/merge")?.body).toEqual({ other: "A-9", read_version: 3, other_version: 4 }));
  expect(await screen.findByText("Merged: “Order the sample copies for the reviewers” is closed.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-1/undo")).toBe(true));
});

test("a to-do with no owner asks who, in the row", async () => {
  const user = userEvent.setup();
  const calls = api({ "POST questions/Q-9/answer": () => ({ ok: "Q-9", request: null }) });
  renderApp(<OpenItems />);
  const row = (await rows())[2];
  await user.click(within(row).getByRole("button", { name: "Pick an owner" }));
  await user.selectOptions(await within(row).findByRole("combobox"), "P-2");
  await user.click(within(row).getByRole("button", { name: "Add the to-do" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST questions/Q-9/answer")?.body).toEqual({ person: "P-2" }));
});

test("a question can be answered, reworded, asked of someone else or dropped from its row", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  await user.click(await screen.findByRole("button", { name: /Questions/ }));
  const [waiting] = within(await screen.findByRole("list", { name: "Open questions" })).getAllByRole("listitem");
  await user.click(within(waiting).getByRole("button", { name: /More actions for Is the acknowledgments page final/ }));
  const names = (await screen.findAllByRole("menuitem")).map((m) => m.querySelector('[slot="label"]')?.textContent ?? m.textContent);
  expect(names).toEqual(expect.arrayContaining(["Reword", "Ask someone else", "Drop"]));
});

test("with nothing open the screen says so, and a failed load offers to try again", async () => {
  api({}, { actions: [], questions: [] });
  renderApp(<OpenItems />);
  // The empty to-dos are a brand moment: a title, one line, the way to see what was finished and the way to add the next thing.
  expect(await screen.findByText("Nothing is open right now.")).toBeInTheDocument();
  expect(screen.getByText("All done")).toBeInTheDocument();
  // The page's own empty state is the shared card form (r3-s3), not a bare mark and a line.
  expect(document.querySelector("[data-empty]")?.className).toMatch(/card/);
  expect(screen.getByRole("button", { name: "See what you finished" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add a to-do" })).toBeInTheDocument();
});

test("with no side besides Personal the filters say Area, never Project, and the state list has no No owner", async () => {
  api({
    "GET setup/business": () => ({ business: false, name: null, personal: "PRJ-personal", sides: [], chosen: "me" }),
    "GET projects": () => [project("PRJ-personal", "Personal")],
  });
  renderApp(<OpenItems />);
  await rows();
  expect(await screen.findByRole("combobox", { name: "Area" })).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Project" })).toBeNull();
  expect(within(await snapshotOf(screen.getByRole("combobox", { name: "Area" }))).getByRole("option", { name: "All areas" })).toBeTruthy();
  const states = within(await snapshotOf(screen.getByRole("combobox", { name: "State" }))).getAllByRole("option").map((o) => o.textContent);
  expect(states).toEqual(expect.arrayContaining(["Overdue", "Not touched in a while", "Paused"]));
  expect(states).not.toContain("No owner");
});

test("with a side the filters keep Project and No owner", async () => {
  api({ "GET setup/business": () => ({ business: true, name: "Orchard Press", personal: "PRJ-personal", sides: [{ project: "PRJ-side", kind: "business", name: "Orchard Press" }], chosen: "work" }) });
  renderApp(<OpenItems />);
  await rows();
  expect(screen.getByRole("combobox", { name: "Project" })).toBeInTheDocument();
  expect(within(await snapshotOf(screen.getByRole("combobox", { name: "State" }))).getByRole("option", { name: "No owner" })).toBeTruthy();
});

const BUSINESS = () => ({ business: true, name: "Orchard Press", personal: "PRJ-personal", sides: [{ project: "PRJ-side", kind: "business", name: "Orchard Press" }], chosen: "work" });

test("a to-do filed on a side and in none of its projects shows no project chip, and the project filter lists real projects only", async () => {
  const user = userEvent.setup();
  api(
    { "GET setup/business": BUSINESS, "GET projects": () => [project("PRJ-personal", "Personal", { side: true }), project("PRJ-side", "Orchard Press", { side: true }), project("PRJ-1", "Harbor", { parent: "PRJ-side" }), project("PRJ-2", "Lantern", { parent: "PRJ-side" })] },
    { actions: [action("A-1", "Send the proof"), action("A-2", "Tidy the shelf", { project: "PRJ-side", project_name: "", side_name: "Orchard Press" }), action("A-3", "Order the paper", { project: "PRJ-2", project_name: "Lantern" })], questions: [] },
  );
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  expect(first).toHaveTextContent("Harbor");
  expect(second).not.toHaveTextContent("not in a project");
  expect(second).not.toHaveTextContent("Orchard Press");
  const choice = screen.getByRole("combobox", { name: "Project" });
  expect(within(await snapshotOf(choice)).getAllByRole("option").map((o) => o.textContent)).toEqual(["All projects", "Harbor", "Lantern"]);
  await user.selectOptions(choice, "PRJ-1");
  expect(await rows()).toHaveLength(1);
});

test("a filter is drawn when it can change the list, never by how long the list is; with none to draw there is no row and no empty strip (answer 1)", async () => {
  // Two to-dos: one person, one project, one state, no side. Nothing to narrow by, so nothing is drawn.
  api({}, { actions: [action("A-1", "Send the proof"), action("A-2", "Tidy the shelf")], questions: [] });
  renderApp(<OpenItems />);
  await rows();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(document.querySelector("[data-header-filters]")).toBeNull();
});

test("Who is drawn when the to-dos belong to more than one person, State when they are in more than one state, Project with two projects", async () => {
  api({}, { actions: [action("A-1", "Send the proof"), action("A-2", "Tidy the shelf", { owners: [{ person: "P-2", name: "Robin Sample" }], needs_you: false })], questions: [] });
  renderApp(<OpenItems />);
  await rows();
  expect(screen.getByRole("combobox", { name: "Who" })).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "State" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Project" })).toBeNull();
});

test("a state is offered only when the rows are in more than one state, and only the states they are in", async () => {
  const user = userEvent.setup();
  api({}, { actions: [action("A-1", "Send the proof", { state: "overdue", due: "2026-10-12" }), action("A-2", "Tidy the shelf")], questions: [] });
  renderApp(<OpenItems />);
  await rows();
  const state = screen.getByRole("combobox", { name: "State" });
  expect(within(await snapshotOf(state)).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any state", "Overdue"]);
  await user.selectOptions(state, "overdue");
  expect(await rows()).toHaveLength(1);
  // A filter that is on stays, with Clear, however short the result.
  expect(screen.getByRole("combobox", { name: "State" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear" }));
  expect(await rows()).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
});

// ---- the to-do row's own acts: Drop, Change this, a reminder, a hold, what is learned (moved here with the row) ---------------

test("Drop on a to-do asks why with the cursor in the field, acts at once and Undo takes it back", async () => {
  const user = userEvent.setup();
  const calls = api({ "POST actions/A-1/drop": () => ({ changeset: "CS-9", drafts: [], acts: [] }), "POST changesets/CS-9/undo": () => ({ restored: [0], skipped: [] }) });
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Drop" }));
  const field = await screen.findByRole("textbox", { name: "Why isn't it needed?" });
  expect(field).toHaveFocus();
  const form = field.closest("form") as HTMLElement;
  expect(within(form).getByRole("button", { name: "Drop it" })).toBeDisabled();
  await user.type(field, "The index moved to the printer");
  await user.click(within(form).getByRole("button", { name: "Drop it" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST actions/A-1/drop")?.body).toEqual({ reason: "The index moved to the printer" }));
  expect(await screen.findByText("Dropped.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-9/undo")).toBe(true));
});

test("Drop on a to-do that reached people reads Drop it and tell them, says a note waits for the yes, and one Undo takes the note and the drop back", async () => {
  const user = userEvent.setup();
  const calls = api(
    {
      "POST actions/A-1/drop": () => ({ changeset: "CS-9", drafts: ["CS-10"], acts: ["XACT-1"] }),
      "POST changesets/CS-9/undo": () => ({ restored: [0], skipped: [] }),
      "POST changesets/CS-10/undo": () => ({ restored: [0], skipped: [] }),
    },
    { actions: [action("A-1", "Send the proof to the printer", { told_names: ["Robin Sample"] }), action("A-2", "Tidy the style sheet")] },
  );
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  await user.click(within(second).getByRole("button", { name: /More actions for Tidy the style sheet/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Drop" }));
  const plain = await screen.findByRole("textbox", { name: "Why isn't it needed?" });
  await user.type(plain, "x");
  expect(within(plain.closest("form") as HTMLElement).getByRole("button", { name: "Drop it" })).toBeInTheDocument();
  expect(within(plain.closest("form") as HTMLElement).queryByRole("button", { name: "Drop it and tell them" })).toBeNull();
  await user.keyboard("{Escape}");
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Drop" }));
  const field = await screen.findByRole("textbox", { name: "Why isn't it needed?" });
  const form = field.closest("form") as HTMLElement;
  expect(within(form).queryByRole("button", { name: "Drop it" })).toBeNull();
  await user.type(field, "The index moved to the printer");
  await user.click(within(form).getByRole("button", { name: "Drop it and tell them" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST actions/A-1/drop")?.body).toEqual({ reason: "The index moved to the printer" }));
  expect(await screen.findByText("Dropped. A note to Robin Sample is waiting for your yes.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.filter((c) => c.route.endsWith("/undo")).map((c) => c.route)).toEqual(["POST changesets/CS-9/undo"]));
});

test("a to-do's menu has one Edit with every field, and no second Reassign or Change this beside it", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  expect(await screen.findByRole("menuitem", { name: "Edit" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "Reassign…" })).toBeNull();
  expect(screen.queryByRole("menuitem", { name: "Change this" })).toBeNull();
});

test("a to-do's title opens its page", async () => {
  api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  expect(within(first).getByRole("link", { name: /^Send the proof/ }).getAttribute("href")).toMatch(/#records\/action\/A-1$/);
});

test("only one editor is open at a time, on a row or across rows, and Escape closes it", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  expect(await screen.findAllByRole("button", { name: "Save" })).toHaveLength(1);
  // A note on the same row closes the edit.
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Add a note" }));
  expect(within(first).queryByRole("textbox", { name: "Title" })).toBeNull();
  expect(await within(first).findByRole("textbox", { name: "Your note" })).toBeInTheDocument();
  // An edit on another row closes that note.
  await user.click(within(second).getByRole("button", { name: /More actions for/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  await waitFor(() => expect(within(first).queryByRole("textbox", { name: "Your note" })).toBeNull());
  const text = await within(second).findByRole("textbox", { name: "Title" });
  await user.click(text);
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("textbox", { name: "Title" })).toBeNull());
});

test("what is being learned from a change asked for on a to-do shows on that row", async () => {
  api({
    "GET knowledge/learned": () => ({
      lines: [{ signal: "SIG-1", kind: "change_requested", changeset: null, refs: ["A-2"], state: "learning", waiting: "With the assistant, starting now" }],
    }),
  });
  renderApp(<OpenItems />);
  const row = (await screen.findByText("Order the sample copies")).closest("li")!;
  expect(await within(row).findByRole("status")).toHaveTextContent("Learning from this…");
});

test("a to-do whose blocker is over says who answered and when, and Resume clears it", async () => {
  const user = userEvent.setup();
  const answered = action("A-6", "Ship the proofs", {
    blocker: { kind: "question", id: "Q-4", name: "Can proof copies ship by Nov 3?", who: "Morgan Sample", state: "answered", answered: "2026-10-09" },
  });
  const calls = api({ "POST actions/A-6/unhold": () => ({ ok: "A-6", previous: { waiting_for: "Morgan Sample", since: "2026-10-01", on: "Q-4" } }) }, { actions: [answered] });
  renderApp(<OpenItems />);
  expect(await screen.findByText(/^Unblocked: Morgan Sample answered .*9$/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "More actions for Ship the proofs" }));
  await user.click(await screen.findByRole("menuitem", { name: "Resume" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST actions/A-6/unhold")).toBe(true));
});

test("a blocked to-do says Blocked, waiting on who or what it waits on", async () => {
  api({}, { actions: [action("A-7", "Sign the contract", { state: "on_hold", on_hold: "Morgan Sample", blocker: { kind: "person", id: "PER-9", name: "Morgan Sample", state: "waiting" } })] });
  renderApp(<OpenItems />);
  expect(await screen.findByText(/Blocked, waiting on/)).toHaveTextContent("Blocked, waiting on Morgan Sample");
});

test("a to-do's menu sets a reminder from a day and time, and a set one is said on its row and can be changed or removed", async () => {
  const user = userEvent.setup();
  const calls = api({ "POST reminders/A-1": () => ({ changeset: "CS-6" }) });
  const first = renderApp(<OpenItems />);
  const [row] = await rows();
  await user.click(within(row).getByRole("button", { name: /More actions for Send the proof/ }));
  expect(screen.queryByRole("menuitem", { name: "Remove reminder" })).toBeNull();
  await user.click(screen.getByRole("menuitem", { name: "Remind me…" }));
  const box = await screen.findByLabelText("Remind me at");
  await typeMoment(userEvent.setup(), box, "2026-10-21T10:30");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST reminders/A-1")?.body).toEqual({ at: "2026-10-21T10:30" }));
  first.unmount();

  const at = "2026-10-21T10:30:00-04:00";
  const again = api({ "POST reminders/A-1": () => ({ changeset: "CS-6" }) }, { actions: [action("A-1", "Send the proof to the printer", { remind_at: at })] });
  renderApp(<OpenItems />);
  expect(await screen.findByText(new RegExp(`Reminder ${dateAndTime(at)}`))).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /More actions for Send the proof/ }));
  expect(screen.getByRole("menuitem", { name: "Change reminder…" })).toBeInTheDocument();
  await user.click(screen.getByRole("menuitem", { name: "Remove reminder" }));
  await waitFor(() => expect(again.filter((c) => c.route === "POST reminders/A-1").map((c) => c.body)).toEqual([{}]));
});

test("a reminder is a menu entry, never a second primary button on the row", async () => {
  api();
  renderApp(<OpenItems />);
  const [first] = await rows();
  expect(within(first).queryByRole("button", { name: /Remind me/ })).toBeNull();
  expect(within(first).getAllByRole("button").filter((b) => b.getAttribute("data-key") === "primary")).toHaveLength(1);
});

test("the overdue line's link shows the person's own overdue to-dos and no one else's, as many as the line counts", async () => {
  const mine = [action("A-1", "Send the proof to the printer", { state: "overdue", due: "2026-10-12" }), action("A-8", "Pay the invoice", { state: "overdue", due: "2026-10-10" })];
  const theirs = action("A-2", "Order the sample copies", { state: "overdue", due: "2026-10-09", owners: [{ person: "P-2", name: "Robin Sample" }] });
  api({}, { actions: [theirs, ...mine, action("A-3", "Tidy the style sheet")] });
  chooseFilters({ state: "overdue", person: "P-1" });
  renderApp(<OpenItems />);
  const listed = await rows();
  expect(listed).toHaveLength(2);
  expect(listed.map((r) => r.textContent).join(" ")).toMatch(/Send the proof to the printer.*Pay the invoice|Pay the invoice.*Send the proof/);
  expect(screen.queryByText("Order the sample copies")).toBeNull();
});

test("the line under the list counts the rows the tab counts, with the noun the tab names, and never a number of its own (X87)", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  // Five to-dos are listed: three wait on the person (two of theirs and one with no owner yet), two don't.
  expect(await screen.findByRole("button", { name: /^To-dos\b.*5/ })).toBeInTheDocument();
  expect(await screen.findByText("· 3 are yours")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Questions\b/ }));
  expect(await screen.findByText("· 1 is yours")).toBeInTheDocument();
});

test("under the title it says how many the open tab holds and how many of them are overdue, from the rows listed, and follows the tab (VS10)", async () => {
  const user = userEvent.setup();
  api();
  renderApp(<OpenItems />);
  expect(await screen.findByText("5 open")).toBeInTheDocument();
  expect(screen.getByText(/· 1 overdue/)).toBeInTheDocument();
  // The questions tab counts questions, with no to-do figures beside it.
  await user.click(screen.getByRole("button", { name: /^Questions\b/ }));
  expect(await screen.findByText("2 open")).toBeInTheDocument();
  expect(screen.queryByText(/overdue/)).toBeNull();
});

// ---- The 4.6 `todos` mockup (section 316) ---------------------------------------------------------------------------------

const TODAY_ISO = todayOn(new Date());
const mixed = [
  action("G-1", "Pay the deposit", { due: "2026-01-05", state: "overdue" }),
  action("G-2", "Get a catering quote", { due: TODAY_ISO }),
  action("G-3", "Take the tablets", { due: TODAY_ISO, repeat: undefined }),
  action("G-4", "Mail the claim forms", { due: "2099-10-30" }),
  action("G-5", "Book the fitting", { due: "2099-11-05" }),
  action("G-6", "Revised offsite budget", { owners: [{ person: "P-2", name: "Robin Sample" }], needs_you: false, due: "2099-11-01" }),
  action("G-7", "Print the agenda", { needs_date: true }),
];
const groupLabels = () => within(screen.getByRole("list", { name: "Open to-dos" })).getAllByRole("heading", { level: 3 });

test("the to-dos are grouped Overdue, Today, Coming up and Waiting on others, each with its count, in that order", async () => {
  api({}, { actions: mixed });
  renderApp(<OpenItems />);
  await screen.findByRole("list", { name: "Open to-dos" });
  expect(groupLabels().map((g) => g.textContent)).toEqual(["Overdue1", "Today2", "Coming up2", "Waiting on others1"]);
  expect(groupLabels()[0]).toHaveAttribute("data-tone", "danger");
  const names = (await rows()).map((r) => r.querySelector("[data-row-title]")?.textContent);
  expect(names).toEqual(["Pay the deposit", "Get a catering quote", "Take the tablets", "Mail the claim forms", "Book the fitting", "Revised offsite budget"]);
  // The undated one is in the slim "needs a date" section at the foot, not among the rows.
  expect(within(screen.getByRole("region", { name: /Needs a date/ })).getByRole("link", { name: "Print the agenda" })).toBeInTheDocument();
  // The overdue line says its day with an icon; the group says it too, so the row has no Overdue pill of its own.
  const first = (await rows())[0];
  expect(first.querySelector("[data-due=late] [data-icon=alert]")).not.toBeNull();
  expect(within(first).queryByText("Overdue")).toBeNull();
  expect((await rows())[1].querySelector("[data-due=today]")).toHaveTextContent("Due today");
});

test("the counts agree: the tab, the line under the title, the groups with the line for those that need a date, and the footer", async () => {
  api({}, { actions: mixed, questions });
  renderApp(<OpenItems />);
  await screen.findByRole("list", { name: "Open to-dos" });
  // 7 to-dos and 2 questions are open; the line counts the tab shown (the to-dos); one is overdue and two are due today; the line says at most three things, so with the person's own count it gives up "due today".
  expect(screen.getByRole("button", { name: /^To-dos/ })).toHaveTextContent("7");
  expect(screen.getByRole("button", { name: /^Questions/ })).toHaveTextContent("2");
  expect(screen.getByText("7 open")).toBeInTheDocument();
  expect(screen.getByText(/· 1 overdue/)).toBeInTheDocument();
  expect(screen.queryByText(/due today/)).toBeNull();
  const grouped = groupLabels().reduce((n, g) => n + Number(g.querySelector("[data-group-count]")?.textContent), 0);
  expect(grouped).toBe(6);
  expect(screen.getByText("1 to-do needs a date")).toBeInTheDocument();
  expect(grouped + 1).toBe(7);
  // How many of the seven wait on the person is said once, in the line under the title, not in a footer.
  expect(document.querySelector("[data-need-count]")).toHaveTextContent(/\d+ are yours|None are yours|1 is yours/);
});

test("those that need a date are listed at the foot of the list under one line, with a date picker beside each and no button to press", async () => {
  api({}, { actions: mixed });
  renderApp(<OpenItems />);
  const line = await screen.findByText("1 to-do needs a date");
  expect(line.closest("[data-needs-date-line]")).not.toBeNull();
  const group = await screen.findByRole("region", { name: /Needs a date/ });
  expect(within(group).getByLabelText(/^Date for /)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Give them dates|Hide them/ })).toBeNull();
});

test("a question has no check box or round tick: only a to-do can be marked done from its row", async () => {
  const user = userEvent.setup();
  api({}, { actions: mixed, questions });
  renderApp(<OpenItems />);
  expect((await rows())[0].querySelector("[aria-label^='Mark done']")).not.toBeNull();
  await user.click(screen.getByRole("button", { name: /^Questions/ }));
  const list = await screen.findByRole("list", { name: "Open questions" });
  expect(within(list).getAllByRole("listitem").length).toBe(2);
  expect(within(list).queryByRole("button", { name: /^Mark done/ })).toBeNull();
  expect(within(list).queryByRole("checkbox")).toBeNull();
  for (const q of Array.from(list.querySelectorAll("[data-row-lead]"))) expect(q.children).toHaveLength(0);
});

test("Side is drawn when the tab's rows are on more than one side, and its counts are the tab's own", async () => {
  const user = userEvent.setup();
  const many = Array.from({ length: 12 }, (_, i) => action(`A-${i + 10}`, `To-do number ${i + 1}`, { side: "PRJ-side" }));
  const own = action("A-30", "Tidy the shelf", { side: "PRJ-personal", state: "overdue", due: "2026-10-12" });
  api({ "GET setup/business": BUSINESS, "GET waiting": () => ({ changed: { total: 0 }, followups: { total: 0 }, handled: { total: 0 }, open: { total: 14, sides: [{ side: "PRJ-side", count: 14 }] } }) }, { actions: [...many, own], questions: [question("Q-1", "Which cover finish?", { side: "PRJ-side" })] });
  renderApp(<OpenItems />);
  // The to-dos are on two sides: the choice is drawn, and its count is the to-dos' own (not the screen's 14).
  expect(await screen.findByRole("radio", { name: "Orchard Press, 12 waiting" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "State" })).toBeInTheDocument();
  // The questions are all on one side and in one state: nothing to narrow, so nothing is drawn over them.
  await user.click(screen.getByRole("button", { name: /^Questions/ }));
  await waitFor(() => expect(screen.queryByRole("radio", { name: /Orchard Press/ })).toBeNull());
  expect(screen.queryByRole("combobox", { name: "State" })).toBeNull();
  expect(document.querySelector("[data-header-filters]")).toBeNull();
});

test("three to-dos on two sides draw Side and not Who; a side that is picked stays drawn when it holds one (answer 1)", async () => {
  const user = userEvent.setup();
  const three = [action("A-1", "Send the proof", { side: "PRJ-side" }), action("A-2", "Order the samples", { side: "PRJ-side" }), action("A-3", "Tidy the shelf", { side: "PRJ-personal" })];
  api({ "GET setup/business": BUSINESS }, { actions: three, questions: [] });
  renderApp(<OpenItems />);
  await rows();
  expect(await screen.findByRole("radio", { name: /Orchard Press/ })).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Who" })).toBeNull();
  await user.click(screen.getByRole("radio", { name: /Personal/ }));
  expect(await rows()).toHaveLength(1);
  expect(screen.getByRole("radio", { name: /Personal/ })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear" }));
  expect(await rows()).toHaveLength(3);
});

test("only Personal and only the person's own to-dos draw no filter row at all (answer 1)", async () => {
  const own = [action("A-1", "Send the proof"), action("A-2", "Tidy the shelf"), action("A-3", "Order the samples")];
  api({ "GET setup/business": () => ({ business: false, name: "", personal: "PRJ-personal", sides: [], chosen: "personal" }) }, { actions: own, questions: [] });
  renderApp(<OpenItems />);
  await rows();
  expect(document.querySelector("[data-header-filters]")).toBeNull();
});

test("one cap for every section: a list longer than the setting shows the same few rows in each, each with its own Show N more", async () => {
  const user = userEvent.setup();
  const later = Array.from({ length: 9 }, (_, i) => action(`L-${i}`, `Later to-do ${i}`, { due: "2099-12-01" }));
  const today = Array.from({ length: 5 }, (_, i) => action(`T-${i}`, `Today to-do ${i}`, { due: TODAY_ISO }));
  api({}, { actions: [...today, ...later], questions: [], rowsShown: 6 });
  renderApp(<OpenItems />);
  await rows();
  // Fourteen to-dos are more than the setting's six, so each section shows three (a third of it, at least three).
  expect(within(screen.getByRole("list", { name: "Open to-dos" })).getAllByText(/^Later to-do/)).toHaveLength(3);
  expect(within(screen.getByRole("list", { name: "Open to-dos" })).getAllByText(/^Today to-do/)).toHaveLength(3);
  expect(document.querySelector('[data-show-more="today"]')).toHaveTextContent("Show 2 more");
  const more = document.querySelector<HTMLElement>('[data-show-more="coming"]');
  // Round 4 (r4-s7): a text button that says which group it opens, never a bare pill.
  expect(more).toHaveTextContent("Show 6 more coming up");
  expect(more).toHaveAttribute("data-variant", "quiet");
  // The group's count still says all nine.
  expect(groupLabels().find((g) => g.textContent?.startsWith("Coming up"))).toHaveTextContent("9");
  await user.click(more!);
  expect(within(screen.getByRole("list", { name: "Open to-dos" })).getAllByText(/^Later to-do/)).toHaveLength(9);
  expect(document.querySelector('[data-show-more="coming"]')).toBeNull();
  expect(within(screen.getByRole("list", { name: "Open to-dos" })).getAllByText(/^Today to-do/)).toHaveLength(3);
});

test("a list that fits the setting is not cut", async () => {
  const later = Array.from({ length: 5 }, (_, i) => action(`L-${i}`, `Later to-do ${i}`, { due: "2099-12-01" }));
  api({}, { actions: later, questions: [], rowsShown: 6 });
  renderApp(<OpenItems />);
  await rows();
  expect(within(screen.getByRole("list", { name: "Open to-dos" })).getAllByText(/^Later to-do/)).toHaveLength(5);
  expect(document.querySelector("[data-show-more]")).toBeNull();
});

test("while the list could not be loaded the tabs show no count, never a false 0 beside the error", async () => {
  api({ "GET open-items": () => new Refuse(500, "no") });
  renderApp(<OpenItems />);
  await screen.findByText(/To-dos and questions didn't load/);
  expect(screen.getByRole("button", { name: /^To-dos/ })).not.toHaveTextContent(/\d/);
  expect(screen.getByRole("button", { name: /^Questions/ })).not.toHaveTextContent(/\d/);
});

test("a to-do's edit refused because it changed since the editor opened keeps what was typed, shows old, new and theirs, and the choice saves against the new version", async () => {
  const user = userEvent.setup();
  let moved = false;
  const current = () => actions.map((a) => (a.id === "A-1" && moved ? { ...a, version: 4, text: "Send the proof to the binder" } : a));
  const calls = api({
    "GET open-items": () => ({ actions: current(), questions, stale_days: 21, rows_shown: 15 }),
    "POST records/edit": (body) => {
      if ((body as { read_version: number }).read_version === 3) {
        moved = true;
        return new Refuse(409, "This record changed after you opened it.");
      }
      return { changeset: "CS-2" };
    },
  });
  renderApp(<OpenItems />);
  const [first] = await rows();
  await user.click(within(first).getByRole("button", { name: /More actions for Send the proof/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
  const title = await screen.findByRole("textbox", { name: "Title" });
  await user.clear(title);
  await user.type(title, "Send the proof to the press");
  await user.click(screen.getByRole("button", { name: "Save" }));
  const box = (await screen.findByText("Changed somewhere else")).closest("[data-changed-elsewhere]") as HTMLElement;
  expect(box.querySelector("[data-was]")).toHaveTextContent("Send the proof to the printer");
  expect(box.querySelector("[data-now]")).toHaveTextContent("Send the proof to the binder");
  expect(box).toHaveTextContent("Yours: Send the proof to the press");
  // No toast offers to run the same stale save again.
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  await user.click(within(box).getByRole("button", { name: "Keep mine" }));
  expect(screen.queryByText("Changed somewhere else")).toBeNull();
  expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Send the proof to the press");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.filter((c) => c.route === "POST records/edit")[1]?.body).toMatchObject({ read_version: 4, fields: { text: "Send the proof to the press" } }));
});

// Q12: a row's grey line starts with its side, as a dot and a name (not a chip), when there is more than one side and the list
// is not narrowed to one.
const sideMark = (row: HTMLElement) => row.querySelector<HTMLElement>("[data-side-mark]");
const TWO_SIDES = { "GET setup/business": BUSINESS };
const filed = () => ({ actions: [action("A-1", "Send the proof", { side: "PRJ-side", due: "2026-12-30" }), action("A-2", "Tidy the shelf", { side: "PRJ-personal" })], questions: [] });

test("with two sides and the list unfiltered, each row's grey line starts with its side, named", async () => {
  setSideChoice("all");
  api(TWO_SIDES, filed());
  renderApp(<OpenItems />);
  const [first, second] = await rows();
  expect(sideMark(first)).toHaveTextContent("Orchard Press");
  expect(sideMark(second)).toHaveTextContent("Personal");
  // It comes first in the line, before the due date, and is not a filter chip.
  const meta = sideMark(first)!.parentElement!;
  expect(meta.firstElementChild).toBe(sideMark(first));
  expect(sideMark(first)!.closest("button")).toBeNull();
});

test("a long side name is never cut by a count (the line cuts it by its room), whole to a screen reader and on hover, and a due phrase is one unbreakable unit", async () => {
  setSideChoice("all");
  const LONG = "Harborview Community Support Partnership Incorporated";
  api(
    { "GET setup/business": () => ({ business: true, name: LONG, personal: "PRJ-personal", sides: [{ project: "PRJ-side", kind: "business", name: LONG }], chosen: "work" }) },
    { actions: [action("A-1", "Pay the deposit", { side: "PRJ-side", due: "2099-12-30" })], questions: [] },
  );
  renderApp(<OpenItems />);
  const [first] = await rows();
  // Round 4 (r4-s2): the text is the whole name; only the line's width may cut it, with an ellipsis in CSS.
  const mark = sideMark(first)!;
  expect(mark).toHaveAttribute("title", LONG);
  expect(mark.textContent).toBe(LONG);
  expect(within(mark).getByText(LONG)).toBeInTheDocument();
  const due = first.querySelector("[data-row-title] ~ p [class*=unit], p [class*=unit]");
  expect(due).not.toBeNull();
});

test("r4-s2: no dot stands before a side mark or ends the line, and the mark is set off from what follows it by a dot", async () => {
  setSideChoice("all");
  api(TWO_SIDES, filed());
  renderApp(<OpenItems />);
  const [first] = await rows();
  const unit = sideMark(first)!.parentElement!;
  // The side's name never runs into the part after it (here, the owner).
  expect(unit.textContent).toMatch(/Orchard Press\s*·\s*$/);
  expect(unit.nextElementSibling).toHaveTextContent("Quinn Sample");
  expect(unit.previousElementSibling?.textContent ?? "").not.toMatch(/·\s*$/);
  const line = unit.parentElement!;
  expect(line.textContent!.trim()).not.toMatch(/·$/);
});

test("filtered to one side, no row shows its side", async () => {
  setSideChoice("PRJ-side");
  api(TWO_SIDES, filed());
  renderApp(<OpenItems />);
  const [first] = await rows();
  expect(sideMark(first)).toBeNull();
  setSideChoice("all");
});

test("with only Personal, no row shows a side", async () => {
  setSideChoice("all");
  api({}, { actions: [action("A-1", "Send the proof", { side: "PRJ-personal" })], questions: [] });
  renderApp(<OpenItems />);
  const [first] = await rows();
  expect(sideMark(first)).toBeNull();
});

test("a to-do waiting on someone has Nudge when Follow-ups holds a drafted message that lists it, and no other row does", async () => {
  const user = userEvent.setup();
  window.location.hash = "";
  const section = { person: "P-2", name: "Robin Sample", is_pm: false, questions: [], actions: [], message: "", to_send: 0, nudge: { text: "Hi Robin", round: 1, question_ids: [], action_ids: ["A-2"] } };
  api({ "GET followups": () => [section] });
  renderApp(<OpenItems />);
  const all = await rows();
  const waiting = all.find((r) => r.textContent?.includes("Order the sample copies"))!;
  const nudge = await within(waiting).findByRole("button", { name: "Nudge" });
  for (const row of all.filter((r) => r !== waiting)) expect(within(row).queryByRole("button", { name: "Nudge" })).toBeNull();
  await user.click(nudge);
  // Nothing on this screen holds the message, so the person is taken to it.
  expect(window.location.hash).toContain("followups");
});

test("a waiting to-do with no drafted message has no Nudge, and one that was followed up says so and stays open", async () => {
  const followed = action("A-2", "Order the sample copies", { owners: [{ person: "P-2", name: "Robin Sample" }], needs_you: false, followed_up: "2026-10-12" });
  api({ "GET followups": () => [] }, { actions: [followed], questions: [] });
  renderApp(<OpenItems />);
  const [row] = await rows();
  expect(within(row).queryByRole("button", { name: "Nudge" })).toBeNull();
  expect(row).toHaveTextContent(/Followed up .*12/);
  expect(within(row).getByRole("button", { name: /^Mark done: / })).toBeInTheDocument();
});

test("an overdue row is tinted and edged (with its words and icon too); a row due later is not", async () => {
  api({}, { actions: mixed });
  renderApp(<OpenItems />);
  const list = await rows();
  expect(list[0]).toHaveAttribute("data-state", "danger");
  expect(list[3]).not.toHaveAttribute("data-state", "danger");
  expect(list[0].querySelector("[data-due=late] [data-icon=alert]")).not.toBeNull();
});

test("a row's second line starts with its due date, and no part of it starts with a dot", async () => {
  api({}, { actions: [action("D-1", "Order the cake", { due: "2099-10-30", owners: [{ person: "P-2", name: "Robin Sample" }], needs_you: false })], questions: [] });
  renderApp(<OpenItems />);
  const row = (await rows())[0];
  const line = row.querySelector("[data-row-title]")?.parentElement?.querySelector("p")?.textContent ?? "";
  expect(line.trimStart()).toMatch(/^Due /);
  expect(line.trimStart()).not.toMatch(/^·/);
  expect(line.indexOf("Due")).toBeLessThan(line.indexOf("Robin Sample"));
});

// H1-06: the number the menu shows beside To-dos is a number this screen says, in the same words.
test("the menu's count of what needs the person, to-dos and questions together, is said under the title when it is not the tab's own", async () => {
  const user = userEvent.setup();
  const none = { total: 0, sides: [], views: [] };
  api({ "GET waiting": () => ({ changed: none, followups: none, open: { total: 4, sides: [], views: [] }, handled: none }) });
  renderApp(<OpenItems />);
  expect(await screen.findByText("· 3 are yours")).toBeInTheDocument();
  expect(await screen.findByText("· 4 need you across to-dos and questions")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Questions\b/ }));
  expect(await screen.findByText("· 1 is yours")).toBeInTheDocument();
  expect(screen.getByText("· 4 need you across to-dos and questions")).toBeInTheDocument();
});
