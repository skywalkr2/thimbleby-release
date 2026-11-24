import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { entry } from "../lib/schedule-fixtures";
import { fakeApi, renderApp } from "../test-utils";
import { EntryDetails } from "./ScheduleEntryPane";

// An entry the assistant called off because a later mail cancelled it shows the mail's words as the reason beside "Called off"
// (design 6.32); an entry called off with no reason says only that it is called off.

afterEach(() => vi.unstubAllGlobals());

const ENTRY = "EVT-1";
const WHY = "Your reservation HS48213 for Friday, October 16 has been canceled";
const calendars = { name: () => undefined, color: () => undefined } as unknown as Parameters<typeof EntryDetails>[0]["calendars"];
const options = { record: ENTRY, kind: "event", account: null, account_label: null, acting: false, can_act: false, channel_label: null, actions: [], answers: [], propose_refusal: null, folder_source: null, folders_listed: false, from_automated: false, event_actions: [], event_own: true, event_why: null } as S["ActOptionsView"];

function open(extra: Record<string, unknown>) {
  fakeApi({
    [`GET record?kind=event&id=${ENTRY}`]: () => ({ kind: "event", id: ENTRY, version: 5, fields: { id: ENTRY, title: "Hotel", start: "2026-10-16T15:00:00+00:00", cancelled: true }, long_text: [] }),
    [`GET acts/options?record=${ENTRY}`]: () => options,
  });
  renderApp(<EntryDetails entry={entry({ title: "Hotel", snapshot: ENTRY, own: true, kind: "own", cancelled: true, held: true, ...extra }, "2026-10-16")} date="2026-10-16" calendars={calendars} />);
}

test("a call-off made from a mail shows the mail's words as the reason", async () => {
  open({ called_off_why: WHY });
  expect(await screen.findByText(`Called off: ${WHY}`)).toBeInTheDocument();
});

test("a call-off with no reason shows none", async () => {
  open({});
  expect(await screen.findByText("Paused: called off")).toBeInTheDocument();
  expect(screen.queryByText(/Called off:/)).toBeNull();
});
