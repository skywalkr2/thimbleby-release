import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

type Line = S["QueueLineView"];

const MESSAGE_LINK = ["https:", "", "mail.example.com", "m", "1"].join("/");

const line = (kind: Line["kind"], over: Partial<Line> = {}): Line => ({
  key: kind,
  group: "decide",
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
    "GET changes": () => [{ id: "REQ-9", version: 4, state: "needs_you", link: MESSAGE_LINK, refused: false } as S["ChangeItem"]],
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
    "POST changesets/CS-1/undo": () => ({ restored: [0], skipped: [] }),
    "POST suggestions/not-now/SIG-1/undo": () => ({ ok: "SIG-1" }),
    ...extra,
  });
  const view = renderApp(
    <RestartProvider hellos={1}>
      <Today workspace="Workspace" onView={vi.fn()} onAddSource={vi.fn()} onOpenGuide={vi.fn()} onOpenRecord={vi.fn()} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
  );
  return { calls, view };
}

afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
});

const row = (kind: string) => document.querySelector<HTMLElement>(`[data-queue-line="${kind}"]`)!;

const stopped = line("refused", {
  key: "refused:REQ-9",
  group: "risk",
  request: "REQ-9",
  waiting: "Tried 3 times without a usable answer. Nothing was applied: the assistant's second answer left out part of its first that was fine.",
  title: { kind: "email", sender: "Northfield Bank", topic: "Your statement is available" },
});

test("a stopped email says what happened in plain words, names the sender and no address, and says the reason nowhere on the line", async () => {
  show([stopped]);
  expect(await screen.findByText(/couldn't read the email from Northfield Bank · Your statement is available/)).toBeInTheDocument();
  const found = row("refused");
  expect(found).not.toHaveTextContent("@");
  expect(found).not.toHaveTextContent(/account|usable answer|left out/);
  expect(within(found).getAllByText("Nothing was changed.")).toHaveLength(1);
});

test("a stopped line offers Try again, and Read it myself, Skip it and Choose another account in its menu, each doing what it says", async () => {
  const user = userEvent.setup();
  const open = vi.fn();
  vi.stubGlobal("open", open);
  const { calls } = show([stopped], {
    "POST requests/REQ-9/retry": () => ({ ok: "REQ-9" }),
    "POST requests/REQ-9/dismiss": () => ({ ok: "REQ-9", version: 5 }),
    "POST requests/REQ-9/undismiss": () => ({ ok: "REQ-9", version: 6 }),
  });
  await screen.findByText(/couldn't read the email/);
  const found = row("refused");
  expect(await within(found).findByRole("button", { name: "Try again" })).toBeInTheDocument();
  expect(within(found).queryByRole("button", { name: /another account/ })).toBeNull();
  await user.click(within(found).getByRole("button", { name: /More actions for/ }));
  expect((await screen.findAllByRole("menuitem")).map((m) => m.textContent)).toEqual(["Read it myself", "Skip it", "Choose another account"]);
  await user.click(screen.getByRole("menuitem", { name: "Read it myself" }));
  expect(open).toHaveBeenCalledWith(MESSAGE_LINK, "_blank", "noopener,noreferrer");
  await user.click(within(row("refused")).getByRole("button", { name: /More actions for/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Skip it" }));
  await waitFor(() => expect(calls.find((c) => c.route === "POST requests/REQ-9/dismiss")?.body).toEqual({ read_version: 4 }));
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST requests/REQ-9/undismiss")).toBe(true));
});

test("Try again queues the item again", async () => {
  const user = userEvent.setup();
  const { calls } = show([stopped], { "POST requests/REQ-9/retry": () => ({ ok: "REQ-9" }) });
  await screen.findByText(/couldn't read the email/);
  await user.click(await within(row("refused")).findByRole("button", { name: "Try again" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST requests/REQ-9/retry")).toBe(true));
});
