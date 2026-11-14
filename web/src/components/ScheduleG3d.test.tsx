import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays } from "../lib/dates";
import { clash, entry, scheduleRoutes, TODAY, WEEK, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { Schedule } from "./Schedule";

// The Schedule's second round (design 7.7): the view tabs, the to-do's one mark, a clash drawn at its true times, and a cut grid that says so.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
function width(w: number) {
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => w });
}
beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => {
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});

async function open(content: Content = WEEK, over = {}, extra: Routes = {}) {
  const calls = fakeApi(scheduleRoutes(content, over, extra));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2, name: /–|2026/ });
  await waitFor(() => {
    const last = calls.filter((c) => c.route.startsWith("GET schedule")).at(-1)?.route ?? "";
    const from = /from=(\d{4}-\d{2}-\d{2})&days=(\d+)/.exec(last);
    expect(from !== null && from[1] <= TODAY && TODAY <= addDays(from[1], Number(from[2]) - 1)).toBe(true);
  });
  await waitFor(() => expect(document.querySelector(`[data-day="${TODAY}"]`)).not.toBeNull());
  return calls;
}

describe("the view tabs", () => {
  test("the views are a tab list: one tab in the tab order, the arrows move and choose, Home and End go to the ends", async () => {
    const user = userEvent.setup();
    await open();
    const list = screen.getByRole("tablist", { name: "View" });
    const tabs = within(list).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Day", "Work week", "Week", "Month", "Timeline"]);
    expect(tabs.filter((t) => t.tabIndex === 0)).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Work week" })).toHaveAttribute("aria-selected", "true");
    screen.getByRole("tab", { name: "Work week" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Week" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Week" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Timeline" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Day" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("a to-do among the entries", () => {
  test("has the To-dos list's mark, named for it, that marks it done with Undo; a calendar's entry has none", async () => {
    const user = userEvent.setup();
    const calls = fakeApi({
      ...scheduleRoutes((date) => (date === TODAY ? { all_day: [entry({ title: "Send the figures", kind: "due", action: "ACT-1", slot: "all_day", all_day: true, source: "", snapshot: "ACT-1" })], timed: WEEK(date).timed } : {})),
      "POST actions/ACT-1/status": () => ({ ok: "ACT-1", request: null }),
    });
    renderApp(<Schedule />);
    const mark = await screen.findByRole("button", { name: "Mark done: Send the figures" });
    expect(mark).toHaveAttribute("title", "Mark done");
    expect(screen.queryByRole("button", { name: /^Mark done: (Standup|Dentist)/ })).toBeNull();
    await user.click(mark);
    await waitFor(() => expect(calls.find((c) => c.route === "POST actions/ACT-1/status")?.body).toEqual({ status: "done" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.route === "POST actions/ACT-1/status").pop()?.body).toEqual({ status: "open" }));
  });
});

describe("a clash", () => {
  const planning = (date: string) => entry({ title: "Planning", begins: `${date}T09:15:00+00:00`, ends: `${date}T10:00:00+00:00` });
  const content: Content = (date) => (date === TODAY ? { timed: [planning(date), ...(WEEK(date).timed ?? [])] } : {});
  const over = () => ({ clashes: [clash((WEEK(TODAY).timed ?? [])[0], planning(TODAY))] });

  test("where the column has room each meeting stands at its own time, with one Clash marker, in words and an icon", async () => {
    const user = userEvent.setup();
    width(1200);
    await open(content, over());
    await user.click(screen.getByRole("tab", { name: "Day" }));
    const group = await screen.findByRole("group", { name: /^Clash: 2 meetings overlap, .+ to .+$/ });
    expect(group.querySelectorAll("[data-clash-tag]")).toHaveLength(1);
    // The first lane starts with the word and its icon, never the icon alone.
    expect(within(group).getByText("Clash")).toBeInTheDocument();
    expect(group.querySelector("[data-clash-tag]")?.closest("li")).toHaveAttribute("data-first");
    const members = Array.from(group.querySelectorAll<HTMLElement>(":scope > li"));
    expect(members).toHaveLength(2);
    // Each stands at its own start inside the clash's span, and they share the width.
    expect(members.map((m) => m.style.top)).not.toContain("");
    expect(members.map((m) => m.style.width)).toEqual(["calc(50% - 2px)", "calc(50% - 2px)"]);

  });

  test("a lane shows whole lines only: a place that would be half drawn is one line, or left out, and the whole is on hover", async () => {
    const user = userEvent.setup();
    width(1200);
    const rect = (bottom: number) => ({ top: 0, left: 0, right: 100, bottom, width: 100, height: bottom, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
    // The line's box ends at 80. The place runs to 100 as two lines, to 90 as one, so it is cut either way: it is left out.
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.matches("[class*='linePlace']")) return rect(100);
      if (this.matches("[data-entry-line]")) return rect(80);
      return rect(0);
    });
    try {
      const long = (title: string, from: string, to: string) => entry({ title, begins: `${TODAY}T${from}:00+00:00`, ends: `${TODAY}T${to}:00+00:00`, start: `${TODAY}T${from}:00+00:00`, where: "Room 1" });
      const hour = [long("Budget talk", "09:00", "10:00"), long("Lunch with Sam", "09:30", "10:30")];
      await open((date) => (date === TODAY ? { timed: hour } : {}), { clashes: [clash(hour[0], hour[1])] });
      await user.click(screen.getByRole("tab", { name: "Day" }));
      const lane = (await screen.findByRole("group", { name: /^Clash: / })).querySelector<HTMLElement>("button[data-entry-key]") as HTMLElement;
      await waitFor(() => expect(lane).toHaveAttribute("data-place-hidden"));
    } finally {
      spy.mockRestore();
    }
  });

  test("in a column too narrow for two readable meetings it is one card that names them all", async () => {
    width(900);
    await open(content, over());
    const card = await screen.findByRole("group", { name: /^Clash: 2 meetings overlap, .+ to .+$/ });
    expect(card.querySelector("[data-clash-tag]")).toBeNull();
    // The card's heading says the word too.
    expect(within(card).getByText(/^Clash · they overlap by \d+ min$/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /Standup/ })).toBeInTheDocument();
  });
});

describe("a grid cut at the bottom", () => {
  test("says how many meetings are below, and a press scrolls to them", async () => {
    const user = userEvent.setup();
    width(1200);
    const rect = (top: number, bottom: number) => () => ({ top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.getAttribute("data-scroller") !== null) return rect(0, 400)();
      // The lane is 72 px an hour from the grid's first hour, so the meetings that start after the frame's bottom are below it.
      if (this.tagName === "UL" && this.hasAttribute("data-day")) return rect(0, document.querySelectorAll("[data-hour]").length * 72)();
      return rect(0, 0)();
    });
    const scrolled = vi.fn();
    Element.prototype.scrollBy = scrolled as unknown as typeof Element.prototype.scrollBy;
    await open(WEEK);
    const cue = await screen.findByRole("button", { name: /more meetings? below$/ });
    await user.click(cue);
    expect(scrolled).toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("a meeting's card", () => {
  test("says the place beside the time, as the calendar's own card does", async () => {
    const user = userEvent.setup();
    width(1200);
    await open((date) => (date === TODAY ? { timed: [entry({ title: "Site visit", where: "Room 4", begins: `${date}T13:00:00+00:00`, ends: `${date}T15:00:00+00:00` })] } : {}));
    await user.click(screen.getByRole("tab", { name: "Day" }));
    const card = await screen.findByRole("button", { name: /Site visit/ });
    expect(card).toHaveTextContent("Room 4");
  });
});
