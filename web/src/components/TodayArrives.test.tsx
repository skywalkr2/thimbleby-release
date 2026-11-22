import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

// What arrives (design 6.32): a dated item's reminder on Today, and an area of life offered for items that share a word.

type Line = S["QueueLineView"];

const line = (kind: Line["kind"], over: Partial<Line> = {}): Line => ({
  key: kind,
  group: kind === "area" ? "review" : "risk",
  kind,
  count: 1,
  untrusted: false,
  unpriced: 0,
  actions: [],
  questions: [],
  outcome: {},
  ...over,
});

function show(lines: Line[], extra: Routes = {}) {
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
    "GET status": () => statusFixture({}, { assistant: { last_run_at: "2026-10-20T08:00:00Z" } }),
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
  vi.unstubAllGlobals();
  forgetLine();
});

const row = (kind: string) => document.querySelector<HTMLElement>(`[data-queue-line="${kind}"]`)!;

test("a reminder for a dated fact says what kind of day it is and opens the fact", async () => {
  const reminder = line("date_reminder", { text: "The studio plan renews", due: "2026-12-15", state: "renewal", fact: "FACT-4", at: "2026-12-01T09:00:00+00:00" });
  const { onOpenRecord } = show([reminder]);
  expect(await screen.findByText(/^Decide on the renewal: The studio plan renews \(.*15\)$/)).toBeInTheDocument();
  const found = row("date_reminder");
  expect(found).toHaveTextContent("Date coming");
  await userEvent.click(within(found).getByRole("button", { name: "Open it" }));
  expect(onOpenRecord).toHaveBeenCalledWith("fact", "FACT-4");
});

const NOTE = "From an email; check the address before you pay.";

test("a reminder to pay a bill that came from an email says where it came from, in its details", async () => {
  const user = userEvent.setup();
  show([line("date_reminder", { text: "The printer's invoice", due: "2026-12-15", state: "bill", fact: "FACT-5", untrusted: true, at: "2026-12-01T09:00:00+00:00" })]);
  const found = await waitFor(() => {
    const el = row("date_reminder");
    expect(el).not.toBeNull();
    return el;
  });
  expect(screen.queryByText(NOTE)).toBeNull();
  await user.click(within(found).getByRole("button", { name: /More actions for/ }));
  await user.click(screen.getByRole("menuitem", { name: "Look closer" }));
  expect(await screen.findByText(NOTE)).toBeInTheDocument();
});

test("a bill the person wrote down, and a renewal from an email, carry no such note", async () => {
  show([
    line("date_reminder", { key: "own", text: "My rent", due: "2026-12-15", state: "bill", fact: "FACT-6", untrusted: false, at: "2026-12-01T09:00:00+00:00" }),
    line("date_reminder", { key: "renewal", text: "The plan", due: "2026-12-15", state: "renewal", fact: "FACT-7", untrusted: true, at: "2026-12-01T09:00:00+00:00" }),
  ]);
  await screen.findByText(/My rent/);
  for (const found of document.querySelectorAll<HTMLElement>('[data-queue-line="date_reminder"]')) {
    expect(within(found).queryByRole("button", { name: /More actions for/ })).toBeNull();
  }
  expect(screen.queryByText(NOTE)).toBeNull();
});

const AREA_ITEMS = ["Book the dentist", "Ask about the crown", "Closed on Fridays", "Which dentist takes the new plan?"];
const area = line("area", { text: "Dentist", subject: "AREA-1", count: 4, reason: "All four are about looking after your teeth.", names: AREA_ITEMS });

test("an area the assistant offered shows why and every item it would take as its own row, never run together in one line", async () => {
  show([area]);
  await screen.findByText("Start the area Dentist");
  const rows = within(within(row("area")).getByRole("list", { name: "What it would take" })).getAllByRole("listitem");
  expect(rows.map((r) => r.textContent)).toEqual(AREA_ITEMS);
  expect(row("area")).toHaveTextContent("All four are about looking after your teeth.");
  expect(row("area")).toHaveTextContent("4 items");
  expect(row("area")).not.toHaveTextContent("Book the dentist; Ask about the crown");
  // The items sit inside the line's own card, in the shared item list, never bare lines beside it.
  const list = within(row("area")).getByRole("list", { name: "What it would take" });
  expect(list).toHaveAttribute("data-item-list");
  expect(row("area").contains(list)).toBe(true);
  expect(rows.every((r) => r.hasAttribute("data-item"))).toBe(true);
});

test("an area offered for items that share a word is started and filled with one press, and Undo takes both changes back", async () => {
  const keep = vi.fn(() => ({ project: "PRJ-9", filed: "CS-2", started: "CS-1" }));
  const undone: string[] = [];
  const { calls } = show([area], {
    "POST areas/keep": keep,
    "POST changesets/CS-2/undo": () => {
      undone.push("CS-2");
      return { restored: [0], skipped: [] };
    },
    "POST changesets/CS-1/undo": () => {
      undone.push("CS-1");
      return { restored: [0], skipped: [] };
    },
  });
  // The line starts with its one verb and the suggested name already in it; the box for another name is behind Rename.
  expect(await screen.findByText("Start the area Dentist")).toBeInTheDocument();
  expect(within(row("area")).queryByLabelText("Name of the area")).toBeNull();
  await userEvent.click(within(row("area")).getByRole("button", { name: "Start the area" }));
  await waitFor(() => expect(keep).toHaveBeenCalled());
  expect(calls.find((c) => c.route === "POST areas/keep")?.body).toEqual({ offer: "AREA-1", name: "Dentist" });
  expect(await screen.findByText("Started Dentist and filed 4 items under it")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(undone).toEqual(["CS-2", "CS-1"]));
});

test("Rename in the line's menu opens the name field with the cursor in it, and the area starts under the name typed", async () => {
  const user = userEvent.setup();
  const { calls } = show([area], { "POST areas/keep": () => ({ project: "PRJ-9", filed: "CS-2", started: "CS-1" }) });
  await screen.findByText("Start the area Dentist");
  await user.click(within(row("area")).getByRole("button", { name: /More|menu/i }));
  await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
  const field = await within(row("area")).findByLabelText("Name of the area");
  expect(field).toHaveValue("Dentist");
  await waitFor(() => expect(field).toHaveFocus());
  await user.clear(field);
  await user.type(field, "Teeth and health");
  await user.click(within(row("area")).getByRole("button", { name: "Start the area" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST areas/keep")?.body).toEqual({ offer: "AREA-1", name: "Teeth and health" }));
  expect(await screen.findByText("Started Teeth and health and filed 4 items under it")).toBeInTheDocument();
});

test("an offered area can be put off with Not now, like any suggestion", async () => {
  const user = userEvent.setup();
  const { calls } = show([area], { "POST suggestions/not-now": () => ({ signal: "SIG-3" }) });
  await screen.findByText("Start the area Dentist");
  await user.click(within(row("area")).getByRole("button", { name: /More|menu/i }));
  await user.click(await screen.findByRole("menuitem", { name: "Not now" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST suggestions/not-now")?.body).toEqual({ key: "area" }));
});
