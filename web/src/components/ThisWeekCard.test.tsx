import "@testing-library/jest-dom/vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { TodayRail } from "./TodayRail";

afterEach(() => cleanup());

const WEEK: S["WeekAheadView"] = {
  first: "2026-11-23",
  last: "2026-11-27",
  state: "empty",
  sentence: null,
  rows: [],
  read_again: true,
  days_off: [
    { day: "2026-11-26", reason: "Thanksgiving" },
    { day: "2026-11-27", reason: "Day After Thanksgiving" },
  ],
  working_days: 2,
};
const GOALS: NonNullable<S["BriefView"]["goals"]> = { first: "2026-11-23", last: "2026-11-27", confirmed: false, goals: [], proposed: ["Ship the proof"], proposed_sides: [null], fewest: 1, most: 3, offer: "offered", can_offer: false };
// A Tuesday: the morning form is due and the week's briefing is only an offer.
const TUESDAY: S["BriefView"] = { form: "morning", day: "2026-11-24", forms: ["morning", "monday"], sections: [], quiet: true, afternoon_from_hour: 12, on_today: 0 };

const routes = (brief: S["BriefView"], week = WEEK) => ({
  "GET brief": (_body: unknown, query: URLSearchParams) => (query.get("form") === "monday" ? { ...brief, form: "monday" as const, goals: GOALS } : brief),
  "GET week-ahead": () => week,
  "GET today/agenda": () => [],
  "GET today/agenda-span": () => ({ first: "2026-11-23", last: "2026-11-29" }),
  "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
  "GET today/week": () => ({ first: "2026-11-23", last: "2026-11-27", due: [], waiting: [], meetings: [] }),
  "GET watch": () => [],
  "GET setup": () => ({ finished: true, steps: [], settled: 0, total: 0 }),
});

test("This week (days off, working days left, goals to confirm) is in the rail on a Tuesday without pressing anything", async () => {
  fakeApi(routes(TUESDAY) as never);
  renderApp(<TodayRail onView={() => undefined} workspace="ws" />);
  const card = await screen.findByRole("region", { name: /This week/ });
  expect(within(card).getByText(/Days off: .*Thanksgiving.*Plan for 2 working days/)).toBeInTheDocument();
  expect(within(card).getByText("Goals for the week")).toBeInTheDocument();
  expect(within(card).getByText("Ship the proof")).toBeInTheDocument();
  expect(within(card).getByRole("button", { name: "Confirm these goals" })).toBeInTheDocument();
});

test("a week with no day off and no goals draws no This week card", async () => {
  // The monday form carries goals in this fixture, so the goals are taken out for the case.
  fakeApi({ ...routes(TUESDAY, { ...WEEK, days_off: [], working_days: 5 }), "GET brief": () => TUESDAY } as never);
  renderApp(<TodayRail onView={() => undefined} workspace="ws" />);
  await screen.findByRole("region", { name: /Schedule/ });
  expect(screen.queryByRole("region", { name: /This week/ })).toBeNull();
});

test("while a line's detail is open in the rail the cards are out of sight and the rail says they come back when it closes", async () => {
  fakeApi(routes(TUESDAY) as never);
  const slot = { current: null as HTMLDivElement | null };
  renderApp(<TodayRail onView={() => undefined} workspace="ws" detailRef={slot} detailOpen />);
  expect(await screen.findByText("This week, your schedule and setup come back when you close this.")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: /This week/ })).toBeNull();
  cleanup();
  renderApp(<TodayRail onView={() => undefined} workspace="ws" detailRef={slot} detailOpen={false} />);
  expect(await screen.findByRole("region", { name: /This week/ })).toBeInTheDocument();
  expect(screen.queryByText(/come back when you close this/)).toBeNull();
});

test("a week with days off has one line under Today's date where the rail is below the queue (the browser test checks it goes from 1100px)", async () => {
  fakeApi(routes(TUESDAY) as never);
  const { Today } = await import("./Today");
  renderApp(<Today workspace="ws" onView={() => undefined} onAddSource={() => undefined} onOpenGuide={() => undefined} onOpenRecord={() => undefined} />);
  expect(await screen.findByText("This week: 2 working days (Thu, Fri off)")).toBeInTheDocument();
});
