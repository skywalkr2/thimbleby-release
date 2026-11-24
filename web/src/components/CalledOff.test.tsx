import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { forgetLine } from "../lib/today";
import { RestartProvider } from "../lib/restart";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

// A called-off entry is held, not done (design 6.33; S-0001, S-0002): its line on Today asks for a new date or a drop with a
// reason, a drop asks once about the to-dos held for it, and an entry of a connected calendar says to move it there.

type Line = S["QueueLineView"];

const line = (kind: Line["kind"], over: Partial<Line> = {}): Line => ({ key: `${kind}:1`, group: "review", kind, count: 1, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over });

function today(lines: Line[], extra: Routes = {}) {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
  const calls = fakeApi({
    "GET today/queue": () => lines,
    "GET changes": () => [],
    "GET followups": () => [],
    "GET plugin-today": () => [],
    "GET stages/records": () => [],
    "GET stages/ready": () => [],
    "GET stages/requests": () => [],
    "GET today/agenda": () => [],
    "GET today/todo": () => [],
    "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
    "GET watch": () => [],
    "GET projects": () => [],
    "GET people": () => [],
    "GET status": () => statusFixture(),
    "GET runtime-config": () => ({ instance: null }),
    ...extra,
  });
  const onOpenRecord = vi.fn();
  renderApp(
    <RestartProvider hellos={1}>
      <Today workspace="Workspace" onView={vi.fn()} onAddSource={vi.fn()} onOpenGuide={vi.fn()} onOpenRecord={onOpenRecord} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
  );
  return { calls, onOpenRecord };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  forgetLine();
});

const rowOf = async (title: string) => (await screen.findByRole("group", { name: title })) as HTMLElement;


const EVENT = { kind: "event", id: "EVT-1", version: 3, long_text: [], fields: { title: "Walkthrough", start: "2026-11-12T14:00:00+00:00", end: "2026-11-12T15:00:00+00:00" } };

test("a called-off entry is a line that offers a new date, and giving one is the person's own change with Undo", async () => {
  const user = userEvent.setup();
  const { calls } = today([line("called_off", { key: "called_off:EVT-1", group: "decide", text: "Walkthrough", event: "EVT-1", state: "own", count: 2, at: "2026-11-12T14:00:00+00:00" })], {
    "GET record?kind=event&id=EVT-1": () => EVENT,
    "POST events/EVT-1/new-date": () => ({ changeset: "CS-1", refused: null }),
  });
  const row = await rowOf("Set a new date for Walkthrough, or drop it");
  expect(within(row).getByText("Paused")).toBeInTheDocument();
  expect(row).toHaveTextContent("2 to-dos paused with it");
  await user.click(within(row).getByRole("button", { name: "New date" }));
  await user.click(await within(row).findByRole("button", { name: "Set the new date" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST events/EVT-1/new-date")?.body).toMatchObject({ end: expect.any(String) }));
  expect(await screen.findByText("Gave Walkthrough a new date")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
});

test("Drop needs the person's reason in their words and sends it", async () => {
  const user = userEvent.setup();
  const { calls } = today([line("called_off", { key: "called_off:EVT-1", group: "decide", text: "Walkthrough", event: "EVT-1", state: "own", count: 0, at: "2026-11-12T14:00:00+00:00" })], {
    "POST events/EVT-1/drop": () => ({ changeset: "CS-2", refused: null }),
  });
  const row = await rowOf("Set a new date for Walkthrough, or drop it");
  await user.click(within(row).getByRole("button", { name: /More actions|Actions|More/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Drop it" }));
  const go = await within(row).findByRole("button", { name: "Drop it" });
  expect(go).toBeDisabled();
  const box = within(row).getByRole("textbox", { name: "Why is Walkthrough dropped?" });
  await waitFor(() => expect(box).toHaveFocus());
  await user.type(box, "The client withdrew");
  await user.click(go);
  await waitFor(() => expect(calls.find((c) => c.route === "POST events/EVT-1/drop")?.body).toEqual({ reason: "The client withdrew" }));
  expect(await screen.findByText("Dropped Walkthrough")).toBeInTheDocument();
});

test("a connected calendar's called-off entry says to move it there, and offers no new date of its own", async () => {
  const { onOpenRecord } = today([line("called_off", { key: "called_off:EVT-2", group: "decide", text: "Standup", event: "EVT-2", state: "connected", count: 0, at: "2026-11-12T09:00:00+00:00" })]);
  const row = await rowOf("Set a new date for Standup, or drop it");
  expect(row).toHaveTextContent("Move it in your calendar; this follows");
  expect(within(row).queryByRole("button", { name: "New date" })).toBeNull();
  await userEvent.setup().click(within(row).getByRole("button", { name: "Open entry" }));
  expect(onOpenRecord).toHaveBeenCalledWith("event", "EVT-2");
});

test("a dropped entry asks once about the to-dos held for it: Keep them or Drop them", async () => {
  const user = userEvent.setup();
  const { calls } = today([line("called_off_todos", { key: "called_off_todos:EVT-1", group: "decide", text: "Walkthrough", event: "EVT-1", count: 2, actions: ["ACT-1", "ACT-2"] })], {
    "POST events/EVT-1/keep-todos": () => ({ changeset: "CS-3", refused: null }),
  });
  const row = await rowOf("Keep or drop the to-dos for Walkthrough");
  expect(row).toHaveTextContent("2 to-dos paused with it");
  await user.click(within(row).getByRole("button", { name: "Keep them" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST events/EVT-1/keep-todos")).toBe(true));
  expect(await screen.findByText("Kept the to-dos for Walkthrough")).toBeInTheDocument();
});

test("an entry called off by a mail reads as its decision: rebook sets a new date, let it go drops it", async () => {
  const user = userEvent.setup();
  const { calls } = today([line("called_off", { key: "called_off:EVT-3", group: "decide", text: "Hotel", event: "EVT-3", state: "mail", count: 0, at: "2026-12-04T15:00:00+00:00" })], {
    "GET record?kind=event&id=EVT-3": () => ({ ...EVENT, id: "EVT-3", fields: { title: "Hotel", start: "2026-12-04T15:00:00+00:00" } }),
    "POST events/EVT-3/new-date": () => ({ changeset: "CS-3", refused: null }),
    "POST events/EVT-3/drop": () => ({ changeset: "CS-4", refused: null }),
  });
  const row = await rowOf("Hotel for Fri, Dec 4 was canceled: rebook or let it go");
  expect(within(row).queryByRole("button", { name: "New date" })).toBeNull();
  await user.click(within(row).getByRole("button", { name: "Rebook" }));
  await user.click(await within(row).findByRole("button", { name: "Set the new date" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST events/EVT-3/new-date")).toBe(true));
});

test("Let it go drops a mail-canceled entry with the person's reason, as Drop does", async () => {
  const user = userEvent.setup();
  const { calls } = today([line("called_off", { key: "called_off:EVT-3", group: "decide", text: "Hotel", event: "EVT-3", state: "mail", count: 0, at: "2026-12-04T15:00:00+00:00" })], {
    "POST events/EVT-3/drop": () => ({ changeset: "CS-4", refused: null }),
  });
  const row = await rowOf("Hotel for Fri, Dec 4 was canceled: rebook or let it go");
  await user.click(within(row).getByRole("button", { name: /More actions|Actions|More/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Let it go" }));
  await user.type(await within(row).findByRole("textbox", { name: "Why is Hotel dropped?" }), "Staying with friends");
  await user.click(within(row).getByRole("button", { name: "Drop it" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST events/EVT-3/drop")?.body).toEqual({ reason: "Staying with friends" }));
});
