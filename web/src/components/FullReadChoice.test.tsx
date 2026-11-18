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
    { days: 14, count: 0, estimate_usd: null, unpriced: 0, reaches: true, capped: false, estimate: false },
    { days: 30, count: 12, estimate_usd: 0.4, unpriced: 0, reaches: true, capped: false, estimate: false },
    { days: 90, count: 40, estimate_usd: 1.2, unpriced: 0, reaches: true, capped: false, estimate: false },
  ],
};
const done = (taken: number): S["LookBackView"] => ({ days: 30, from_date: "2026-09-19", count: taken, unpriced: 0, reaches: true, capped: false, estimate: false, expected: 0, expected_estimate: false, gave: 0, short: false, taken, started: false });

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

test("a reach whose count stopped at the cap says at least, with its cost, and a reach under it says the exact count", async () => {
  const user = userEvent.setup();
  const capped: S["FullReadView"] = {
    answered: null,
    options: [
      { days: 30, count: 40, estimate_usd: 0.12, unpriced: 0, reaches: true, capped: false, estimate: false },
      { days: 90, count: 100, estimate_usd: 0.31, unpriced: 0, reaches: false, capped: true, estimate: false },
    ],
  };
  fakeApi({ "GET watch/m/full-read": () => capped });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  const options = (await screen.findAllByRole("option")).map((o) => o.textContent ?? "");
  expect(options[1]).toMatch(/^1 month: 40 more messages\./);
  expect(options[2]).toMatch(/^3 months: At least 100 more messages\. At least .*0\.31/);
});

test("after Read it, the result line says what was skipped and nothing about skipping when none was", async () => {
  const user = userEvent.setup();
  const skipped = { ...done(412), started: true, skipped: { too_large: 3 } };
  fakeApi({ "GET watch/m/full-read": () => offered, "POST watch/m/full-read": () => skipped, "GET watch": () => [] });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: /1 month/ }));
  await user.click(screen.getByRole("button", { name: "Read it" }));
  expect(await screen.findByText("Taking in 412 older items from Inbox. Skipped 3 messages that were too large.")).toBeInTheDocument();
});

test("a read that skipped nothing says nothing about skipping", async () => {
  const user = userEvent.setup();
  fakeApi({ "GET watch/m/full-read": () => offered, "POST watch/m/full-read": () => ({ ...done(12), started: true, skipped: {} }), "GET watch": () => [] });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: /1 month/ }));
  await user.click(screen.getByRole("button", { name: "Read it" }));
  const line = await screen.findByText("Taking in 12 older items from Inbox.");
  expect(line.textContent).not.toMatch(/skipped/i);
});

test("a count the service only estimated says about, in the list of reaches", async () => {
  const user = userEvent.setup();
  const guessed: S["FullReadView"] = { answered: null, options: [{ days: 30, count: 201, estimate_usd: 0.62, unpriced: 0, reaches: true, capped: false, estimate: true }] };
  fakeApi({ "GET watch/m/full-read": () => guessed });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  const options = (await screen.findAllByRole("option")).map((o) => o.textContent ?? "");
  expect(options[1]).toMatch(/^1 month: About 201 more messages\./);
});

test("Read it answers every open source of the account and one line names each with its own count", async () => {
  const user = userEvent.setup();
  const sent = source({ id: "s", label: "Your sent mail" });
  const inbox = source({ id: "m", label: "Your inbox" });
  const calls = fakeApi({
    "GET watch/m/full-read": () => offered,
    "GET watch/s/full-read": () => offered,
    "POST watch/m/full-read": () => ({ ...done(412), started: true }),
    "POST watch/s/full-read": () => ({ ...done(30), started: true }),
    "GET watch": () => [],
  });
  renderApp(<FullReadChoice sources={[inbox, sent]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: /1 month/ }));
  await user.click(screen.getByRole("button", { name: "Read it" }));
  expect(await screen.findByText("Taking in 412 older items from Your inbox. Taking in 30 older items from Your sent mail.")).toBeInTheDocument();
  expect(calls.filter((c) => c.route.startsWith("POST watch/") && c.route.endsWith("/full-read")).map((c) => c.route).sort()).toEqual(["POST watch/m/full-read", "POST watch/s/full-read"]);
});

test("a look that took in far fewer than its count says how many of how many, with about for an estimate", async () => {
  const user = userEvent.setup();
  const few = { ...done(2), started: true, short: true, expected: 201, expected_estimate: true, gave: 2 };
  fakeApi({ "GET watch/m/full-read": () => offered, "POST watch/m/full-read": () => few, "GET watch": () => [] });
  renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await user.click(await pickerOf());
  await user.click(await screen.findByRole("option", { name: /1 month/ }));
  await user.click(screen.getByRole("button", { name: "Read it" }));
  expect(await screen.findByText("Taking in 2 older items from Inbox. Took in 2 of about 201: the service gave no more.")).toBeInTheDocument();
});
