import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import type { S } from "../lib/api";
import { allDay, clash, entry, scheduleRoutes, TODAY, WEEK, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { Schedule } from "./Schedule";

// The Schedule's Day, Week and Month views, fourth round (design 7.7): one all-day entry held by two calendars is drawn once, a clash's time
// never breaks inside itself, a calendar that needs signing in again is named as the page names it, and a page that did not load holds Add.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
const width = (w: number) => Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => w });
beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => {
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});

async function open(view: string, content: Content = WEEK, over = {}, extra: Routes = {}) {
  window.localStorage.setItem("cockpit:schedule-view", view);
  fakeApi(scheduleRoutes(content, over, extra));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2, name: /2026/ });
  await waitFor(() => expect(document.querySelector(`[data-day="${TODAY}"]`)).not.toBeNull());
}

test("the same all-day entry held by two calendars is one chip, counted", async () => {
  width(1200);
  await open("day", (date) => (date === TODAY ? { all_day: [allDay("Public holiday", date, { source: "cal-work" }), allDay("Public holiday", date, { source: "cal-home" })] } : {}));
  const strip = document.querySelector("[data-strip]") as HTMLElement;
  expect(within(strip).getAllByRole("button", { name: /Public holiday/ })).toHaveLength(1);
  expect(strip).toHaveTextContent("×2");
});

test("a clash of three in a narrow column is headed Clash with its reason, and its tooltip keeps the time whole", async () => {
  width(900);
  const at = (title: string, from: string, to: string) => (date: string) => entry({ title, begins: `${date}T${from}:00+00:00`, ends: `${date}T${to}:00+00:00` });
  const three = [at("Supplier call", "09:00", "10:00"), at("Venue walk", "09:15", "10:15"), at("Budget check", "09:30", "10:30")].map((make) => make(TODAY));
  await open("week", (date) => (date === TODAY ? { timed: three } : {}), { clashes: [clash(three[0], three[1]), clash(three[1], three[2])] });
  const card = await screen.findByRole("group", { name: /^Clash: / });
  const head = card.querySelector("p") as HTMLElement;
  expect(head.querySelector(":scope > span:not([hidden])")?.textContent, "the reason is on the card in words").toBe("Clash · 3 at once, they overlap by 15\u00a0min");
  // The short sentence is held for a card with no room for a meeting under the whole one; it is its own whole sentence.
  expect(head.querySelector("[data-head-brief]")?.textContent).toBe("Clash · 3 at once");
  expect(head.getAttribute("title")).toMatch(/^3 at once · 9:00\u00a0AM$/);
});

test("a calendar that needs signing in again is named as the page names it: by its side's mark and name, with no address anywhere", async () => {
  const side: S["SideView"] = { project: "PRJ-first", kind: "business", name: "Orchard Press", removable: false, filed: 0 };
  const source = { id: "cal-a", label: "Calendar, robin@example.com", connector: "k/calendar", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], account: "robin@example.com", account_state: "expired", sides: [side.project] } as unknown as S["WatchSourceView"];
  await open("day", WEEK, {}, {
    "GET setup/business": () => ({ business: true, name: side.name, personal: "PRJ-personal", sides: [side], chosen: "work" }),
    "GET watch": () => [source, { ...source, id: "cal-b", account_state: "ok", account: "other@example.com", label: "Calendar, other@example.com", sides: [] }],
    "GET sign-ins": () => [{ name: "k/account", label: "Example", status: "expired", ready: true, several: true, accounts: [], callback: "x", allows: [] }],
  });
  const line = await screen.findByRole("list", { name: "Calendars that need you to sign in" });
  expect(line).toHaveTextContent("Orchard Press");
  expect(line.textContent ?? "").not.toContain("robin@example.com");
  expect(line.querySelector("[data-side-mark]")).toHaveTextContent("Orchard Press");
  expect(line.innerHTML).not.toContain("robin");
  expect(line).not.toHaveTextContent("Calendar, robin");
});

test("a schedule that did not load keeps the date in its heading and holds Add, with the reason beside it", async () => {
  const routes = scheduleRoutes();
  delete routes["GET schedule"];
  fakeApi(routes);
  window.localStorage.setItem("cockpit:schedule-view", "day");
  renderApp(<Schedule />);
  await screen.findByText(/Your schedule couldn't be loaded/);
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/2026/);
  const add = screen.getByRole("button", { name: "Add to schedule" });
  expect(add).toBeDisabled();
  expect(screen.getByText("Adding comes back when the schedule loads.")).toBeInTheDocument();
});

test("a month day with a clash has a labeled mark", async () => {
  width(1400);
  const planning = entry({ title: "Planning", begins: `${TODAY}T09:15:00+00:00`, ends: `${TODAY}T10:00:00+00:00` });
  await open("month", (date) => (date === TODAY ? { timed: [planning, ...(WEEK(date).timed ?? [])] } : {}), { clashes: [clash((WEEK(TODAY).timed ?? [])[0], planning)] });
  const mark = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[data-clash-mark]");
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  expect(mark).toHaveAttribute("title", "Clash on this day");
  // The mark says it in words as well as by its icon: "1 clash" to the eye, and "Clash: 1 clash on this day" to a screen reader.
  expect(mark).toHaveTextContent("1 clash");
  expect(mark).toHaveTextContent("Clash: 1 clash on this day");
});

test("an all-day band with more entries than fit shows whole rows and a +N more that opens the list of them in the side pane", async () => {
  width(1200);
  // jsdom has no layout: the band is 100px tall and each row 30px, so only whole rows within it (less the room for "+N more") stay.
  const rect = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const el = this as HTMLElement;
    if (el.hasAttribute("data-strip")) return { top: 0, bottom: 100, left: 0, right: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) };
    const row = el.closest("[data-strip-row]") ? Array.from(el.closest("[data-strip]")!.querySelectorAll(":scope > [data-strip-row]")).indexOf(el.closest("[data-strip-row]")!) : -1;
    const bottom = row >= 0 ? (row + 1) * 30 : 0;
    return { top: bottom - 30, bottom, left: 0, right: 100, width: 100, height: 30, x: 0, y: bottom - 30, toJSON: () => ({}) };
  });
  const clientHeight = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute("data-strip") ? 100 : 0;
  });
  try {
    const names = ["Bank holiday", "School trip", "Passport due", "Visa due", "Rent due", "Tax due", "Insurance due"];
    await open("day", (date) => (date === TODAY ? { all_day: names.map((n) => allDay(n, date)) } : {}));
    const strip = document.querySelector("[data-strip]") as HTMLElement;
    await waitFor(() => expect(within(strip).getByRole("button", { name: /\+5 more|5 more all-day/ })).toBeInTheDocument());
    const rows = Array.from(strip.querySelectorAll<HTMLElement>("[data-strip-row]"));
    expect(rows.filter((r) => !r.hidden)).toHaveLength(2);
    expect(rows.filter((r) => r.hidden)).toHaveLength(5);
    within(strip).getByRole("button", { name: /5 more all-day/ }).click();
    const list = await screen.findByRole("list", { name: "All-day entries of this day" });
    expect(within(list).getAllByRole("button")).toHaveLength(7);
  } finally {
    rect.mockRestore();
    clientHeight.mockRestore();
  }
});
