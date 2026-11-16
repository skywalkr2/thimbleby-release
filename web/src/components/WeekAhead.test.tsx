import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import type { S } from "../lib/api";
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
