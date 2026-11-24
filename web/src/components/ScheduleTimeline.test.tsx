import "@testing-library/jest-dom/vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays, dayOfMonth, monthDay, monthDayLong, shortRange, weekday } from "../lib/dates";
import { entry, item, lane, timelineRoutes, TODAY } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// The Timeline view of the calendar page (design 7.7): a lane for each project, each item a button with its kind, day and state
// in its name, the details of the item the cursor is on, days off, the range, and the list by week in a window too narrow.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");

/** The room the calendar has; none given leaves the width unknown, which counts as enough. */
function room(width?: number) {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
  if (width !== undefined) Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => width });
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("cockpit:schedule-view", "timeline");
  room();
});
afterEach(() => {
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});

const todo = (title: string, start = TODAY, over = {}) => item({ title, kind: "todo", ...over }, start);
const LANES = [
  lane("PRJ-1", "Harbor", [
    todo("Send the quote", addDays(TODAY, 2), { owners: [{ person: "P-1", name: "Quinn Sample" }] }),
    todo("Pay the deposit", addDays(TODAY, -3), { state: "overdue" }),
    item({ title: "Share the draft", kind: "promise" }, addDays(TODAY, 4)),
    item({ title: "Launch day", kind: "target", id: "PRJ-1" }, addDays(TODAY, 20)),
    item({ title: "Licence renews", kind: "fact", detail: "renewal" }, addDays(TODAY, 9)),
    item({ title: "Site visit", kind: "entry", id: "EVT-9", end: addDays(TODAY, 2), entry: entry({ title: "Site visit", own: true, kind: "own", snapshot: "EVT-9", source: "" }) }, addDays(TODAY, 1)),
    item({ title: "Standup", kind: "entry", id: "EVT-1", entry: entry({ title: "Standup", snapshot: "snap-1", entry: "EVT-1" }) }, TODAY),
  ]),
  lane("PRJ-2", "Harbor shop", [todo("Order paper", addDays(TODAY, 5))], { depth: 1, parent: "PRJ-1" }),
];

async function open(lanes = LANES, over = {}, extra = {}) {
  const calls = fakeApi(timelineRoutes(lanes, over, extra));
  const view = renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-timeline]")).not.toBeNull());
  return { calls, view };
}
const names = () => screen.getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? "");

describe("the Timeline", () => {
  test("a mark on one day carries its date beside its title", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])]);
    const mark = screen.getByRole("button", { name: /^To-do: Send the quote/ });
    expect(mark).toHaveTextContent(`${monthDay(addDays(TODAY, 2))}Send the quote`);
  });

  test("a calendar entry has its calendar's color, as it has on every other view; the app's own entries have none", async () => {
    await open(LANES, {}, { "GET watch": () => [{ id: "cal-work", label: "Work calendar", connector: "k", connector_label: "K", enabled: true, every_minutes: 15, items: 1, failures: 0, problem: null, reads: ["calendar"], shown_color: "teal" }] });
    const harbor = screen.getByRole("list", { name: "Items on the Harbor lane" });
    await waitFor(() => expect(within(harbor).getByRole("button", { name: /^Calendar entry: Standup\./ })).toHaveAttribute("data-color", "teal"));
    expect(within(harbor).getByRole("button", { name: /^Calendar entry: Site visit\./ })).not.toHaveAttribute("data-color");
  });

  test("a lane for each project, indented under its parent, each item a button named by its kind, day and state", async () => {
    const { calls } = await open();
    expect(screen.getByRole("tab", { name: "Timeline" })).toHaveAttribute("aria-selected", "true");
    expect(calls.some((c) => c.route === "GET schedule/timeline")).toBe(true);
    expect(screen.getByRole("heading", { name: "Harbor" })).toBeInTheDocument();
    const shop = screen.getByRole("heading", { name: "Harbor shop" });
    expect(shop).toHaveStyle({ paddingLeft: "calc(var(--space-2) + 1 * var(--space-3))" });
    const harbor = screen.getByRole("list", { name: "Items on the Harbor lane" });
    const kinds = within(harbor).getAllByRole("button").map((b) => b.getAttribute("data-kind"));
    expect(kinds.sort()).toEqual(["entry", "entry", "fact", "promise", "target", "todo", "todo"]);
    const send = within(harbor).getByRole("button", { name: /^To-do: Send the quote\. .*\. Open\.$/ });
    expect(send.querySelector("[data-shape='square']")).not.toBeNull();
    expect(within(harbor).getByRole("button", { name: /^Calendar entry: Standup\./ }).querySelector("[data-shape='circle']")).not.toBeNull();
    expect(within(harbor).getByRole("button", { name: /^Target day: Launch day\./ }).querySelector("[data-shape='diamond']")).not.toBeNull();
    expect(within(harbor).getByRole("button", { name: /^Renewal: Licence renews\./ }).querySelector("[data-shape='diamond']")).not.toBeNull();
    // An overdue to-do says so in its name and carries the warning icon, not only a color.
    const late = within(harbor).getByRole("button", { name: /^To-do: Pay the deposit\. .*\. Overdue\.$/ });
    expect(late.querySelector("[data-state='overdue'] svg")).not.toBeNull();
    // A thing over several days is a bar.
    expect(within(harbor).getByRole("button", { name: /^Calendar entry: Site visit\. .* to .*/ })).toHaveAttribute("data-bar");
    expect(screen.getByRole("list", { name: "Key" })).toBeInTheDocument();
  });

  test("the to-dos past due are a stack at today, each saying the day it was due", async () => {
    const was = addDays(TODAY, -40);
    await open([lane("PRJ-1", "Harbor", [todo("Pay the deposit", TODAY, { state: "overdue", detail: was }), todo("Renew the licence", TODAY, { state: "overdue", detail: addDays(TODAY, -9) })])]);
    const harbor = screen.getByRole("list", { name: "Items on the Harbor lane" });
    const late = within(harbor).getByRole("button", { name: /^To-do: Pay the deposit\. Overdue, was due .*\. Overdue\.$/ });
    expect(late.querySelector("[data-state='overdue'] svg")).not.toBeNull();
    // Two on one day take two rows: a stack, none over another.
    const top = (title: string) => Number.parseInt(screen.getByRole("button", { name: new RegExp(`^To-do: ${title}\\.`) }).closest("li")!.style.top, 10);
    expect(top("Renew the licence")).not.toBe(top("Pay the deposit"));
  });

  test("a stacked overdue to-do shows the day it was due beside its title, never today (U6-3)", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Pay the deposit", TODAY, { state: "overdue", detail: addDays(TODAY, -40) })])]);
    const harbor = screen.getByRole("list", { name: "Items on the Harbor lane" });
    const mark = within(harbor).getByRole("button", { name: /^To-do: Pay the deposit\./ });
    expect(mark.textContent).toMatch(/^due [A-Z][a-z]{2} \d{1,2}Pay the deposit$/);
  });

  test("two items on one day take two rows and none overlaps", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("First thing"), todo("Second thing"), todo("Other day", addDays(TODAY, 30))])]);
    const top = (title: string) => Number.parseInt(screen.getByRole("button", { name: new RegExp(`^To-do: ${title}\\.`) }).closest("li")!.style.top, 10);
    expect(top("First thing")).not.toBe(top("Second thing"));
    // A day far from them shares a row with the first of them: nothing of theirs reaches it.
    expect([top("First thing"), top("Second thing")]).toContain(top("Other day"));
    expect(top("Other day")).toBe(Math.min(top("First thing"), top("Second thing")));
  });

  test("two weeks label every day, with today named in words as well as outlined", async () => {
    window.localStorage.setItem("cockpit:schedule-timeline-range", "two_weeks");
    const { calls } = await open();
    expect(calls.some((c) => c.route === "GET schedule/timeline?range=two_weeks")).toBe(true);
    for (let n = 0; n < 14; n++) {
      const d = addDays(TODAY, n);
      expect(screen.getByText(`${weekday(d)} ${dayOfMonth(d)}`)).toBeInTheDocument();
    }
    expect(screen.getByText(`${weekday(TODAY)} ${dayOfMonth(TODAY)}`)).toHaveAttribute("data-today");
    expect(screen.getByText("Today", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: `${shortRange(TODAY, addDays(TODAY, 13)).start} – ${shortRange(TODAY, addDays(TODAY, 13)).end}` })).toBeInTheDocument();
  });

  test("longer ranges label the weeks, and the range pick is remembered and asked for", async () => {
    const user = userEvent.setup();
    const { calls } = await open();
    expect(screen.queryByText(`${weekday(TODAY)} ${dayOfMonth(TODAY)}`)).toBeNull();
    await user.click(screen.getByRole("radio", { name: "A quarter" }));
    await waitFor(() => expect(calls.some((c) => c.route === "GET schedule/timeline?range=quarter")).toBe(true));
    expect(window.localStorage.getItem("cockpit:schedule-timeline-range")).toBe("quarter");
    await user.click(screen.getByRole("button", { name: "Later" }));
    await waitFor(() => expect(calls.some((c) => c.route === `GET schedule/timeline?from=${addDays(TODAY, 91)}&range=quarter`)).toBe(true));
    await user.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(calls.filter((c) => c.route === "GET schedule/timeline?range=quarter").length).toBeGreaterThan(1));
  });

  test("focus on an item shows its details under the lanes, and Enter on a calendar entry opens its details", async () => {
    const user = userEvent.setup();
    await open();
    expect(screen.getByText(/Move over an item, or tab to it/)).toBeInTheDocument();
    const send = screen.getByRole("button", { name: /^To-do: Send the quote\./ });
    send.focus();
    const details = await screen.findByLabelText("Send the quote", { selector: "section" });
    expect(within(details).getByText("Quinn Sample")).toBeInTheDocument();
    expect(within(details).getByText("Harbor")).toBeInTheDocument();
    expect(within(details).getByText("Open")).toBeInTheDocument();
    send.blur();
    await waitFor(() => expect(screen.getByText(/Move over an item, or tab to it/)).toBeInTheDocument());
    const standup = screen.getByRole("button", { name: /^Calendar entry: Standup\./ });
    standup.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("link", { name: "Open the event" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("link", { name: "Open the event" })).toBeNull());
  });

  test("an item arriving under a still pointer does not replace the one keyboard focus chose; moving over it does", async () => {
    await open();
    const send = screen.getByRole("button", { name: /^To-do: Send the quote\./ });
    const standup = screen.getByRole("button", { name: /^Calendar entry: Standup\./ });
    // The cursor and the pointer move inside act, so the details are on the page when each returns: nothing here waits for a
    // render that a busy computer could be late with.
    act(() => send.focus());
    expect(screen.getByLabelText("Send the quote", { selector: "section" })).toBeInTheDocument();
    fireEvent.mouseEnter(standup.closest("li") as HTMLElement);
    expect(screen.getByLabelText("Send the quote", { selector: "section" })).toBeInTheDocument();
    fireEvent.mouseMove(standup.closest("li") as HTMLElement);
    expect(screen.getByLabelText("Standup", { selector: "section" })).toBeInTheDocument();
  });

  test("Enter on a to-do goes to its page", async () => {
    const user = userEvent.setup();
    await open();
    screen.getByRole("button", { name: /^To-do: Send the quote\./ }).focus();
    await user.keyboard("{Enter}");
    // The page change lands after the key's handler; on a busy machine that is later than the key returns.
    await waitFor(() => expect(window.location.hash).toBe("#records/action/ACT-Send%20the%20quote"));
  });

  test("days off are hatched on every lane, and a lane's own days off are named in the details of an item that falls on one", async () => {
    const day = addDays(TODAY, 2);
    await open(
      [lane("PRJ-1", "Harbor", [todo("Send the quote", day)], { days_off: [{ day, kind: "team", reason: "closed for the move" }] })],
      { off_days: [{ day: addDays(TODAY, 5), kind: "weekend", reason: "" }, { day: addDays(TODAY, 6), kind: "holiday", reason: "Thanksgiving" }] },
    );
    expect(document.querySelectorAll("[data-off='weekend']")).toHaveLength(1);
    expect(document.querySelectorAll("[data-off='holiday']")).toHaveLength(1);
    expect(document.querySelectorAll("[data-off='team']")).toHaveLength(1);
    expect(screen.getByText(/Days off on this lane: .*closed for the move/)).toBeInTheDocument();
    screen.getByRole("button", { name: /^To-do: Send the quote\./ }).focus();
    expect(await screen.findByText(/closed for the move/, { selector: "dd" })).toBeInTheDocument();
  });

  test("with several sides the lanes are grouped under a heading for each side", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("A")], { side: "SIDE-1" }), lane("PRJ-9", "Home", [todo("B")], { side: "SIDE-2" })], {}, {
      "GET setup/business": () => ({ business: true, name: "The shop", personal: "SIDE-2", sides: [{ project: "SIDE-1", name: "The shop", kind: "business" }], chosen: "work" }),
    });
    expect(await screen.findByRole("heading", { level: 3, name: "The shop" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "Harbor" })).toBeInTheDocument();
  });

  test("nothing in the range draws no notice, and the to-dos with no date are counted under the timeline with a link to where they are listed", async () => {
    await open([], {}, {
      "GET open-items": () => ({
        actions: [{ id: "A-1", version: 1, text: "Tidy the style sheet", state: "open", owners: [], due: null, project: "PRJ-1", project_name: "Harbor", needs_date: true, views: [] }],
        questions: [],
        stale_days: 21,
      }),
    });
    expect(document.querySelector("[data-schedule-empty]")).toBeNull();
    expect(await screen.findByText(/1 to-do needs a date, so it is not on the timeline/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set dates in To-dos" })).toHaveAttribute("href", expect.stringContaining("work/open"));
    // The to-dos themselves, with their pickers, are in To-dos only.
    expect(screen.queryByRole("heading", { name: /Needs a date/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Set" })).toBeNull();
  });

  test("in a window too narrow for the weeks the same items are a list by week and nothing needs sideways room", async () => {
    room(300);
    await open();
    expect(document.querySelector("[data-week-list]")).not.toBeNull();
    expect(document.querySelector("[data-mode='list']")).not.toBeNull();
    expect(screen.queryByRole("group", { name: "Lanes by project" })).toBeNull();
    const week = screen.getByRole("region", { name: `Week of ${monthDayLong(TODAY)}` });
    const rows = within(week).getAllByRole("button");
    expect(rows.length).toBeGreaterThan(3);
    const row = within(week).getByRole("button", { name: /Send the quote/ });
    expect(row).toHaveTextContent("Harbor");
    expect(row.querySelector("[data-shape='square']")).not.toBeNull();
    // Each week that has something has its own heading, and a week with nothing has none.
    expect(screen.getAllByRole("heading", { level: 3, name: /^Week of / }).length).toBeGreaterThan(1);
    expect(names().length).toBeGreaterThan(0);
  });

  test("the 5 key picks the Timeline", async () => {
    window.localStorage.clear();
    fakeApi({ ...timelineRoutes(LANES), "GET schedule": () => ({ today: TODAY, first: TODAY, days: [], on_its_way: [], work_days: [0, 1, 2, 3, 4], week_starts_on: 0, grid_starts: "07:00", grid_ends: "19:00", month_entries: 3 }) });
    renderApp(<Schedule />);
    await screen.findByRole("tab", { name: "Work week" });
    fireEvent.keyDown(document.body, { key: "5" });
    await screen.findByRole("group", { name: "Lanes by project" });
  });
});

describe("a mark on one day carries its title", () => {
  test("each one-day item shows its title beside its mark, and a bar does not", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2)), item({ title: "Site visit", kind: "entry", id: "EVT-9", end: addDays(TODAY, 2), entry: entry({ title: "Site visit", own: true, kind: "own", snapshot: "EVT-9", source: "" }) }, addDays(TODAY, 1))])]);
    const one = screen.getByRole("button", { name: /^To-do: Send the quote\./ });
    expect(one).toHaveTextContent("Send the quote");
    expect(one).not.toHaveAttribute("data-bar");
    expect(screen.getByRole("button", { name: /^Calendar entry: Site visit\./ })).toHaveAttribute("data-bar");
  });

  test("the key lists only what is on the screen", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])]);
    const key = screen.getByRole("list", { name: "Key" });
    expect(within(key).getByText("To-do or promise with a day")).toBeInTheDocument();
    expect(within(key).queryByText("Overdue")).toBeNull();
    expect(within(key).queryByText("Calendar entry")).toBeNull();
  });
});

describe("a daily repeat is one band and the key matches the chart", () => {
  test("an item over several days is a bar named with its days, and a calendar entry's key is its calendar's color", async () => {
    await open([lane("PRJ-1", "Harbor", [item({ title: "Stand-up", kind: "entry", id: "EVT-3", end: addDays(TODAY, 4), entry: entry({ title: "Stand-up", snapshot: "snap-3", entry: "EVT-3", source: "cal-a" }) }, TODAY)])], {}, {});
    const bar = screen.getByRole("button", { name: /^Calendar entry: Stand-up\. .* to .*/ });
    expect(bar).toHaveAttribute("data-bar");
    expect(screen.getAllByRole("button", { name: /Stand-up/ })).toHaveLength(1);
  });
});

describe("the Timeline's finishing", () => {
  test("lanes with nothing in the range are named in one line under the chart, not a full row each, and the chart says how many items it shows", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))]), lane("PRJ-3", "Quiet one", []), lane("PRJ-4", "Quiet two", [])]);
    expect(screen.queryByRole("list", { name: "Items on the Quiet one lane" })).toBeNull();
    expect(screen.getByText("No dates in these weeks: Quiet one, Quiet two")).toBeInTheDocument();
    // The count is the page's own line under its title, so the title block is as tall here as on the other views.
    expect(document.querySelector("[data-timeline-count]")).toHaveTextContent("1 item");
  });

  test("with nothing on it the Timeline draws no notice and no button, and no legend for patterns that are not shown (S-0525)", async () => {
    await open([lane("PRJ-1", "Harbor", [])], { off_days: [{ day: addDays(TODAY, 3), kind: "weekend", reason: null }] });
    expect(document.querySelector("[data-timeline]")).not.toBeNull();
    expect(document.querySelector("[data-schedule-empty]")).toBeNull();
    expect(screen.queryByText("Nothing with a date in these weeks")).toBeNull();
    expect(screen.queryByRole("button", { name: "Look at later weeks" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Key" })).toBeNull();
  });

  test("in the list by week a calendar entry keeps its calendar's color, so a phone loses no meaning", async () => {
    room(300);
    await open(LANES, {}, { "GET watch": () => [{ id: "cal-work", label: "Work calendar", connector: "k", connector_label: "K", enabled: true, every_minutes: 15, items: 1, failures: 0, problem: null, reads: ["calendar"], shown_color: "teal" }] });
    const standup = document.querySelector<HTMLElement>('[data-week-list] button[data-kind="entry"][data-color]');
    expect(standup).not.toBeNull();
  });
});

describe("the Timeline's clashes", () => {
  const pair = (day: string) => ({ group: `g-${day}`, day, first: { snapshot: "snap-1", start: `${day}T09:00:00+00:00` }, second: { snapshot: "snap-2", start: `${day}T09:15:00+00:00` }, kind: "overlap" as const, minutes: 15, travel_minutes: 30 });

  test("the subtitle counts the clashes the range holds, with the first one's day, beside the items", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])], { clashes: [pair(addDays(TODAY, 3)), pair(addDays(TODAY, 9))] });
    expect(document.querySelector("[data-timeline-clashes]")).toHaveTextContent(`2 clashes: 4 meetings overlap · the first on ${weekday(addDays(TODAY, 3))}`);
    expect(document.querySelector("[data-timeline-clashes]")).toHaveAttribute("title", `The first clash is on ${monthDayLong(addDays(TODAY, 3))}`);
    expect(document.querySelector("[data-timeline-count]")).toHaveTextContent("1 item");
  });

  test("pairs that share a meeting are one clash, so a run of three overlapping meetings is counted once", async () => {
    const day = addDays(TODAY, 3);
    const chain = [pair(day), { ...pair(day), first: { snapshot: "snap-2", start: `${day}T09:15:00+00:00` }, second: { snapshot: "snap-3", start: `${day}T09:20:00+00:00` } }];
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])], { clashes: chain });
    expect(document.querySelector("[data-timeline-clashes]")).toHaveTextContent("1 clash: 3 meetings overlap");
  });

  test("one clash is said in the singular, and a range with none says nothing about clashes", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])], { clashes: [pair(addDays(TODAY, 3))] });
    expect(document.querySelector("[data-timeline-clashes]")).toHaveTextContent("1 clash: 2 meetings overlap");
  });

  test("a range with no clashes has no clash line", async () => {
    await open([lane("PRJ-1", "Harbor", [todo("Send the quote", addDays(TODAY, 2))])], { clashes: [] });
    expect(document.querySelector("[data-timeline-clashes]")).toBeNull();
  });
});
