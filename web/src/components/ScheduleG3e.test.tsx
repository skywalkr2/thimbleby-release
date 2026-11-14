import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays } from "../lib/dates";
import type { S } from "../lib/api";
import { entry, item, lane, scheduleRoutes, timelineRoutes, TODAY, WEEK } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// The Schedule's third round (design 7.7): a lane with many items stands as its items by week; a failed schedule gives its cause with one
// quiet retry.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
afterEach(() => {
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});

describe("a lane with many items", () => {
  test("is its items by week, not a staircase, a lane with a few keeps its track", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("cockpit:schedule-view", "timeline");
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1400 });
    const many = Array.from({ length: 36 }, (_, n) => item({ title: `Step ${n + 1}`, kind: "todo" }, addDays(TODAY, n % 3)));
    fakeApi(timelineRoutes([lane("PRJ-1", "Everything", many), lane("PRJ-2", "Small", [item({ title: "One thing", kind: "todo" }, addDays(TODAY, 1))])]));
    renderApp(<Schedule />);
    await waitFor(() => expect(document.querySelector("[data-timeline]")).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll("[data-lane-by-week]")).toHaveLength(1));
    const weeks = document.querySelector('[data-lane-by-week][data-lane="PRJ-1"]') as HTMLElement;
    expect(weeks).not.toBeNull();
    // It has its own heading and sits apart from the dated axis; the small lane stays on the axis.
    expect(weeks.querySelector("h3")).toHaveTextContent("Everything, by week");
    expect(document.querySelector("[data-axis]")?.contains(weeks)).toBe(false);
    expect(document.querySelector('[data-axis]')?.parentElement?.querySelector('[data-lane="PRJ-2"]')).not.toBeNull();
    expect(document.querySelector('[data-axis]')?.parentElement?.querySelector('[data-lane="PRJ-1"]')).toBeNull();
    // Every item is still a button.
    expect(weeks.querySelectorAll("button")).toHaveLength(36);
  });
});

describe("a calendar that can't be read", () => {
  test("never says an address and offers one quiet button", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("cockpit:schedule-view", "day");
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    const make = (id: string, label: string, over = {}) =>
      ({ id, label, connector: "pack/calendar", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], account: label, ...over }) as S["WatchSourceView"];
    const stale = make("cal-a", "robin@example.com", { account_state: "expired" });
    fakeApi(scheduleRoutes(undefined, {}, { "GET watch": () => [stale, make("cal-b", "other@example.com")], "GET sign-ins": () => [{ name: "pack/account", label: "Example mail", status: "expired", ready: true, several: true, accounts: [], callback: "x", allows: [] }] }));
    renderApp(<Schedule />);
    const line = await screen.findByRole("list", { name: "Calendars that need you to sign in" });
    expect(line.innerHTML).not.toContain("robin");
    const button = await within(line).findByRole("button", { name: /Sign in again/ });
    expect(button).toHaveAttribute("data-variant", "secondary");
  });
});

describe("a timeline of one lane with many items", () => {
  test("has no date axis and no Today marker over its weeks", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("cockpit:schedule-view", "timeline");
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1400 });
    const many = Array.from({ length: 36 }, (_, n) => item({ title: `Step ${n + 1}`, kind: "todo" }, addDays(TODAY, n % 3)));
    fakeApi(timelineRoutes([lane("PRJ-1", "Everything", many)]));
    renderApp(<Schedule />);
    await waitFor(() => expect(document.querySelector("[data-lane-by-week]")).not.toBeNull());
    expect(document.querySelector("[data-axis]")).toBeNull();
    expect(screen.queryByText("Today", { selector: "span" })).toBeNull();
  });
});

describe("the Add form", () => {
  test("an all-day meeting needs no start: Ends at says All day, no hint contradicts it, and Add says what is missing", async () => {
    window.localStorage.clear();
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    const user = userEvent.setup();
    fakeApi(scheduleRoutes());
    renderApp(<Schedule />);
    await user.click(await screen.findByRole("button", { name: "Add to schedule" }));
    const drawer = await screen.findByRole("dialog", { name: "Add a meeting" });
    expect(within(drawer).getByLabelText("Ends at")).toBeDisabled();
    expect(within(drawer).getByLabelText("Ends at")).toHaveAttribute("placeholder", "All day");
    expect(within(drawer).queryByText("Give a start time first.")).toBeNull();
    // Nothing is said yet: Add is held, with its reason.
    expect(within(drawer).getByRole("button", { name: /^Add$/ })).toBeDisabled();
    await user.type(within(drawer).getByRole("textbox", { name: "What" }), "Site walk");
    // With a title and no start (all day) Add is ready.
    expect(within(drawer).getByRole("button", { name: /^Add$/ })).toBeEnabled();
    await user.type(within(drawer).getByLabelText("Starts at"), "15:00");
    await user.tab();
    expect(within(drawer).getByLabelText("Ends at")).toBeEnabled();
    expect(within(drawer).getByLabelText("Ends at")).toHaveAttribute("placeholder", "No end time");
  });
});

describe("the cue for meetings out of sight", () => {
  // The hours drawn take in the hour now when today is in view, so the clock is the fixture's day at noon: the cues are measured on the same
  // grid whatever the time the tests run.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(`${TODAY}T12:00:00`));
  });
  afterEach(() => vi.useRealTimers());
  // Each meeting counts once, by its own start and end: below when it starts at or under the frame's bottom, above when it ends at or over
  // the headings' line; one partly in view counts as neither. The boxes are made up: the frame is 100 to 500 (or as given), the lane starts
  // at `laneTop` and is 72 px an hour.
  const rect = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  function frame(laneTop: number, frameBottom = 500) {
    return vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.getAttribute("data-scroller") !== null) return rect(100, frameBottom);
      if (this.tagName === "UL" && this.hasAttribute("data-day")) return rect(laneTop, laneTop + document.querySelectorAll("[data-hour]").length * 72);
      return rect(0, 0);
    });
  }
  async function render(content = scheduleRoutes(), view = "day", wait = /Standup/) {
    window.localStorage.clear();
    window.localStorage.setItem("cockpit:schedule-view", view);
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1440 });
    fakeApi(content);
    renderApp(<Schedule />);
    await screen.findByRole("heading", { level: 2, name: /2026/ });
    await screen.findAllByRole("button", { name: wait });
  }
  const cue = (which: "above" | "below") => screen.queryByRole("button", { name: new RegExp(`more meetings? ${which}$`) });
  // The fixture's Standup is 9:00 to 9:30, the Dentist at 12:00 (a short block), the Design review at 15:00; the grid starts at 7 AM.

  test("with every meeting in the frame there is no cue", async () => {
    const spy = frame(100, 1500);
    await render();
    expect(cue("above")).toBeNull();
    expect(cue("below")).toBeNull();
    spy.mockRestore();
  });
  test("a meeting that starts under the frame's bottom is counted below, once", async () => {
    const spy = frame(100);
    await render();
    expect(await screen.findByRole("button", { name: /^1 more meeting below$/ })).toBeInTheDocument();
    expect(cue("above")).toBeNull();
    spy.mockRestore();
  });
  test("meetings that end over the frame's top are counted above; none is counted by its box", async () => {
    const spy = frame(-300);
    await render();
    expect(await screen.findByRole("button", { name: /^2 more meetings above$/ })).toBeInTheDocument();
    expect(cue("below")).toBeNull();
    spy.mockRestore();
  });
  test("a member of a group card below the fold is counted once, whether its row is drawn or counted in the card's +N more", async () => {
    const spy = frame(100, 150);
    const titles = ["Quarterly planning review", "Supplier negotiation", "Venue walk-through", "Budget check-in"];
    const day = (date: string) => ({ timed: titles.map((title, n) => entry({ title, begins: `${date}T10:${40 + n * 5}:00+00:00`, ends: `${date}T11:${String(n * 5).padStart(2, "0")}:00+00:00`, start: `${date}T10:${40 + n * 5}:00+00:00` }, date)) });
    await render(scheduleRoutes((date) => (date === TODAY ? day(date) : {})), "week", /Quarterly planning/);
    expect(await screen.findByRole("button", { name: /^4 more meetings below$/ })).toBeInTheDocument();
    spy.mockRestore();
  });
  test("the Week and the Work week over the same days and the same frame count the same", async () => {
    const spy = frame(100);
    const content = scheduleRoutes((date) => (date === TODAY ? { timed: WEEK(date).timed } : {}));
    await render(content, "week");
    const text = async () => (await screen.findByRole("button", { name: /more meetings? below$/ })).textContent;
    const week = await text();
    await userEvent.setup().click(screen.getByRole("tab", { name: "Work week" }));
    await waitFor(async () => expect(await text()).toBe(week));
    spy.mockRestore();
  });
});
