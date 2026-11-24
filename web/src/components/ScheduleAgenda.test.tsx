import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { addDays } from "../lib/dates";
import { allDay, due, entry, scheduleRoutes, TODAY } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// A week with no meeting is a list by day (S-0743): what is due, what is off, the projects' target days, the to-dos past due stacked at
// today, and "No meetings" once. A week with a meeting keeps the grid, with a day off hatched and named.

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("cockpit:schedule-view", "work_week");
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => cleanup());

const THURSDAY = addDays(TODAY, 3);
const OVER = { ...due("Pay the deposit", addDays(TODAY, -40)), start: addDays(TODAY, -40), days: [addDays(TODAY, -40)] };
const NOT_MEETINGS = (date: string) => (date === addDays(TODAY, 1) ? { all_day: [due("Send the figures", date)] } : {});
const EXTRA = {
  off_days: [{ day: THURSDAY, kind: "holiday" as const, reason: "Thanksgiving" }],
  overdue: [OVER],
  targets: [{ day: addDays(TODAY, 2), project: "PRJ-1", name: "Spring catalog", side: null, views: [] }],
};

async function open(content = NOT_MEETINGS, over: object = EXTRA) {
  fakeApi(scheduleRoutes(content, over));
  renderApp(<Schedule />);
  return screen.findByRole("list", { name: "The week by day" });
}

test("a work week with no meeting is a list by day with Mon 23 headings, the due to-dos, the target, the day off and No meetings once", async () => {
  const list = await open();
  expect(document.querySelector("[data-grid]")).toBeNull();
  expect(screen.getAllByText("No meetings")).toHaveLength(1);
  const days = Array.from(list.querySelectorAll(":scope > li"));
  expect(days).toHaveLength(5);
  // The page's weekday-then-number form, never "26 Mon".
  expect(within(days[0] as HTMLElement).getByRole("heading")).toHaveTextContent(/^Today · Mon 26$/);
  expect(within(days[1] as HTMLElement).getByRole("heading")).toHaveTextContent(/^Tue 27$/);
  expect(within(days[1] as HTMLElement).getByText(/Send the figures/)).toBeInTheDocument();
  expect(within(days[2] as HTMLElement).getByRole("link", { name: "Target day: Spring catalog" })).toHaveAttribute("href", expect.stringContaining("PRJ-1"));
  // The day off is hatched and labelled in words.
  expect(days[3]).toHaveAttribute("data-off");
  expect(within(days[3] as HTMLElement).getByText("Day off · Thanksgiving")).toBeInTheDocument();
  expect(within(days[4] as HTMLElement).getByText("Nothing planned")).toBeInTheDocument();
});

test("the to-dos past due that no day shown holds are stacked under today's row, and one opens with the day it was due", async () => {
  const user = userEvent.setup();
  const list = await open();
  const today = list.querySelector(":scope > li") as HTMLElement;
  expect(within(today).getByText("Overdue, yours")).toBeInTheDocument();
  await user.click(today.querySelector("[data-entry-key]") as HTMLElement);
  await screen.findByRole("heading", { name: /Pay the deposit/ });
  // Due 40 days before the Monday of the week: Sep 16, in the page's date words.
  expect(await screen.findByText(/Sep 16/)).toBeInTheDocument();
});

test("with a meeting in the week the grid stays, and the day off is hatched and named in its all-day band, never over the day", async () => {
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: [entry({ title: "Standup" })] } : {}), EXTRA));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-grid]")).not.toBeNull());
  expect(document.querySelector("[data-agenda]")).toBeNull();
  const lane = document.querySelector(`ul[data-day="${THURSDAY}"]`) as HTMLElement;
  expect(lane).toHaveAttribute("data-off");
  // Named in the day's all-day band, above the hours: a label inside the day would cover a meeting at the top of it, and one in the
  // heading would take the heading to two lines.
  expect(within(lane).queryByText("Day off · Thanksgiving")).toBeNull();
  const bands = Array.from(document.querySelectorAll("[data-grid] [data-strip]"));
  expect(bands.filter((b) => b.textContent?.includes("Day off · Thanksgiving"))).toHaveLength(1);
  expect(Array.from(document.querySelectorAll("[data-grid] h3")).some((h) => h.textContent?.includes("Day off"))).toBe(false);
  expect(document.querySelector(`ul[data-day="${TODAY}"]`)).not.toHaveAttribute("data-off");
  // The overdue to-do is in today's all-day band, so it is on the calendar and in its count.
  expect(await screen.findByText(/Pay the deposit/)).toBeInTheDocument();
  expect(screen.getByText(/^1 meeting · 1 due$/)).toBeInTheDocument();
});

test("headings are the weekday then the number in the grid too", async () => {
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: [entry({ title: "Standup" })], all_day: [allDay("Offsite")] } : {})));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-grid]")).not.toBeNull());
  const heads = Array.from(document.querySelectorAll("[data-grid] h3")).map((h) => h.textContent);
  expect(heads[0]).toBe("Today · Mon 26");
  expect(heads[1]).toBe("Tue 27");
});
