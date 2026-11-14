import "@testing-library/jest-dom/vitest";
import { waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { RestartProvider } from "../lib/restart";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

type Line = S["QueueLineView"];

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
    "GET changes": () => [{ id: "REQ-9", version: 4 } as S["ChangeItem"]],
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



// S-0053: every line carries an icon beside its words, as decoration (status is never by icon alone).
test("each kind of line carries an icon beside its words that screen readers skip", async () => {
  const kinds: Line["kind"][] = ["first_go", "needs_date", "since_yesterday", "backup", "area", "no_effect", "stale", "account_check"];
  show(kinds.map((kind) => line(kind, { key: `${kind}:1`, state: "never" })));
  await waitFor(() => expect(document.querySelectorAll("[data-queue-line]").length).toBe(kinds.length));
  for (const kind of kinds) {
    const found = document.querySelector<HTMLElement>(`[data-queue-line="${kind}"]`)!;
    const icon = found.querySelector("[data-row-lead] svg[data-icon]");
    expect(icon, `an icon on the ${kind} line`).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(within(found).queryByRole("img")).toBeNull();
  }
});
