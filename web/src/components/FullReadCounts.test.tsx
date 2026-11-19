import "@testing-library/jest-dom/vitest";
import { act, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { S } from "../lib/api";
import { refreshFamilies } from "../lib/write";
import { inHours, fakeApi, renderApp } from "../test-utils";
import { FullReadChoice } from "./FullReadChoice";
import { OlderReadWaiting } from "./OlderReadWaiting";

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
  options: [{ days: 30, count: 12, estimate_usd: 0.4, unpriced: 0, reaches: true, capped: false, estimate: false, unknown: false }],
};

test("the full-read choice asks for its counts once while open: not again on window focus or a change to something else", async () => {
  const calls = fakeApi({ "GET watch/m/full-read": () => offered });
  const { client } = renderApp(<FullReadChoice sources={[source()]} account="person@example.com" />);
  await screen.findByRole("combobox");
  const asked = () => calls.filter((c) => c.route === "GET watch/m/full-read").length;
  expect(asked()).toBe(1);
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await refreshFamilies(client, ["settings", "today"]);
    await refreshFamilies(client, ["watch"]);
  });
  expect(asked()).toBe(1);
});

test("a source whose read stopped shows the read waiting with its time and no full-read choice, and asks no counts", async () => {
  const at = inHours(2);
  const waiting = source({ full_read_open: false, older_read: { kind: "throttled", at, gave_up: false, taken: 412, tries: 1 } });
  const calls = fakeApi({ "GET watch/m/full-read": () => offered });
  renderApp(
    <>
      <OlderReadWaiting sources={[waiting]} />
      <FullReadChoice sources={[waiting]} account="person@example.com" />
    </>,
  );
  const said = await screen.findByRole("status");
  expect(said.textContent).toMatch(/^Taking in 412 older items from Inbox\. The rest continues around \d{1,2}:42[^,]*, after the mail service asked to slow down/);
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(calls.filter((c) => c.route === "GET watch/m/full-read")).toHaveLength(0);
});
