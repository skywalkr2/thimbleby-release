import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { chipsThatFit } from "../lib/calendar";
import { entry, scheduleRoutes, TODAY, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { Schedule } from "./Schedule";

// The key to the sides' colors on the Schedule (design 7.13, the reviewer's answer 4): "● Name" for each side drawn in the range, the name
// cut at 16 with the whole of it on hover and as its accessible name, "+N more" for what does not fit one line (it opens the side menu with
// every side and its color), no two sides drawn together sharing a color, and every entry's accessible name saying its side.

const PERSONAL = "PRJ-personal";
const side = (n: number, name: string): S["SideView"] => ({ project: `PRJ-${n}`, kind: "business", name, removable: false, filed: 0 });
const SIDES = [
  side(1, "Harborview Community Support Partnership Incorporated"),
  side(2, "Willowbrook Handmade Ceramics and Garden Supply Cooperative"),
  side(3, "Northfield Mobile Bicycle Repair and Neighborhood Delivery Service"),
  side(4, "Lantern Row Studio"),
];
const source = (id: string, sides: string[]) =>
  ({ id, label: id, connector: "k/calendar", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], account: `${id}@example.com`, sides }) as unknown as S["WatchSourceView"];
const SOURCES = [source("cal-0", [PERSONAL]), ...SIDES.map((s, n) => source(`cal-${n + 1}`, [s.project]))];
const ROUTES: Routes = {
  "GET setup/business": () => ({ business: true, name: SIDES[0].name, personal: PERSONAL, sides: SIDES, chosen: "work" }),
  "GET views": () => [],
  "GET watch": () => SOURCES,
};
const make = (title: string, hour: number, source: string, sideId: string) => (date: string) =>
  entry({ title, begins: `${date}T${String(hour).padStart(2, "0")}:00:00+00:00`, ends: `${date}T${String(hour + 1).padStart(2, "0")}:00:00+00:00`, start: `${date}T${String(hour).padStart(2, "0")}:00:00+00:00`, source, side: sideId }, date);
const FIVE: Content = (date) => (date === TODAY ? { timed: [make("Bank visit", 8, "cal-0", PERSONAL), ...SIDES.map((s, n) => make(`Visit ${n + 1}`, 10 + n * 2, `cal-${n + 1}`, s.project))].map((m) => m(TODAY)) } : {});

async function open() {
  window.localStorage.setItem("cockpit:schedule-view", "day");
  fakeApi(scheduleRoutes(FIVE, {}, ROUTES));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2 });
  await waitFor(() => expect(document.querySelector("[data-side-key]")).not.toBeNull());
  return document.querySelector("[data-side-key]") as HTMLElement;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("how many chips fit one line, with the button for the rest taking its room", () => {
  expect(chipsThatFit([100, 100, 100], 10, 400, 60)).toBe(3);
  expect(chipsThatFit([100, 100, 100], 10, 300, 60)).toBe(2);
  expect(chipsThatFit([100, 100, 100], 10, 200, 60)).toBe(1);
  expect(chipsThatFit([100, 100, 100], 10, 50, 60)).toBe(0);
  expect(chipsThatFit([], 10, 0, 60)).toBe(0);
});

test("ans-4: every side drawn is in the key, a name cut at 16 with the whole name on hover and in its accessible name", async () => {
  const key = await open();
  const chips = Array.from(key.querySelectorAll<HTMLElement>("li[data-key-side]"));
  expect(chips).toHaveLength(5);
  const long = chips.find((c) => c.title === SIDES[0].name) as HTMLElement;
  expect(long).toBeDefined();
  expect(long.querySelector("[aria-hidden='true']:not([data-mark])")?.textContent).toHaveLength(16);
  expect(within(long).getByText(SIDES[0].name)).toHaveClass("sr");
  // No two sides drawn together share a color, and the key is the color of the entries' edges.
  const dots = chips.map((c) => c.querySelector("[data-mark='side']")?.getAttribute("data-color"));
  expect(new Set(dots).size).toBe(5);
  for (const [n, s] of SIDES.entries()) expect(screen.getByRole("button", { name: new RegExp(`Visit ${n + 1}.*on ${s.name.slice(0, 12)}`) })).toBeInTheDocument();
});

test("ans-4: the chips that do not fit one line are \"+N more\", which opens the side menu with every side and its color", async () => {
  const user = userEvent.setup();
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 420 });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const width = this.hasAttribute("data-key-side") ? 150 : this.hasAttribute("data-key-more") ? 80 : 0;
    return { top: 0, left: 0, right: width, bottom: 0, width, height: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  });
  try {
    const key = await open();
    await waitFor(() => expect(Array.from(key.querySelectorAll<HTMLElement>("li[data-key-side]")).filter((c) => !c.hidden)).toHaveLength(2));
    const more = within(key).getByRole("button", { name: "3 more sides: open the list of sides" });
    expect(more).toHaveTextContent("+3 more");
    await user.click(more);
    const options = await screen.findAllByRole("button", { name: /./, hidden: false }).then((all) => all.filter((b) => b.hasAttribute("data-side-option")));
    // All, Personal, and the four sides: each side with its dot.
    expect(options).toHaveLength(6);
    expect(options.filter((o) => o.querySelector("[data-mark='side']"))).toHaveLength(5);
  } finally {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 0 });
  }
});
