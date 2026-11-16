import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import type { S } from "../lib/api";
import { setSideChoice } from "../lib/sides";
import { fakeApi, renderApp } from "../test-utils";
import { WeekAhead } from "./WeekAhead";

afterEach(() => cleanup());

const ROW: S["WeekAheadRowView"] = { from_day: "2026-10-21", to_day: null, words: "A parcel of ink arrives", kind: "delivery", link: { kind: "event", id: "EVT-1" } };
const WINDOW: S["WeekAheadRowView"] = { from_day: "2026-10-20", to_day: "2026-10-24", words: "The print offer is open", kind: "window", link: { kind: "snapshot", id: "SNAP-1" } };
const READ: S["WeekAheadView"] = { first: "2026-10-19", last: "2026-10-25", state: "read", sentence: "A light week with a parcel coming.", rows: [ROW, WINDOW], read_again: true };

test("the card has the sentence and one row for each thing, each with its day or window and a link to its source", async () => {
  fakeApi({ "GET week-ahead": () => READ });
  renderApp(<WeekAhead />);
  expect(await screen.findByRole("heading", { level: 2, name: "The week ahead" })).toBeInTheDocument();
  expect(screen.getByText("A light week with a parcel coming.")).toBeInTheDocument();
  const rows = document.querySelectorAll("[data-week-ahead-row]");
  expect(rows).toHaveLength(2);
  expect(screen.getByRole("link", { name: "Open A parcel of ink arrives" }).getAttribute("href")).toContain("records/event/EVT-1");
  expect(screen.getByRole("link", { name: "Open The print offer is open" }).getAttribute("href")).toContain("SNAP-1");
  expect(rows[1].textContent).toMatch(/ to /); // a window shows both of its days
});

test("with no reading the rows show without a sentence", async () => {
  fakeApi({ "GET week-ahead": () => ({ ...READ, state: "rules", sentence: null, rows: [ROW] }) });
  renderApp(<WeekAhead />);
  expect(await screen.findByText("A parcel of ink arrives")).toBeInTheDocument();
  expect(document.querySelector("[data-week-ahead-sentence]")).toBeNull();
});

test("an empty week says so, and a reading under way or waiting for the go says that and cannot be asked for again", async () => {
  fakeApi({ "GET week-ahead": () => ({ ...READ, state: "empty", sentence: null, rows: [] }) });
  renderApp(<WeekAhead />);
  expect(await screen.findByText("Nothing dated this week.")).toBeInTheDocument();
  cleanup();
  fakeApi({ "GET week-ahead": () => ({ ...READ, state: "needs_go", estimate_usd: 0.05, read_again: false }) });
  renderApp(<WeekAhead />);
  expect(await screen.findByText(/Waiting for your go to read the week/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read the week again" })).toBeDisabled();
});

test("Not this week leaves the row out with Undo, and Read the week again asks once", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET week-ahead": () => READ,
    "POST week-ahead/set-aside": () => ({ previous: [] }),
    "POST week-ahead/read": () => ({ request: "REQ-1" }),
  });
  renderApp(<WeekAhead />);
  await screen.findByText("A parcel of ink arrives");
  await user.click(screen.getAllByRole("button", { name: "Not this week" })[0]);
  await waitFor(() => expect(calls.some((c) => c.route === "POST week-ahead/set-aside")).toBe(true));
  expect(calls.find((c) => c.route === "POST week-ahead/set-aside")?.body).toEqual({ source: "EVT-1" });
  await user.click(screen.getByRole("button", { name: "Read the week again" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST week-ahead/read")).toBe(true));
});

test("under a side's filter the card shows only that side's rows and those on no side, saying Every side on the latter, and no sentence", async () => {
  const sides: S["SideView"][] = [
    { project: "PRJ-first", kind: "business", name: "Orchard Press", removable: false, filed: 0 },
    { project: "PRJ-second", kind: "job", name: "Lantern Works", removable: false, filed: 0 },
  ];
  const mine = { ...ROW, side: "PRJ-first", words: "Proofs arrive", link: { kind: "event", id: "EVT-A" } };
  const other = { ...ROW, side: "PRJ-second", words: "Venue deposit due", link: { kind: "event", id: "EVT-B" } };
  const loose = { ...ROW, side: null, words: "Renew the passport", link: { kind: "event", id: "EVT-C" } };
  fakeApi({
    "GET week-ahead": () => ({ ...READ, rows: [mine, other, loose] }),
    "GET setup/business": () => ({ business: true, name: "Orchard Press", personal: "PRJ-personal", sides, chosen: "work" }),
  });
  setSideChoice("PRJ-first");
  renderApp(<WeekAhead />);
  await screen.findByText("Proofs arrive");
  await waitFor(() => expect(document.querySelectorAll("[data-week-ahead-row]")).toHaveLength(2));
  expect(screen.queryByText("Venue deposit due")).toBeNull();
  expect(screen.queryByText("A light week with a parcel coming.")).toBeNull();
  expect(document.querySelector("[data-week-ahead-row=EVT-C] [data-every-side]")).not.toBeNull();
  expect(document.querySelector("[data-week-ahead-row=EVT-A] [data-every-side]")).toBeNull();
  setSideChoice("all");
  cleanup();
  renderApp(<WeekAhead />);
  expect(await screen.findByText("A light week with a parcel coming.")).toBeInTheDocument();
  expect(document.querySelectorAll("[data-week-ahead-row]")).toHaveLength(3);
  expect(document.querySelector("[data-every-side]")).toBeNull();
});

test("a row's words read as Today shows them: a day written as year-month-day is a day, never the raw date", async () => {
  const dated: S["WeekAheadRowView"] = { ...ROW, kind: "task", words: "Lend us the trailer on 2026-10-22", from_day: "2026-10-22" };
  fakeApi({ "GET week-ahead": () => ({ ...READ, rows: [dated] }) });
  renderApp(<WeekAhead />);
  await screen.findByRole("link", { name: /Open Lend us the trailer/ });
  const row = document.querySelector("[data-week-ahead-row]")!;
  expect(row.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  expect(row.querySelector("a")?.getAttribute("aria-label") ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}/);
});

test("on Today the card leaves out a row whose record Today's agenda lists, says so when none is left, and the Schedule's card stays whole", async () => {
  const entry = { snapshot: "SNAP-1", source: "", title: "The print offer is open", start: "2026-10-20", all_day: true, cancelled: false, days: ["2026-10-20"] };
  fakeApi({ "GET week-ahead": () => READ, "GET today/agenda": () => [entry] });
  renderApp(<WeekAhead leaveOutAgenda />);
  expect(await screen.findByText("A parcel of ink arrives")).toBeInTheDocument();
  expect(screen.queryByText("The print offer is open")).toBeNull();
  expect(document.querySelector("[data-week-ahead-sentence]")).toBeNull();
  cleanup();
  fakeApi({ "GET week-ahead": () => ({ ...READ, rows: [WINDOW] }), "GET today/agenda": () => [entry] });
  renderApp(<WeekAhead leaveOutAgenda />);
  expect(await screen.findByText("Nothing dated this week.")).toBeInTheDocument();
  cleanup();
  fakeApi({ "GET week-ahead": () => READ, "GET today/agenda": () => [entry] });
  renderApp(<WeekAhead />);
  expect(await screen.findByText("The print offer is open")).toBeInTheDocument();
});
