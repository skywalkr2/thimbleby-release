import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { addDays } from "../lib/dates";
import { allDay, clash, entry, scheduleRoutes, TODAY, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// The calendar at each width (design 7.7): seven days wide, the working days below 1100px, and a list by day on a phone; the
// calendars as toggles; a clash as one card naming its meetings; an entry held in two calendars shown once.

const calendar = (id: string, label: string, shown_color: S["WatchSourceView"]["shown_color"]) =>
  ({ id, label, connector: "k", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], shown_color }) as S["WatchSourceView"];
const CALENDARS = [calendar("cal-a", "Home calendar", "blue"), calendar("cal-b", "Clinic calendar", "teal")];

const venue = entry({ title: "Venue walk-through", source: "cal-a", begins: `${TODAY}T14:30:00+00:00`, ends: `${TODAY}T15:30:00+00:00` });
const budget = entry({ title: "Budget check-in", source: "cal-b", begins: `${TODAY}T14:45:00+00:00`, ends: `${TODAY}T15:15:00+00:00` });
const pickup = entry({ title: "School pickup", source: "cal-a", begins: `${TODAY}T14:50:00+00:00`, ends: `${TODAY}T15:20:00+00:00` });
const content: Content = (date) =>
  date === TODAY
    ? {
        all_day: [allDay("Due: revised budget", date, { source: "cal-b" })],
        timed: [
          venue,
          budget,
          pickup,
          entry({ title: "Quarterly review", source: "cal-a", also_in: ["cal-b"], begins: `${date}T10:00:00+00:00`, ends: `${date}T11:00:00+00:00` }),
        ],
      }
    : {};
// The engine names the three meetings' pairs; the screen draws a clash only for pairs it names.
const CLASHES = [clash(venue, budget, { minutes: 30 }), clash(venue, pickup, { minutes: 30 }), clash(budget, pickup, { minutes: 25 })];

function window_(over: { wide?: boolean; phone?: boolean }) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: /max-width: 1099/.test(query) ? !over.wide : false,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  document.documentElement.toggleAttribute("data-narrow", !!over.phone);
}

async function open(view: string) {
  window.localStorage.setItem("cockpit:schedule-view", view);
  fakeApi(scheduleRoutes(content, { clashes: CLASHES }, { "GET watch": () => CALENDARS }));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-grid], [data-month], [data-schedule-list]")).not.toBeNull());
  await waitFor(() => expect(document.querySelector(`[data-day="${TODAY}"]`)).not.toBeNull());
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-narrow");
});

const lanes = () => Array.from(document.querySelectorAll("ul[data-day]")).map((el) => el.getAttribute("data-day"));

test("wide, the Week view has seven days; below 1100px it is the working days, and it says so", async () => {
  window_({ wide: true });
  await open("week");
  expect(lanes()).toHaveLength(7);
  expect(document.querySelector("[data-weekdays-only]")).toBeNull();
  document.body.innerHTML = "";
  window_({ wide: false });
  await open("week");
  expect(lanes()).toEqual([0, 1, 2, 3, 4].map((n) => addDays("2026-10-26", n)));
  expect(screen.getByText("Weekdays only at this width. Widen the window to see the weekend.")).toBeInTheDocument();
  // The tab still says Week: the person did not pick another view.
  expect(screen.getByRole("tab", { name: "Week" })).toHaveAttribute("aria-selected", "true");
});

test("on a phone the week is a list by day: each day a heading, a day with nothing says so, and a row opens its entry", async () => {
  const user = userEvent.setup();
  window_({ phone: true });
  await open("week");
  expect(document.querySelector("[data-grid]")).toBeNull();
  const list = await screen.findByRole("list", { name: "Entries by day" });
  expect(within(list).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toContain("Monday, October 26 · today");
  // The days with nothing on them are one line, not a row each.
  expect(within(list).getByText(/^Nothing on Tuesday, /)).toBeInTheDocument();
  const review = within(list).getByRole("button", { name: /Quarterly review/ });
  expect(review).toHaveTextContent("In 2 calendars");
  await user.click(review);
  expect(await screen.findByText("Quarterly review", { selector: "h2, h3" })).toBeInTheDocument();
});

test("meetings that overlap are one row naming them, with how long they overlap, and one card in the grid", async () => {
  window_({ phone: true });
  await open("work_week");
  const group = await screen.findByRole("group", { name: /^Clash: 3 meetings overlap, .+ to .+$/ });
  expect(within(group).getByText("Clash · 3 at once, they overlap by 30 min")).toBeInTheDocument();
  expect(within(group).getAllByRole("button")).toHaveLength(3);
  document.body.innerHTML = "";
  window_({ wide: true });
  await open("day");
  const card = await screen.findByRole("group", { name: /^Clash: / });
  // A clash card says Clash and its reason in words; how many meetings and when is its tooltip, and each meeting has its own row.
  expect(within(card).getByText(/^Clash · (\d+ at once, )?they overlap by \d+ min$/)).toBeInTheDocument();
  expect(card.querySelector("p")).toHaveAttribute("title", expect.stringMatching(/^3 at once · /));
});

test("an entry held in two calendars is shown once, and says so in words", async () => {
  window_({ wide: true });
  await open("day");
  const blocks = screen.getAllByRole("button", { name: /Quarterly review/ });
  expect(blocks).toHaveLength(1);
  expect(blocks[0]).toHaveTextContent("In 2 calendars");
});

test("the calendars are toggles with their color: pressing one hides its entries and says Hidden in words, pressing it again shows them", async () => {
  const user = userEvent.setup();
  window_({ wide: true });
  await open("day");
  await user.click(await screen.findByRole("button", { name: "Calendars (2)" }));
  const home = within(await screen.findByRole("list", { name: "Calendars" })).getByRole("button", { name: /Home calendar/ });
  expect(home).toHaveAttribute("aria-pressed", "true");
  expect(home.querySelector("[data-color]")).toHaveAttribute("data-color", "blue");
  expect(screen.getByRole("button", { name: /Venue walk-through/, hidden: true })).toBeInTheDocument();
  await user.click(home);
  expect(home).toHaveAttribute("aria-pressed", "false");
  expect(within(home).getByText("Hidden")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Venue walk-through/, hidden: true })).toBeNull();
  await user.click(home);
  expect(screen.getByRole("button", { name: /Venue walk-through/, hidden: true })).toBeInTheDocument();
});

test("a block says its title, then its time and its calendar on a line under it", async () => {
  window_({ wide: true });
  await open("day");
  const block = screen.getByRole("button", { name: /Quarterly review/ });
  expect(block.querySelector("[data-entry-line]")).toHaveTextContent(/^10:00 AM · In 2 calendars$/);
  expect(block).toHaveAttribute("data-color", "blue");
});

test("a calendar whose account needs signing in again is named in one line over the calendar, with when its entries are from and the one button", async () => {
  window_({ wide: true });
  window.localStorage.setItem("cockpit:schedule-view", "day");
  const stale = { ...calendar("cal-a", "Home calendar", "blue"), account: "robin@example.com", account_state: "expired" as const, connector: "pack/calendar", read_at: "2026-11-03T10:51:00Z", last: { outcome: "failed" as const, error_kind: "auth", started_at: "2026-11-03T11:00:00Z", new: 0, changed: 0, removed: 0 } };
  fakeApi(scheduleRoutes(content, {}, { "GET watch": () => [stale, CALENDARS[1]], "GET sign-ins": () => [{ name: "pack/account", label: "Example mail", status: "expired", ready: true, several: true, accounts: [], callback: "x", allows: [] }] }));
  renderApp(<Schedule />);
  const line = await screen.findByRole("list", { name: "Calendars that need you to sign in" });
  // The line names the calendar (its side's name or the person's name for it) and says when it was last updated; the account's address is
  // nowhere on the page (it is on Connections).
  expect(line).toHaveTextContent(/^Home calendar isn't up to date\. Last updated /);
  expect(line).not.toHaveTextContent("robin@example.com");
  expect(line.innerHTML).not.toContain("robin");
  expect(await within(line).findByRole("button", { name: "Sign in again for Home calendar" })).toBeInTheDocument();
  // The entries it last read stay shown, and the ones from that calendar (not the other's) are marked as not up to date.
  const venue_ = await screen.findByRole("button", { name: /Venue walk-through/ });
  expect(venue_).toHaveAttribute("data-stale");
  expect(venue_).toHaveTextContent("Not up to date: its calendar needs you to sign in again.");
  expect(screen.getByRole("button", { name: /Budget check-in/ })).not.toHaveAttribute("data-stale");
});

test("on a phone the header is the title and a menu, and the moves and a short range are one row", async () => {
  const user = userEvent.setup();
  window_({ phone: true });
  await open("week");
  // The tab bar's plus hands something in, so adding to the schedule is in the menu and there is no button row for it.
  expect(screen.queryByRole("button", { name: "Add to schedule" })).toBeNull();
  const row = document.querySelector("[data-nav-row]") as HTMLElement;
  expect(within(row).getByRole("button", { name: "Today" })).toBeInTheDocument();
  expect(within(row).getByRole("heading", { level: 2 })).toHaveTextContent(/^Oct 26 – Nov 1$/);
  await user.click(screen.getByRole("button", { name: "More actions for Schedule" }));
  await user.click(await screen.findByRole("menuitem", { name: "Add to schedule" }));
  expect(await screen.findByRole("dialog", { name: "Add a meeting" })).toBeInTheDocument();
});

test("wide, Add to schedule is the header's button and the range is written out", async () => {
  window_({ wide: true });
  await open("week");
  expect(screen.getByRole("button", { name: "Add to schedule" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "More actions for Schedule" })).toBeNull();
  expect(within(document.querySelector("[data-nav-row]") as HTMLElement).getByRole("heading", { level: 2 })).toHaveTextContent("Oct 26 – Nov 1");
});

describe("the grid opens on what matters", () => {
  test("it scrolls inside its own labelled frame to the first clash, never to empty early hours", async () => {
    window_({ wide: true });
    await open("day");
    const frame = screen.getByRole("region", { name: "Hours of the day" });
    expect(frame).toHaveAttribute("data-scroller");
    expect(frame.querySelector("[data-grid]")).not.toBeNull();
    expect(frame.querySelector("[data-clash]")).not.toBeNull();
  });

  test("the frame is placed on the clash even when the day's entries arrive after the view was picked", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(5000);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      // The day's entries start part way down and the clash is further down: the frame opens at the first entry, never past it.
      const top = this.hasAttribute("data-clash") ? 900 : this.tagName === "LI" ? 600 : 0;
      return { top, bottom: top + 40, left: 0, right: 100, width: 100, height: 40, x: 0, y: top, toJSON: () => ({}) };
    });
    window_({ wide: true });
    await open("day");
    const frame = screen.getByRole("region", { name: "Hours of the day" });
    await waitFor(() => expect(frame.scrollTop).toBeGreaterThan(0));
    expect(frame.scrollTop).toBeLessThanOrEqual(600);
    vi.restoreAllMocks();
  });

  test("an hour on the edge is its short form, so it has room inside the gutter", async () => {
    window_({ wide: true });
    await open("day");
    const labels = Array.from(document.querySelectorAll("[data-hour]")).map((el) => el.textContent);
    expect(labels).toContain("10 AM");
    expect(labels.some((l) => /:00/.test(l ?? ""))).toBe(false);
  });

  test("the line that names the clashes is a button that goes to the first clash", async () => {
    window_({ wide: true });
    await open("day");
    const jump = document.querySelector<HTMLButtonElement>("[data-clash-jump]")!;
    expect(jump).not.toBeNull();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await userEvent.setup().click(jump);
    expect(scroll).toHaveBeenCalled();
  });
});

describe("the month marks a day with a clash", () => {
  test("a day the engine names a clash on shows a mark with words for a screen reader", async () => {
    window_({ wide: true });
    await open("month");
    const cell = document.querySelector(`[data-day="${TODAY}"]`)!;
    expect(cell.querySelector("[data-clash-mark]")).not.toBeNull();
    expect(within(cell as HTMLElement).getByText("Clash: 3 clashes on this day")).toBeInTheDocument();
    expect(cell.querySelector("[data-clash-mark]")).toHaveTextContent("3 clashes");
  });
});

test("on a phone a day of the month is chosen, and its entries are listed under the month", async () => {
  const user = userEvent.setup();
  window_({ phone: true });
  await open("month");
  const cell = document.querySelector(`[data-day="${TODAY}"]`) as HTMLElement;
  await user.click(within(cell).getByRole("button", { name: /Open/ }));
  const below = document.querySelector("[data-month-day-list]") as HTMLElement;
  expect(below).not.toBeNull();
  expect(within(below).getByRole("button", { name: /Venue walk-through/ })).toBeInTheDocument();
  expect(within(below).getByRole("button", { name: "Open this day" })).toBeInTheDocument();
});

const holiday = (n: number) => allDay("Public holiday", TODAY, { snapshot: `holiday-${n}`, source: "cal-a" });

test("identical all-day entries of a day are one with a count, and a day with none has no all-day strip at all", async () => {
  const user = userEvent.setup();
  window_({ wide: true });
  window.localStorage.setItem("cockpit:schedule-view", "week");
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { all_day: [holiday(1), holiday(2), holiday(3), allDay("Offsite", TODAY, { source: "cal-a" })], timed: [venue] } : {}), {}, { "GET watch": () => CALENDARS }));
  renderApp(<Schedule />);
  const strip = await screen.findByRole("list", { name: /^All day, Today/ });
  const buttons = within(strip).getAllByRole("button");
  expect(buttons).toHaveLength(2);
  expect(within(strip).getByRole("button", { name: /Public holiday.*3 identical entries/ })).toHaveTextContent("×3");
  await user.click(buttons[0]);
  expect(await screen.findByRole("heading", { name: "Public holiday" })).toBeInTheDocument();
});

test("the count is by kind from what is drawn: meetings, all day, due; a kind with none is left out, and a called-off entry is not counted", async () => {
  window_({ wide: true });
  window.localStorage.setItem("cockpit:schedule-view", "week");
  const todo = { ...venue, title: "Send the quote", kind: "due" as const, slot: "all_day" as const, begins: null, ends: null };
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: [venue, { ...venue, title: "Called off", cancelled: true }], all_day: [todo, { ...todo, title: "Another quote" }] } : {}), {}, { "GET watch": () => CALENDARS }));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-meetings]")).not.toBeNull());
  expect(document.querySelector("[data-meetings]")).toHaveTextContent(/^1 meeting · 2 due$/);
});

test("a week with no all-day entries draws no all-day row", async () => {
  window_({ wide: true });
  window.localStorage.setItem("cockpit:schedule-view", "week");
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: [venue] } : {}), {}, { "GET watch": () => CALENDARS }));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-grid]")).not.toBeNull());
  expect(screen.queryByText("All day")).toBeNull();
  expect(document.querySelector("ul[aria-label^='All day']")).toBeNull();
});

test("the Day column says which day it is without repeating the date the heading already gives", async () => {
  window_({ wide: true });
  await open("day");
  expect(screen.getByRole("heading", { level: 3, name: "Today" })).toBeInTheDocument();
});

test("the controls above the grid are two rows with the calendars among them, and the header is there while the days load", async () => {
  window_({ wide: true });
  window.localStorage.setItem("cockpit:schedule-view", "week");
  fakeApi(scheduleRoutes(content, { clashes: CLASHES }, { "GET watch": () => CALENDARS, "GET schedule": () => new Promise(() => undefined) }));
  renderApp(<Schedule />);
  // Before any day has arrived the page already has its title's buttons and its two rows.
  expect(await screen.findByRole("button", { name: "Add to schedule" })).toBeInTheDocument();
  expect(document.querySelectorAll("[data-bar-row]")).toHaveLength(2);
  await waitFor(() => expect(document.querySelector("[data-schedule-legend]")).not.toBeNull());
  const rows = Array.from(document.querySelectorAll("[data-bar-row]"));
  expect(rows[1].contains(document.querySelector("[data-schedule-legend]"))).toBe(true);
});

test("the week says its so-what in one line: the clashes and how many meetings there are", async () => {
  window_({ wide: true });
  await open("week");
  const sub = document.querySelector("[data-summary]");
  // The clash count is plain words with a small "Show it" beside it, then the counts as one piece.
  expect(sub?.querySelector("[data-clash-count]")).toHaveTextContent("1 clash this week");
  expect(sub?.querySelector("[data-clash-jump]")).toHaveTextContent("Show it");
  expect(sub?.querySelector("[data-meetings]")).toHaveTextContent("4 meetings · 1 all day");
});

test("Show all hours draws the whole day, and Show fewer hours goes back", async () => {
  const user = userEvent.setup();
  window_({ wide: true });
  await open("day");
  const hours = () => document.querySelectorAll("[data-hour]").length;
  const some = hours();
  expect(some).toBeLessThan(24);
  await user.click(screen.getByRole("button", { name: "Show all hours" }));
  expect(hours()).toBe(24);
  await user.click(screen.getByRole("button", { name: "Show fewer hours" }));
  expect(hours()).toBe(some);
});

test("a month says its so-what too, and a day's dots are inside the day's one button", async () => {
  window_({ wide: true });
  await open("month");
  expect(document.querySelector("[data-clash-count]")).toHaveTextContent("1 clash this month");
  expect(document.querySelector("[data-meetings]")).toHaveTextContent("4 meetings · 1 all day");
  const cell = document.querySelector(`section[data-day="${TODAY}"]`)!;
  const button = within(cell as HTMLElement).getAllByRole("button")[0];
  expect(button.querySelector("[class*='dots']")).not.toBeNull();
});

test("the calendars are always one \"Calendars (2)\" button that opens the list, never a row of chips", async () => {
  window_({ wide: true });
  await open("week");
  const legend = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[data-schedule-legend]");
    expect(found).not.toBeNull();
    return found!;
  });
  expect(within(legend).getAllByRole("button")).toHaveLength(1);
  const user = userEvent.setup();
  await user.click(within(legend).getByRole("button", { name: "Calendars (2)" }));
  const list = await screen.findByRole("list", { name: "Calendars" });
  expect(within(list).getAllByRole("button")).toHaveLength(2);
});

test("on a phone the calendars live in one Filter sheet, so the bar is the moves and the views only", async () => {
  const user = userEvent.setup();
  window_({ phone: true });
  await open("work_week");
  expect(document.querySelector("[data-schedule-legend]")).toBeNull();
  await user.click(await screen.findByRole("button", { name: "Filter" }));
  const sheet = await screen.findByRole("dialog", { name: "Filter" });
  const list = within(sheet).getByRole("list", { name: "Calendars" });
  expect(within(list).getAllByRole("button")).toHaveLength(2);
  await user.click(within(list).getAllByRole("button")[0]);
  await user.click(within(sheet).getByRole("button", { name: "Close" }));
  expect(await screen.findByRole("button", { name: "Filter (1)" })).toBeInTheDocument();
});

// The pass that brought the calendar up to its mockup: what each of these protects is named in its title.
describe("the calendar's finishing", () => {
  test("a phone's Week lists all seven days, Saturday and Sunday too, so it is not the Weekdays list", async () => {
    window_({ phone: true });
    window.localStorage.setItem("cockpit:schedule-view", "week");
    fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: [venue] } : {}), {}, { "GET watch": () => CALENDARS }));
    renderApp(<Schedule />);
    // The day with an entry is a section; the six with nothing are one line naming them, Saturday and Sunday among them.
    await waitFor(() => expect(document.querySelector("[data-schedule-list] [data-nothing-on]")?.textContent).toMatch(/Saturday, Sunday$/));
    expect(document.querySelectorAll("[data-schedule-list] section[data-day]")).toHaveLength(1);
  });

  test("on a phone the identical all-day entries of a day are one row with a count, as on a wide window", async () => {
    window_({ phone: true });
    window.localStorage.setItem("cockpit:schedule-view", "week");
    const holidays = [1, 2, 3].map((n) => allDay("Public holiday", TODAY, { source: "cal-a", snapshot: `H-${n}` }));
    fakeApi(scheduleRoutes((date) => (date === TODAY ? { all_day: holidays } : {}), {}, { "GET watch": () => CALENDARS }));
    renderApp(<Schedule />);
    const rows = await screen.findAllByRole("button", { name: /Public holiday/ });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("×3");
  });

  test("a block's second line is its time (and that it is in several calendars), and its calendar is in its tooltip, so a narrow column never cuts it to nonsense", async () => {
    window_({ wide: true });
    await open("day");
    // A meeting held in one calendar has its time and no calendar name on its line; the one held in two says so.
    expect(screen.getByRole("button", { name: /Quarterly review/ }).querySelector("[data-entry-line]")).toHaveTextContent(/^10:00 AM · In 2 calendars$/);
    expect(screen.getByRole("button", { name: /Quarterly review/ })).toHaveAttribute("title", expect.stringContaining("Quarterly review"));
  });

  test("a clash card is exactly its meetings' span: first start to last end, so it covers nothing after it", async () => {
    window_({ wide: true });
    await open("day");
    const card = (document.querySelector("[data-clash]") as HTMLElement).style;
    expect(card.top).not.toBe("");
    expect(card.height).toBe("calc(1 * var(--hour))");
  });

  test("what already shows without scrolling stays at the top, so the first hour is not slid under the headings", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(2000);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const top = this.hasAttribute("data-clash") ? 400 : 0;
      return { top, bottom: top + 40, left: 0, right: 100, width: 100, height: 40, x: 0, y: top, toJSON: () => ({}) };
    });
    window_({ wide: true });
    await open("day");
    expect(screen.getByRole("region", { name: "Hours of the day" }).scrollTop).toBe(0);
    vi.restoreAllMocks();
  });

  test("the grid opens on the day's earliest entry when the clash is still in the frame from there, so nothing early is scrolled out of sight", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(5000);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const top = this.hasAttribute("data-clash") ? 900 : this.matches("ul[data-day] > li") ? 700 : 0;
      return { top, bottom: top + 40, left: 0, right: 100, width: 100, height: 40, x: 0, y: top, toJSON: () => ({}) };
    });
    window_({ wide: true });
    await open("day");
    // The earliest entry is 700 down and the clash 900: the frame opens at the entry (less the headings and its margin, 40px each here), not at the clash.
    await waitFor(() => expect(screen.getByRole("region", { name: "Hours of the day" }).scrollTop).toBe(588));
    vi.restoreAllMocks();
  });

  test("an all-day entry over several days is one bar: each day joins the days beside it in its week", async () => {
    window_({ wide: true });
    window.localStorage.setItem("cockpit:schedule-view", "month");
    const day = (n: number) => addDays(TODAY, n);
    const offsite = (date: string) => allDay("Team offsite", date, { source: "cal-a", snapshot: "OFFSITE-1" });
    fakeApi(scheduleRoutes((date) => (date === day(0) || date === day(1) || date === day(2) ? { all_day: [offsite(date)] } : {}), {}, { "GET watch": () => CALENDARS }));
    renderApp(<Schedule />);
    await waitFor(() => expect(document.querySelectorAll("[data-month] button[data-join-from], [data-month] button[data-join-to]").length).toBeGreaterThan(0));
    // The month first drawn is the computer's; the server's today may name another, whose answer replaces it.
    const found = () => Array.from(document.querySelectorAll<HTMLElement>("[data-month] button[data-kind]")).filter((b) => /Team offsite/.test(b.textContent ?? ""));
    await waitFor(() => expect(found()).toHaveLength(3));
    const bars = found();
    // The first day of the run only goes on; one that is last only comes in; a day between does both (unless a week's edge cuts it).
    expect(bars.some((b) => b.hasAttribute("data-join-to"))).toBe(true);
    expect(bars.some((b) => b.hasAttribute("data-join-from"))).toBe(true);
  });
});
