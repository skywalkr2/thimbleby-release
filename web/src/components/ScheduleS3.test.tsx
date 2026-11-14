import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { clash, entry, scheduleRoutes, TODAY, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { Schedule } from "./Schedule";
import { roomForSideBySide } from "./ScheduleGrid";

// The side on the Schedule (design 7.7, the reviewer's Q6): a 3 px edge in the side's color on a grid entry; the side's dot and name
// wherever text is read (the details, a clash card's rows, a phone row, the banner); the side filter's chips as the color key; and no
// address, or the start of one, anywhere on the page. A clash card's "+N more" opens the clash in the side pane (Q2).

const PERSONAL = "PRJ-personal";
const harbor: S["SideView"] = { project: "PRJ-harbor", kind: "business", name: "Harborview", removable: false, filed: 0 };
const studio: S["SideView"] = { project: "PRJ-studio", kind: "business", name: "Studio Nine", removable: false, filed: 0 };
const source = (id: string, label: string, account: string, sides: string[], over: Partial<S["WatchSourceView"]> = {}) =>
  ({ id, label, connector: "k/calendar", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], account, sides, ...over }) as unknown as S["WatchSourceView"];
const SOURCES = [
  source("cal-p1", "Your calendar, avery.lane", "avery.lane@example.com", [PERSONAL]),
  source("cal-p2", "Your calendar, avery.lane.home", "avery.lane.home@example.com", [PERSONAL]),
  source("cal-h", "Your calendar, harbor.desk", "harbor.desk@example.com", [harbor.project]),
  source("cal-x", "Your calendar, shared.desk", "shared.desk@example.com", [harbor.project, studio.project]),
];
const ROUTES: Routes = {
  "GET setup/business": () => ({ business: true, name: harbor.name, personal: PERSONAL, sides: [harbor, studio], chosen: "work" }),
  "GET views": () => [],
  "GET watch": () => SOURCES,
};
const at = (title: string, from: string, to: string, over: Partial<S["ScheduleEntryView"]> = {}) => (date: string) => entry({ title, begins: `${date}T${from}:00+00:00`, ends: `${date}T${to}:00+00:00`, start: `${date}T${from}:00+00:00`, ...over }, date);
const DAY: Content = (date) =>
  date === TODAY
    ? { timed: [at("Budget talk", "09:00", "10:00", { source: "cal-h", side: harbor.project }), at("Lunch with Sam", "12:00", "13:00", { source: "cal-p1", side: PERSONAL }), at("Shared sync", "15:00", "16:00", { source: "cal-x", side: null, sides: [harbor.project, studio.project] })].map((make) => make(TODAY)) }
    : {};

async function open(view: string, content: Content = DAY, over = {}, extra: Routes = {}) {
  window.localStorage.setItem("cockpit:schedule-view", view);
  fakeApi(scheduleRoutes(content, over, { ...ROUTES, ...extra }));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2 });
  await waitFor(() => expect(document.querySelector(`[data-day="${TODAY}"]`)).not.toBeNull());
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-narrow");
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-narrow");
});

test("Q6: a grid entry's edge is its side's color slot, and an entry on no known side has a neutral edge", async () => {
  await open("day");
  // Personal is the first slot, then each side in the person's order.
  expect(await screen.findByRole("button", { name: /Lunch with Sam/ })).toHaveAttribute("data-side-slot", "1");
  expect(screen.getByRole("button", { name: /Budget talk/ })).toHaveAttribute("data-side-slot", "2");
  expect(screen.getByRole("button", { name: /Shared sync/ })).not.toHaveAttribute("data-side-slot");
  expect(screen.getByRole("button", { name: /Shared sync/ })).not.toHaveAttribute("data-color");
  // The side is in the entry's name too, so the color is never the only sign.
  expect(screen.getByRole("button", { name: /Budget talk.*on Harborview/ })).toBeInTheDocument();
});

test("Q6: the side filter's chips are the key: each side's dot, in the color its entries' edges have", async () => {
  await open("day");
  await screen.findByRole("button", { name: /Budget talk/ });
  const chips = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[aria-label='Show']");
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  const dots = Array.from(chips.querySelectorAll("[data-mark='side']")).map((d) => d.getAttribute("data-color"));
  expect(dots).toEqual(["1", "2", "3"]);
  expect(within(chips).getByText("Harborview").parentElement?.querySelector("[data-mark='side']")).toHaveAttribute("data-color", "2");
});

test("Q6: the details and a clash card's rows show the side's dot and name", async () => {
  const user = userEvent.setup();
  const pair = [at("Budget talk", "09:00", "10:00", { source: "cal-h", side: harbor.project })(TODAY), at("Lunch with Sam", "09:30", "10:30", { source: "cal-p1", side: PERSONAL })(TODAY)];
  await open("day", (date) => (date === TODAY ? { timed: pair } : {}), { clashes: [clash(pair[0], pair[1])] });
  const card = await screen.findByRole("group", { name: /^Clash: / });
  expect(Array.from(card.querySelectorAll("[data-side-mark]")).map((m) => m.textContent)).toEqual(["Harborview", "Personal"]);
  await user.click(within(card).getByRole("button", { name: /Budget talk/ }));
  const pane = await screen.findByRole("complementary", { name: "Budget talk" }).catch(() => screen.findByRole("dialog", { name: "Budget talk" }));
  expect(pane.querySelector("[data-side-mark]")).toHaveTextContent("Harborview");
});

test("Q6: no address, nor the start of one, is anywhere on the Schedule (the grid, the key, the calendars, the details)", async () => {
  const user = userEvent.setup();
  await open("day");
  await user.click(await screen.findByRole("button", { name: /^Calendars \(\d+\)/ }));
  const list = await screen.findByRole("list", { name: "Calendars" });
  // Two calendars on one side are told apart by a number, never by a part of an address.
  expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Personal", "Personal (2)", "Harborview", "Your calendar"]);
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: /Budget talk/ }));
  await screen.findByRole("heading", { level: 2, name: "Budget talk" });
  const page = document.documentElement.outerHTML;
  for (const word of ["@", "avery", "harbor.desk", "shared.desk"]) expect(page, `the page says "${word}"`).not.toContain(word);
});

test("Q6: the phone's list shows each row's side, not 'Personal · avery.lane'", async () => {
  document.documentElement.setAttribute("data-narrow", "");
  await open("week");
  const list = await screen.findByRole("list", { name: /by day/i }).catch(() => document.querySelector("[data-schedule-list]") as HTMLElement);
  const row = within(list as HTMLElement).getByRole("button", { name: /Lunch with Sam/ });
  expect(row.querySelector("[data-side-mark]")).toHaveTextContent("Personal");
  expect((list as HTMLElement).innerHTML).not.toContain("avery");
  expect((list as HTMLElement).textContent).not.toMatch(/Personal · /);
});

test("Q2: +N more opens the clash in the side pane, every meeting listed, each opening its own details", async () => {
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1440 });
  const box = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.hasAttribute("data-group-card")) return box(0, 100);
    if (this.tagName === "LI" && this.parentElement?.closest("[data-group-card]") && this.parentElement.tagName === "UL") return box(0, 40 * (Array.from(this.parentElement.children).indexOf(this) + 1));
    return box(0, 0);
  });
  const user = userEvent.setup();
  const titles = ["Quarterly planning review", "Supplier negotiation", "Venue walk-through", "Budget check-in"];
  const made = titles.map((title, n) => at(title, `10:${String(40 + n * 5).padStart(2, "0")}`, "11:50")(TODAY));
  await open("week", (date) => (date === TODAY ? { timed: made } : {}), { clashes: [clash(made[0], made[1]), clash(made[1], made[2]), clash(made[2], made[3])] });
  const more = await waitFor(() => {
    const found = document.querySelector<HTMLElement>(`ul[data-day="${TODAY}"] [data-group-more]`);
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  spy.mockRestore();
  await user.click(more);
  // The pane (a drawer where the window is narrow) lists all four, each a button.
  const pane = await screen.findByRole("dialog", { name: /The 4 meetings at/ });
  const rows = within(pane).getByRole("list", { name: "Meetings in this clash" });
  for (const title of titles) expect(within(rows).getByRole("button", { name: new RegExp(title) })).toBeInTheDocument();
  expect(document.querySelector("[role='dialog'] [data-popover], [data-popover]")).toBeNull();
  // Each opens its own details in the same pane, with a way back to the list.
  await user.click(within(rows).getByRole("button", { name: /Venue walk-through/ }));
  const own = await screen.findByRole("dialog", { name: "Venue walk-through" });
  await user.click(within(own).getByRole("button", { name: "Back to the 4 meetings" }));
  expect(await screen.findByRole("dialog", { name: /The 4 meetings at/ })).toBeInTheDocument();
});

test("Q1: in the phone layout a clash is the one card however wide its column, and elsewhere lanes of 85 px or more stand side by side", async () => {
  expect(roomForSideBySide(326, 2)).toBe(true);
  expect(roomForSideBySide(326, 4)).toBe(false);
  expect(roomForSideBySide(326, 2, true)).toBe(false);
  const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 900 });
  try {
    document.documentElement.setAttribute("data-narrow", "");
    const pair = [at("Budget talk", "09:00", "10:00")(TODAY), at("Lunch with Sam", "09:30", "10:30")(TODAY)];
    await open("day", (date) => (date === TODAY ? { timed: pair } : {}), { clashes: [clash(pair[0], pair[1])] });
    const card = await screen.findByRole("group", { name: /^Clash: / });
    expect(card.closest("li[data-clash]")).not.toHaveAttribute("data-side");
  } finally {
    if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
  }
});

test("Q2: a meeting that starts where a clash ends is never in the clash's block", async () => {
  const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1400 });
  try {
    const titles = ["Touch a", "Touch b", "Touch c", "Touch d", "Touch e", "Touch f"];
    const made = titles.map((title, n) => at(title, `10:${String(n * 5).padStart(2, "0")}`, "11:00")(TODAY));
    const wall = at("Touch wall", "11:00", "12:00")(TODAY);
    const pairs = made.flatMap((a, i) => made.slice(i + 1).map((b) => clash(a, b)));
    await open("day", (date) => (date === TODAY ? { timed: [...made, wall] } : {}), { clashes: pairs });
    const block = await waitFor(() => {
      const found = document.querySelector<HTMLElement>(`ul[data-day="${TODAY}"] > li[data-clash]`);
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(block.textContent).not.toContain("Touch wall");
    expect(screen.getByRole("button", { name: /Touch wall/ }).closest("li[data-clash]")).toBeNull();
  } finally {
    if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
  }
});

test("Q2 (SCH): the meetings come first: a card that cannot hold the whole heading and every meeting says its short heading and shows them all", async () => {
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 900 });
  const box = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  // The card is 100 px tall: the whole heading takes 45 px, the short one 20 px; each row is 20 px. One row fits under the whole heading (with the +N more button), all three only under the short one.
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.hasAttribute("data-group-card")) return box(0, 100);
    const card = this.closest("[data-group-card]");
    if (card && this.tagName === "LI" && this.parentElement?.tagName === "UL") {
      const brief = card.querySelector<HTMLElement>("[data-head-brief]");
      return box(0, (brief && !brief.hidden ? 20 : 45) + 20 * (Array.from(this.parentElement.children).indexOf(this) + 1));
    }
    return box(0, 0);
  });
  try {
    const pair = [at("Budget talk", "09:00", "10:00")(TODAY), at("Lunch with Sam", "09:30", "10:30")(TODAY), at("Call Ana", "09:45", "10:45")(TODAY)];
    await open("week", (date) => (date === TODAY ? { timed: pair } : {}), { clashes: [clash(pair[0], pair[1]), clash(pair[1], pair[2])] });
    const card = await screen.findByRole("group", { name: /^Clash: / });
    const head = card.querySelector("p") as HTMLElement;
    await waitFor(() => expect(Array.from(card.querySelector("ul")!.children).map((r) => (r as HTMLElement).hidden)).toEqual([false, false, false]));
    expect(card.querySelector("[data-group-more]")).toBeNull();
    // The short heading is whole ("Clash" and what is wrong); the long phrase is on hover and in the card's name.
    expect(head.querySelector(":scope > span:not([hidden])")?.textContent).toMatch(/^Clash · 3 at once$/);
    // Each meeting is on one line (its title; the time and place are in the row's hover text) before the long heading is given up.
    expect(card).toHaveAttribute("data-compact");
    expect(Array.from(card.querySelectorAll("button[data-entry-key]")).every((b) => b.getAttribute("title")?.includes(" · "))).toBe(true);
    expect(head.getAttribute("title")).toBeTruthy();
  } finally {
    spy.mockRestore();
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 0 });
  }
});

test("Q2 (SCH): a clash card's heading is never cut: the row that does not fit is counted in +N more", async () => {
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 900 });
  const box = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  // The card is 90 px tall; its heading takes 20 px and each row 40 px, so the first row fits and the second does not.
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.hasAttribute("data-group-card")) return box(0, 90);
    const card = this.closest("[data-group-card]");
    if (card && this.tagName === "LI" && this.parentElement?.tagName === "UL") return box(0, 20 + 40 * (Array.from(this.parentElement.children).indexOf(this) + 1));
    return box(0, 0);
  });
  try {
    const pair = [at("Budget talk", "09:00", "10:00")(TODAY), at("Lunch with Sam", "09:30", "10:30")(TODAY)];
    await open("week", (date) => (date === TODAY ? { timed: pair } : {}), { clashes: [clash(pair[0], pair[1])] });
    const card = await screen.findByRole("group", { name: /^Clash: / });
    await waitFor(() => expect(Array.from(card.querySelector("ul")!.children).map((r) => (r as HTMLElement).hidden)).toEqual([false, true]));
    expect(card.querySelector("[data-group-more]")).not.toBeNull();
    // The heading is whole: never shortened to one line with an ellipsis.
    expect(card.querySelector("p")).not.toHaveAttribute("data-compact");
    expect(within(card).getByText(/^Clash · they overlap by \d+ min$/)).toBeInTheDocument();
  } finally {
    spy.mockRestore();
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 0 });
  }
});
