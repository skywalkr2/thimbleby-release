import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { FullReadChoice } from "./FullReadChoice";

function source(over: Partial<S["WatchSourceView"]> = {}): S["WatchSourceView"] {
  return {
    id: "m",
    label: "Inbox",
    connector: "kind-a",
    connector_label: "A kind",
    enabled: true,
    every_minutes: 10,
    items: 9,
    last: null,
    failures: 0,
    problem: null,
    account: "person@example.com",
    looked_back_to: "2026-10-05",
    full_read_open: true,
    ...over,
  };
}

const offered: S["FullReadView"] = {
  answered: null,
  options: [
    { days: 14, count: 0, estimate_usd: null, unpriced: 0, reaches: true },
    { days: 30, count: 12, estimate_usd: 0.4, unpriced: 0, reaches: true },
    { days: 90, count: 40, estimate_usd: 1.2, unpriced: 0, reaches: true },
  ],
};
const done = (taken: number): S["LookBackView"] => ({ days: 30, from_date: "2026-09-19", count: taken, unpriced: 0, reaches: true, taken, started: false });

const pickerOf = () => screen.findByRole("combobox", { name: "Read in full from: person@example.com" });

test("a first sign-in is one line: a list of four choices with an estimate each, none chosen, and Read it off", async () => {
  const user = userEvent.setup();
  fakeApi({ "GET watch/m/full-read": () => offered });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  const pick = await pickerOf();
  expect(pick).toHaveTextContent("Choose…");
  expect(screen.getByText("Read in full from:")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read it" })).toBeDisabled();
  await user.click(pick);
  const options = await screen.findAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual([
    "Choose…",
    expect.stringContaining("2 weeks: No more mail to read."),
    expect.stringContaining("1 month: 12 more messages."),
    expect.stringContaining("3 months: 40 more messages."),
    "Not now",
  ]);
});

test("choosing a reach sends it and says the work waits for the go", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "GET watch/m/full-read": () => offered, "POST watch/m/full-read": () => done(12), "GET watch": () => [] });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: /1 month/ }));
  await user.click(screen.getByRole("button", { name: "Read it" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST watch/m/full-read")?.body).toEqual({ days: 30 }));
  expect(await screen.findByText("Taking in Inbox waits for you to start it.")).toBeInTheDocument();
});

test("Not now sends 0 and reads nothing", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "GET watch/m/full-read": () => offered, "POST watch/m/full-read": () => done(0), "GET watch": () => [] });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: "Not now" }));
  await user.click(screen.getByRole("button", { name: "Skip for now" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST watch/m/full-read")?.body).toEqual({ days: 0 }));
});

test("an account whose question is answered shows nothing", () => {
  fakeApi({});
  renderApp(<FullReadChoice sources={[source({ full_read_open: false })]} account="person@example.com" />);
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByText("Read in full from:")).toBeNull();
});
