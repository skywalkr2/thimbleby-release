import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { fullDay } from "../lib/dates";
import { entry, scheduleRoutes, TODAY } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// A person with several calendars (design 7.7): each is named by its account, has a color beside its name, and has a button in a
// legend that shows or hides its entries; the same invitation held by two accounts is one entry naming both.

const calendar = (id: string, label: string, shown_color: S["WatchSourceView"]["shown_color"], over: Partial<S["WatchSourceView"]> = {}) =>
  ({ id, label, connector: "k", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: null, failures: 0, problem: null, reads: ["calendar"], shown_color, ...over }) as S["WatchSourceView"];

const CALENDARS = [calendar("cal-a", "Calendar, alex@example.com", "blue"), calendar("cal-b", "Calendar, blake@example.com", "teal"), calendar("cal-c", "Calendar, casey@example.com", "green")];

const content = (date: string) =>
  date === TODAY
    ? {
        timed: [
          entry({ title: "Quarterly review", source: "cal-a", also_in: ["cal-b"], begins: `${date}T10:00:00+00:00` }),
          entry({ title: "Supplier call", source: "cal-b", begins: `${date}T11:00:00+00:00` }),
          entry({ title: "School run", source: "cal-c", begins: `${date}T12:00:00+00:00` }),
          entry({ title: "Dentist", own: true, kind: "own", snapshot: "EVT-7", source: "", begins: `${date}T13:00:00+00:00` }),
        ],
      }
    : {};

async function open() {
  fakeApi(scheduleRoutes(content, {}, { "GET watch": () => CALENDARS }));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2, name: fullDay(TODAY) });
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("cockpit:schedule-view", "day");
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => vi.unstubAllGlobals());

// The calendars are one button that opens their list.
const legend = async () => {
  await userEvent.setup().click(await screen.findByRole("button", { name: /^Calendars \(\d+\)/ }));
  return screen.findByRole("list", { name: "Calendars" });
};

test("the legend lists each calendar by its name with its color, as a button that is pressed while it shows", async () => {
  await open();
  const list = await legend();
  const buttons = within(list).getAllByRole("button");
  // The app's own calendar is listed too while it holds an entry (the page has one, Dentist), after the calendars that are read.
  expect(buttons.map((b) => b.textContent)).toEqual(["Calendar", "Calendar (2)", "Calendar (3)", "The app's own calendar"]);  // never an address, or the start of one: a number tells equal names apart
  expect(buttons.every((b) => b.getAttribute("aria-pressed") === "true")).toBe(true);
  // The color is a mark beside the name, never the only sign: the name is the button's own text. The app's own calendar has none.
  expect(buttons.map((b) => b.querySelector("[data-color]")?.getAttribute("data-color"))).toEqual(["blue", "teal", "green", undefined]);
});

test("hiding the app's own calendar hides its entries, and showing it brings them back", async () => {
  const user = userEvent.setup();
  await open();
  expect(await screen.findByRole("button", { name: /Dentist/ })).toBeInTheDocument();
  const list = await legend();
  await user.click(within(list).getByRole("button", { name: /The app's own calendar/ }));
  expect(screen.queryByRole("button", { name: /Dentist/, hidden: true })).toBeNull();
  expect(within(list).getByRole("button", { name: /The app's own calendar/ })).toHaveAttribute("aria-pressed", "false");
  await user.click(within(list).getByRole("button", { name: /The app's own calendar/ }));
  expect(await screen.findByRole("button", { name: /Dentist/, hidden: true })).toBeInTheDocument();
});

test("each entry carries its calendar's color on its edge and its name in its words", async () => {
  await open();
  const review = await screen.findByRole("button", { name: /Quarterly review/ });
  expect(review).toHaveAttribute("data-color", "blue");
  expect(review).toHaveTextContent("From Calendar, also in Calendar (2)");
  expect(screen.getByRole("button", { name: /School run/ })).toHaveAttribute("data-color", "green");
  // The app's own entries have no calendar color.
  expect(screen.getByRole("button", { name: /Dentist/ })).not.toHaveAttribute("data-color");
});

test("hiding a calendar hides its entries and says Hidden in words; an invitation in two calendars stays while either shows", async () => {
  const user = userEvent.setup();
  await open();
  const list = await legend();
  await user.click(within(list).getByRole("button", { name: "Calendar (3)" }));
  expect(screen.queryByRole("button", { name: /School run/, hidden: true })).toBeNull();
  expect(within(list).getByRole("button", { name: /Calendar \(3\)/ })).toHaveAttribute("aria-pressed", "false");
  expect(within(list).getByText("Hidden")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Supplier call/, hidden: true })).toBeInTheDocument();
  // The invitation is held by both of the first two: hiding one of them keeps it, hiding both takes it away.
  await user.click(within(list).getByRole("button", { name: "Calendar" }));
  expect(screen.getByRole("button", { name: /Quarterly review/, hidden: true })).toBeInTheDocument();
  await user.click(within(list).getByRole("button", { name: "Calendar (2)" }));
  expect(screen.queryByRole("button", { name: /Quarterly review/, hidden: true })).toBeNull();
  expect(screen.getByRole("button", { name: /Dentist/, hidden: true })).toBeInTheDocument();
  // The choice is remembered on this browser.
  expect(JSON.parse(window.localStorage.getItem("cockpit:schedule:hidden-calendars") ?? "[]").sort()).toEqual(["cal-a", "cal-b", "cal-c"]);
});

test("with one calendar there is no legend", async () => {
  fakeApi(scheduleRoutes(content, {}, { "GET watch": () => [CALENDARS[0]] }));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2, name: fullDay(TODAY) });
  expect(screen.queryByRole("list", { name: "Calendars" })).toBeNull();
});
