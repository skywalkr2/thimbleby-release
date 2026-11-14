import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { TodayNext } from "./TodayNext";

// On a phone the schedule is folded far down Today, so the day's next event is one line under the heading.

const TODAY = "2026-10-11";
const at = (hour: number, minute = 0) => {
  const offset = -new Date(2026, 9, 11, hour, minute).getTimezoneOffset();
  const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");
  return `${TODAY}T${pad(hour)}:${pad(minute)}:00${offset < 0 ? "-" : "+"}${pad(Math.trunc(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
};
const event = (title: string, start: string, over: Partial<S["AgendaItemView"]> = {}): S["AgendaItemView"] => ({ snapshot: `snap-${title}`, source: "cal-1", title, start, all_day: false, cancelled: false, own: false, open_items: 0, days: [TODAY], ...over });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 11, 12, 0));
});
afterEach(() => vi.useRealTimers());

test("the next event of the day that has not started is named with its time, never one that is over or cancelled", async () => {
  fakeApi({
    "GET today/agenda": () => [event("Standup", at(9)), event("Called off", at(13), { cancelled: true }), event("Design review", at(15)), event("Supplier call 2", at(16))],
    "GET projects": () => [],
    "GET setup/business": () => ({ business: false, name: "", personal: "PRJ-p", sides: [], chosen: null }),
  });
  renderApp(<TodayNext />);
  expect(await screen.findByRole("link", { name: /^Next: .*3:00 PM.* Design review$/ })).toBeInTheDocument();
  expect(screen.queryByText(/Standup|Called off/)).toBeNull();
});

test("a day with nothing left to come says nothing", async () => {
  const calls = fakeApi({ "GET today/agenda": () => [event("Standup", at(9))], "GET projects": () => [], "GET setup/business": () => ({ business: false, name: "", personal: "PRJ-p", sides: [], chosen: null }) });
  const { container } = renderApp(<TodayNext />);
  await waitFor(() => expect(calls.some((c) => c.route === "GET today/agenda")).toBe(true));
  expect(container.querySelector("[data-next-event]")).toBeNull();
});
