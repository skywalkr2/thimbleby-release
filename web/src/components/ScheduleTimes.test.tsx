import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clash, entry, scheduleRoutes, TODAY, type Content } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// A calendar that shows the wrong time is broken data: every entry of a day is drawn, at its true start and for its true length, and the
// time printed on it is its own start (design 7.7). Four meetings that clash are four blocks at their own times, never fewer.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
afterEach(() => {
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});
beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});

/** A start and a length, in minutes after midnight, for each of the day's meetings. */
const MEETINGS = [
  { title: "Opening", from: 9 * 60, minutes: 60 },
  { title: "Supplier call", from: 16 * 60 + 10, minutes: 60 },
  { title: "Fitting appointment", from: 16 * 60 + 40, minutes: 60 },
  { title: "Venue walk-through", from: 16 * 60 + 10, minutes: 90 },
  { title: "Budget check", from: 17 * 60, minutes: 30 },
  { title: "Closing", from: 18 * 60 + 30, minutes: 45 },
];
const clock = (date: string, m: number) => `${date}T${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}:00+00:00`;
const made = (date: string) => MEETINGS.map((m) => entry({ title: m.title, begins: clock(date, m.from), ends: clock(date, m.from + m.minutes), start: clock(date, m.from) }, date));
const content: Content = (date) => (date === TODAY ? { timed: made(date) } : {});
// The four meetings from 4:10 PM clash, as the engine says: each pair that overlaps.
const pairs = () => {
  const day = made(TODAY);
  const four = day.slice(1, 5);
  return four.flatMap((a, i) => four.slice(i + 1).map((b) => clash(a, b)));
};

const startOf = (from: number): string => `${((Math.floor(from / 60) + 11) % 12) + 1}:${String(from % 60).padStart(2, "0")} ${from >= 12 * 60 ? "PM" : "AM"}`;

/** Hours (a fraction) from a `calc(N * var(--hour))` value. */
const hours = (value: string): number => Number(/calc\(([-\d.]+) \* var\(--hour\)\)/.exec(value)?.[1] ?? NaN);
const minutesOfLabel = (label: string): number => {
  const m = /^(\d{1,2})(?::(\d\d))? ?(AM|PM)$/.exec(label.trim());
  if (!m) return NaN;
  return ((Number(m[1]) % 12) + (m[3] === "PM" ? 12 : 0)) * 60 + Number(m[2] ?? 0);
};

async function drawn(view: "Day" | "Work week" | "Week", width: number) {
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => width });
  const user = userEvent.setup();
  fakeApi(scheduleRoutes(content, { clashes: pairs() }));
  renderApp(<Schedule />);
  await screen.findByRole("heading", { level: 2, name: /–|2026/ });
  await user.click(await screen.findByRole("tab", { name: view }));
  await waitFor(() => expect(document.querySelector(`[data-day="${TODAY}"] [data-entry-key]`)).not.toBeNull());
  const from = minutesOfLabel(document.querySelector("[data-hour][data-first]")?.textContent ?? "");
  expect(Number.isNaN(from)).toBe(false);
  return from;
}

describe("every entry of a day is drawn at its true time", () => {
  for (const [view, width] of [
    ["Day", 1200],
    ["Work week", 1440],
    ["Week", 1440],
  ] as const) {
    test(`${view} at ${width}px: all ${MEETINGS.length} meetings, each at its start, for its length, naming its own start`, async () => {
      const first = await drawn(view, width);
      const lane = document.querySelector(`ul[data-day="${TODAY}"]`) as HTMLElement;
      for (const m of MEETINGS) {
        const buttons = Array.from(lane.querySelectorAll<HTMLElement>("[data-entry-key]")).filter((b) => b.textContent?.includes(m.title));
        expect(buttons, `${m.title} is drawn`).toHaveLength(1);
        const slot = buttons[0].closest("li[style]") as HTMLElement;
        expect(slot).not.toBeNull();
        const clashing = slot.closest("li[data-clash]") as HTMLElement | null;
        if (clashing && !clashing.hasAttribute("data-side")) {
          // One card for the clash: it starts where its first meeting starts and lists every meeting, each with its own start.
          const names = Array.from(clashing.querySelectorAll("[data-entry-key]")).map((b) => b.textContent);
          expect(names.length).toBe(4);
          // Exactly the clash's span, first start to last end (4:10 PM to 5:40 PM), so it covers nothing after it.
          expect(Math.round(hours(clashing.style.height) * 60)).toBe(90);
          expect(buttons[0].textContent, `${m.title} time`).toContain(startOf(m.from));
          continue;
        }
        // Where the block sits, to a minute: its top is its start after the grid's first hour, its height its length. A member of a
        // clash is placed inside the clash's span, in percent of it.
        let top = hours(slot.style.top);
        let height = hours(slot.style.height);
        if (clashing) {
          const whole = hours(clashing.style.height);
          expect(Number.isNaN(whole), "the clash's span has a height").toBe(false);
          top = hours(clashing.style.top) + (parseFloat(slot.style.top) / 100) * whole;
          height = (parseFloat(slot.style.height) / 100) * whole;
        }
        expect(Math.round(top * 60), `${m.title} top`).toBe(m.from - first);
        expect(Math.round(height * 60), `${m.title} height`).toBe(m.minutes);
        // The time it prints is its own start.
        expect(`${buttons[0].getAttribute("title") ?? ""} ${buttons[0].textContent}`, `${m.title} time`).toContain(startOf(m.from));
      }
    });
  }
});

describe("meetings that overlap without a clash", () => {
  test("where the day's column is too narrow for them side by side they are one card naming each title in full with its own start", async () => {
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1440 });
    const user = userEvent.setup();
    const titles = ["Quarterly planning review", "Supplier negotiation", "Venue walk-through", "Budget check-in"];
    const day: Content = (date) => (date === TODAY ? { timed: titles.map((title, n) => entry({ title, begins: clock(date, 640 + n * 10), ends: clock(date, 700 + n * 10), start: clock(date, 640 + n * 10) }, date)) } : {});
    fakeApi(scheduleRoutes(day));
    renderApp(<Schedule />);
    await screen.findByRole("heading", { level: 2, name: /–|2026/ });
    await user.click(await screen.findByRole("tab", { name: "Week" }));
    const card = await waitFor(() => {
      const found = document.querySelector(`ul[data-day="${TODAY}"] [data-overlap]`);
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    // The card is exactly the meetings' span (first start to last end), so it never covers an entry after it; its rows scroll inside.
    expect(Math.round(hours((card as HTMLElement).style.height) * 60)).toBe(730 - 640);
    for (const [n, title] of titles.entries()) {
      const row = Array.from(card.querySelectorAll("[data-entry-key]")).find((b) => b.textContent?.includes(title));
      expect(row, `${title} in full`).toBeDefined();
      expect(row?.textContent).toContain(startOf(640 + n * 10));
    }
  });
});

describe("a group card that is too short for its rows", () => {
  test("draws only the rows that fit whole and counts the rest in a +N more inside the card that opens the clash in the side pane", async () => {
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 1440 });
    const box = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    // The card is 100 px tall; each row is 40 px, so one row and the button fit.
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.hasAttribute("data-group-card")) return box(0, 100);
      if (this.tagName === "LI" && this.parentElement?.closest("[data-group-card]") && this.parentElement.tagName === "UL") return box(0, 40 * (Array.from(this.parentElement.children).indexOf(this) + 1));
      return box(0, 0);
    });
    const user = userEvent.setup();
    const titles = ["Quarterly planning review", "Supplier negotiation", "Venue walk-through", "Budget check-in"];
    const day: Content = (date) => (date === TODAY ? { timed: titles.map((title, n) => entry({ title, begins: clock(date, 640 + n * 10), ends: clock(date, 700 + n * 10), start: clock(date, 640 + n * 10) }, date)) } : {});
    fakeApi(scheduleRoutes(day));
    renderApp(<Schedule />);
    await screen.findByRole("heading", { level: 2, name: /–|2026/ });
    await user.click(await screen.findByRole("tab", { name: "Week" }));
    const card = await waitFor(() => {
      const found = document.querySelector<HTMLElement>(`ul[data-day="${TODAY}"] [data-group-card]`);
      expect(found?.querySelector("[data-group-more]")).not.toBeNull();
      return found as HTMLElement;
    });
    const rows = Array.from(card.querySelector("ul")!.children) as HTMLElement[];
    // Each row is whole or not drawn: the first is there with its title, the other three are not drawn.
    expect(rows.map((r) => r.hidden)).toEqual([false, true, true, true]);
    expect(rows[0].textContent).toContain(titles[0]);
    const more = card.querySelector("[data-group-more]") as HTMLElement;
    expect(more).toHaveAccessibleName("3 more meetings at " + startOf(640));
    spy.mockRestore();
    await user.click(more);
    const list = await screen.findByRole("dialog", { name: /The 4 meetings at/ });
    for (const title of titles) expect(within(list).getByRole("button", { name: new RegExp(title) })).toBeInTheDocument();
    expect(list.querySelector("[data-group-pane]")).not.toBeNull();
  });
});
