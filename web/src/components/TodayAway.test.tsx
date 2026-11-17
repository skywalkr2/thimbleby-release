import "@testing-library/jest-dom/vitest";
import { act, screen, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { useReminderNotices } from "./ReminderLine";
import { RestartProvider } from "../lib/restart";
import { showAllCameIn } from "../lib/came-in-window";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture } from "../test-utils";
import { Today } from "./Today";

// Work the assistant releases on its own keeps the person's hours (design 6.35): what waited for working hours arrives with
// one row, "While you were away", that says how many; the lines it groups are in their own places. A line that is held is not
// in the queue at all, so there is nothing to notify about until it is released.

type Line = S["QueueLineView"];

function line(kind: Line["kind"], over: Partial<Line> = {}): Line {
  return { key: `${kind}:1`, group: "decide", kind, count: 1, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over };
}

const away = (count: number) => line("away", { key: "away", count, at: "2026-11-17T22:30:00+00:00", since: "2026-11-18T08:00:00+00:00" });
const mail = (snapshot: string, title: string, received: string): S["ArrivedView"] => ({ snapshot, source: "src", title, received, version: 1, sides: [], also_in: [] }) as S["ArrivedView"];
const decision = line("decision", { key: "question:Q-1", text: "Which printer?", question: "Q-1" });

function show(lines: Line[], arrived: S["ArrivedView"][] = []) {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
  fakeApi({
    "GET today/queue": () => lines,
    "GET changes": () => [],
    "GET followups": () => [],
    "GET plugin-today": () => [],
    "GET stages/records": () => [],
    "GET stages/ready": () => [],
    "GET stages/requests": () => [],
    "GET today/agenda": () => [],
    "GET today/todo": () => [],
    "GET today/arrived": () => ({ items: arrived, left_out: 0, set_aside: 0 }),
    "GET watch": () => [],
    "GET projects": () => [],
    "GET people": () => [],
    "GET status": () => statusFixture(),
    "GET runtime-config": () => ({ instance: null }),
  });
  renderApp(
    <RestartProvider hellos={1}>
      <Today workspace="Workspace" onView={vi.fn()} onAddSource={vi.fn()} onOpenGuide={vi.fn()} onOpenRecord={vi.fn()} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
  showAllCameIn();
});

test("what waited arrives under one row that says how many, not a row for each", async () => {
  show([away(3), decision]);
  const name = "Look over the 3 things that came in while you were away";
  const row = (await screen.findByRole("group", { name })) as HTMLElement;
  // One action, in the neutral tone, and no warning mark.
  expect(within(row).getAllByRole("button")).toHaveLength(1);
  expect(within(row).getByRole("button", { name: "Look over" })).toBeInTheDocument();
  expect(within(row).getByText("Arrived").closest("[data-state-mark]")).toHaveAttribute("data-tone", "neutral");
  expect(row.querySelector('[data-tone="warn"], [data-tone="danger"], [data-tone="need"]')).toBeNull();
  expect(screen.getAllByText(/came in while you were away/)).toHaveLength(1);
  expect(await screen.findByRole("group", { name: "Which printer?" })).toBeInTheDocument();
});

test("Look over opens Came in with only what arrived while the person was away, and Show all brings the rest back", async () => {
  show(
    [away(2), decision],
    [
      mail("s1", "Parcel to collect", "2026-11-17T23:10:00+00:00"),
      mail("s2", "Invoice for May", "2026-11-18T06:00:00+00:00"),
      mail("s3", "Lunch on Friday?", "2026-11-18T09:30:00+00:00"),
    ],
  );
  const row = await screen.findByRole("group", { name: "Look over the 2 things that came in while you were away" });
  expect(await screen.findByText("Lunch on Friday?")).toBeInTheDocument();
  await userEvent.click(within(row).getByRole("button", { name: "Look over" }));
  expect(await screen.findByText("Showing what came in while you were away", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("Parcel to collect")).toBeInTheDocument();
  expect(screen.getByText("Invoice for May")).toBeInTheDocument();
  expect(screen.queryByText("Lunch on Friday?")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Show all" }));
  expect(await screen.findByText("Lunch on Friday?")).toBeInTheDocument();
});

test("one thing is said in the singular", async () => {
  show([away(1), decision]);
  expect(await screen.findByRole("group", { name: "Look over the 1 thing that came in while you were away" })).toBeInTheDocument();
});

test("with nothing that waited there is no row", async () => {
  show([decision]);
  await screen.findByRole("group", { name: "Which printer?" });
  expect(screen.queryByText(/while you were away/)).toBeNull();
});

// ---- notifications ----------------------------------------------------------------------------------------------

function lineSource(first: Line[]) {
  let set: (lines: Line[]) => void = () => undefined;
  function Host() {
    const [lines, setLines] = useState(first);
    set = setLines;
    useReminderNotices(lines);
    return null;
  }
  return { Host, show: (lines: Line[]) => act(() => set(lines)) };
}

function stubNotification() {
  const shown: string[] = [];
  class Fake {
    static permission: NotificationPermission = "granted";
    static requestPermission = vi.fn(async () => "granted" as NotificationPermission);
    constructor(title: string) {
      shown.push(title);
    }
  }
  vi.stubGlobal("Notification", Fake);
  return shown;
}

test("a held line is not in the queue, so nothing is shown for it, and released lines with their row show no notification", () => {
  const shown = stubNotification();
  const source = lineSource([]);
  renderApp(<source.Host />);
  // Held: the queue holds nothing new while the hours are out.
  source.show([]);
  expect(shown).toEqual([]);
  // Released: the lines and their row arrive together at the start of the hours; none of them is a reminder.
  source.show([away(2), decision, line("go", { key: "go:REQ-1" })]);
  expect(shown).toEqual([]);
});

test("a reminder the person set still notifies at its own time", () => {
  const shown = stubNotification();
  const source = lineSource([]);
  renderApp(<source.Host />);
  source.show([line("reminder", { key: "reminder:ACT-1", group: "risk", text: "Call the printer", late: false })]);
  expect(shown).toEqual(["Call the printer · due now"]);
});
