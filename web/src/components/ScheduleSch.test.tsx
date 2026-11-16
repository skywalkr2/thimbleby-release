import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { clash, entry, scheduleRoutes, TODAY, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { Schedule } from "./Schedule";

// The Schedule's own cold-score fixes (batch SCH): a calendar the sign-in banner names has its entries marked in words and by a dashed edge;
// the banner waits for the first read; an empty range with such a calendar does not claim "nothing"; "Show all hours" is a button on the
// line above the grid, beside the key to the sides; the summary is plain words with a small link.

const calendar = (id: string, over: Partial<S["WatchSourceView"]> = {}) =>
  ({ id, label: `Calendar, ${id}`, connector: "k/calendar", connector_label: "Calendar", enabled: true, every_minutes: 15, items: 1, last: null, read_at: "2026-11-10T08:00:00Z", failures: 0, problem: null, reads: ["calendar"], account: `${id}@example.com`, account_state: "signed_in", sides: [], ...over }) as unknown as S["WatchSourceView"];
// One refused by the service (no account_state word, a failed read with an auth error) and one that is fine.
const REFUSED = calendar("cal-refused", { last: { outcome: "failed", error_kind: "auth" } as never });
const FINE = calendar("cal-fine");
const ROUTES: Routes = { "GET watch": () => [REFUSED, FINE], "GET setup/business": () => ({ business: false, name: "", personal: "", sides: [], chosen: "work" }), "GET views": () => [] };
const at = (title: string, from: string, source: string) => (date: string) => entry({ title, begins: `${date}T${from}:00+00:00`, ends: `${date}T${from.slice(0, 2)}:59:00+00:00`, start: `${date}T${from}:00+00:00`, source }, date);
const CONTENT: Content = (date) => (date === TODAY ? { timed: [at("Fitting", "09:00", "cal-refused"), at("Dentist", "11:00", "cal-fine")].map((m) => m(TODAY)) } : {});

async function open(view = "day", content: Content = CONTENT, extra: Routes = {}) {
  window.localStorage.setItem("cockpit:schedule-view", view);
  fakeApi(scheduleRoutes(content, {}, { ...ROUTES, ...extra }));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2 });
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => vi.unstubAllGlobals());

test("an entry of a calendar the sign-in line names says it may be out of date, in words and by a dashed edge, however the sign-in was lost", async () => {
  await open();
  const stale = await screen.findByRole("button", { name: /Fitting/ });
  expect(stale).toHaveAttribute("data-stale");
  expect(within(stale).getByText("May be out of date")).toBeInTheDocument();
  const fine = screen.getByRole("button", { name: /Dentist/ });
  expect(fine).not.toHaveAttribute("data-stale");
  expect(within(fine).queryByText("May be out of date")).toBeNull();
  // The line above the calendar names the same calendar.
  expect(document.querySelector("[data-schedule-stale]")).not.toBeNull();
});

test("the account line holds its place while the days load, so nothing moves when they come, and the loading grid draws no block that could be read as an entry", async () => {
  fakeApi(scheduleRoutes(CONTENT, {}, { ...ROUTES, "GET schedule": () => new Promise(() => undefined) }));
  window.localStorage.setItem("cockpit:schedule-view", "day");
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 1, name: "Schedule" });
  await waitFor(() => expect(document.querySelector("[data-skeleton]")).not.toBeNull());
  await waitFor(() => expect(document.querySelector("[data-schedule-stale-list]")).not.toBeNull());
  expect(document.querySelector("[data-skeleton] [class*='skeletonEvent']")).toBeNull();
});

test("an empty range with a calendar that can't be read shows the one quiet line above the calendar and no card (S-0525)", async () => {
  await open("week", () => ({}));
  await waitFor(() => expect(document.querySelector("[data-schedule-stale]")).not.toBeNull());
  expect(document.querySelector("[data-schedule-empty]")).toBeNull();
  expect(screen.queryByText(/in the calendars that can be read/)).toBeNull();
});

test("the line above the grid holds \"Show all hours\" as a button, on the line the key to the sides shares", async () => {
  const user = userEvent.setup();
  await open("day");
  const line = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[data-hours-switch]");
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  const button = within(line).getByRole("button", { name: "Show all hours" });
  expect(button).toHaveAttribute("aria-pressed", "false");
  await user.click(button);
  expect(within(line).getByRole("button", { name: "Show fewer hours" })).toHaveAttribute("aria-pressed", "true");
});

test("the line under the title is the clash count in plain words with a small link, then the counts; no dot ever leads a part", async () => {
  const pair = [at("Budget talk", "09:00", "cal-fine")(TODAY), at("Lunch with Sam", "09:30", "cal-fine")(TODAY)];
  window.localStorage.setItem("cockpit:schedule-view", "week");
  fakeApi(scheduleRoutes((date) => (date === TODAY ? { timed: pair } : {}), { clashes: [clash(pair[0], pair[1], { minutes: 30 })] }, ROUTES));
  renderApp(<Schedule />);
  await waitFor(() => expect(document.querySelector("[data-clash-count]")).not.toBeNull());
  const summary = document.querySelector("[data-summary]") as HTMLElement;
  expect(summary.querySelector("[data-clash-count]")).toHaveTextContent(/^1 clash this week$/);
  // The count is not the link: the link is the small "Show it" beside it.
  expect(summary.querySelector("[data-clash-count]")?.closest("button")).toBeNull();
  expect(within(summary).getByRole("button", { name: "Show it" })).toBeInTheDocument();
  for (const part of Array.from(summary.querySelectorAll("[data-meetings]"))) expect(part.textContent?.trim().startsWith("·")).toBe(false);
});

test("on a phone an entry of a calendar that needs signing in says it may be out of date in its row too", async () => {
  document.documentElement.setAttribute("data-narrow", "");
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: /max-width/.test(query), addEventListener: () => undefined, removeEventListener: () => undefined }));
  try {
    await open("work_week");
    const row = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-schedule-list] button[data-stale]");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(row).toHaveTextContent("Fitting");
    expect(within(row).getByText("May be out of date")).toBeInTheDocument();
    expect(document.querySelectorAll("[data-schedule-list] button[data-stale]")).toHaveLength(1);
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});

test("on a phone the sign-in line is one line: what is wrong and which calendar, the whole sentence on hover", async () => {
  document.documentElement.setAttribute("data-narrow", "");
  try {
    await open("day");
    const line = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-schedule-stale] p");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(line.textContent).toMatch(/^Out of date: /);
    expect(line.textContent).not.toMatch(/Last updated/);
    expect(line.parentElement?.querySelector("[title]")?.getAttribute("title")).toMatch(/isn't up to date/);
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});
