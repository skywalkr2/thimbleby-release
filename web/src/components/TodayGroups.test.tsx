import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { S } from "../lib/api";
import { project } from "../lib/records-fixtures";
import { RestartProvider } from "../lib/restart";
import { setSideChoice } from "../lib/sides";
import { forgetLine } from "../lib/today";
import { fakeApi, renderApp, setupStep, setupView, statusFixture, type Routes } from "../test-utils";
import { Today } from "./Today";

// Today's groups (design 7.7): an account that is not being read is the first line at risk and counts among the things that need
// the person; the gaps in setup are the last group, "Finish setting up", with how far setup is in its header, and are not counted;
// on a heavy day each group shows its first lines and a button for the rest, and the page ends with the count of open to-dos.

type Line = S["QueueLineView"];
type Source = S["WatchSourceView"];

const NOW = new Date();
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();

const line = (kind: Line["kind"], over: Partial<Line> = {}): Line => ({ key: `${kind}:1`, group: "decide", kind, count: 1, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over });
const decision = (n: number, group: Line["group"] = "decide"): Line => line("decision", { key: `question:Q-${group}-${n}`, group, text: `Question ${group} ${n}?`, question: `Q-${group}-${n}`, });

const SIDE: S["SideView"] = { project: "PRJ-harbor", kind: "business", name: "Harborview", removable: false, filed: 0 };
const OTHER: S["SideView"] = { project: "PRJ-lantern", kind: "job", name: "Lantern Row", removable: false, filed: 0 };

function source(id: string, over: Partial<Source> = {}): Source {
  return { id, label: `Inbox ${id}`, connector: "pack/mail", connector_label: "Mail", enabled: true, every_minutes: 15, items: 1, last: null, read_at: hoursAgo(1), failures: 0, problem: null, reads: ["mail"], sides: [SIDE.project], account: "avery.lane@example.com", account_state: "signed_in", ...over };
}
const expired = (over: Partial<Source> = {}) => source("mail-a", { account_state: "expired", read_at: hoursAgo(2), ...over });

function show(lines: Line[], extra: Routes = {}) {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
  const sides = [SIDE, OTHER];
  const onView = vi.fn();
  const onOpenGuide = vi.fn();
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
    "GET today/arrived": () => ({ items: [], left_out: 0, set_aside: 0 }),
    "GET watch": () => [],
    "GET sign-ins": () => [{ name: "pack/account", label: "Example mail", status: "expired", ready: true, several: false, accounts: [], callback: "http://127.0.0.1/api/sign-ins/callback", allows: [] }],
    "GET status": () => statusFixture({}, { assistant: { last_run_at: "2026-10-20T08:00:00Z" } }),
    "GET runtime-config": () => ({ instance: null }),
    "GET setup/business": () => ({ business: true, name: SIDE.name, personal: "PRJ-personal", sides, chosen: null }),
    "GET projects": () => [project("PRJ-personal", "Personal"), ...sides.map((s) => project(s.project, s.name))],
    "GET views": () => [],
    "GET waiting": () => ({ changed: { total: 0, new: 0 }, handled: { total: 0, new: 0 }, followups: { total: 0, new: 0 }, open: { total: 0, new: 0 } }),
    ...extra,
  });
  renderApp(
    <RestartProvider hellos={1}>
      <Today workspace="Workspace" onView={onView} onAddSource={vi.fn()} onOpenGuide={onOpenGuide} onOpenRecord={vi.fn()} shortcuts={{ next: "j", previous: "k" }} />
    </RestartProvider>,
  );
  return { onView, onOpenGuide };
}

beforeEach(() => {
  window.localStorage.clear();
  setSideChoice("all");
});
afterEach(() => {
  vi.unstubAllGlobals();
  forgetLine();
});

const groupOf = (name: string) => screen.getByRole("heading", { level: 3, name: new RegExp(`^${name}`) }).closest("section") as HTMLElement;
/** The group once its lines are drawn (while they load, its heading stands over placeholders). */
const loaded = (name: string) =>
  waitFor(() => {
    const group = groupOf(name);
    expect(rowsOf(group).length).toBeGreaterThan(0);
    return group;
  });
/** The lines a group draws: the queue's own and the accounts'. */
const rowsOf = (group: HTMLElement) => Array.from(group.querySelectorAll<HTMLElement>("[data-queue-line], [data-account-line]"));

// ---- an account that is not being read --------------------------------------------------------------------------------------

test("an expired account is the first line at risk, naming its side and since when, tinted, with the screen's one filled Sign in again, and it is counted", async () => {
  show([decision(1, "risk")], { "GET watch": () => [expired()] });
  const risk = await loaded("At risk");
  const first = rowsOf(risk)[0];
  expect(first).toHaveTextContent(/^Your Example mail account's mail isn't being read · since /);
  expect(first).not.toHaveTextContent("@example.com");
  expect(within(first).getByRole("button", { name: /Sign in again/ })).toHaveAttribute("data-weight", "filled");
  // It is the only tinted row of the group, and the only filled button on the screen: the question under it is a plain row with an outlined button.
  expect(first).toHaveAttribute("data-state", "danger");
  const second = rowsOf(risk)[1];
  expect(second).not.toHaveAttribute("data-state");
  expect(within(second).getByRole("button", { name: "Answer" })).toHaveAttribute("data-weight", "outline");
  expect(document.querySelectorAll('[data-weight="filled"]')).toHaveLength(1);
  // Two things need the person: the account and the question.
  expect((await screen.findAllByText("2 things need you")).length).toBeGreaterThan(0);
});

test("three accounts of one service, one refused: one line naming the service and the account's own label, no address anywhere on Today", async () => {
  const one = (id: string, address: string, over: Partial<Source> = {}) => source(id, { account: address, label: `${id}-label, ${address}`, ...over });
  show([], {
    "GET watch": () => [
      one("a", "avery.lane@example.com"),
      one("b", "robin.hart@example.com", { account_state: "expired" }),
      one("c", "sam.ford@example.com"),
    ],
  });
  const line = await screen.findByText(/aren't|isn't being read/);
  expect(line).toHaveTextContent(/^b-label's mail isn't being read/);
  expect(document.body).not.toHaveTextContent("@example.com");
  expect(document.querySelectorAll("[data-account-line]")).toHaveLength(1);
});

test("two accounts of one service with the same label are told apart by number, never by address", async () => {
  const one = (id: string, address: string, over: Partial<Source> = {}) => source(id, { account: address, label: "Your inbox", ...over });
  show([], { "GET watch": () => [one("a", "avery.lane@example.com", { account_state: "expired" }), one("b", "robin.hart@example.com")] });
  expect(await screen.findByText(/^Your Example mail account \(1\)'s mail isn't being read/)).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("@example.com");
});

test("a refused account says calendar when it holds only a calendar, and both when it holds both", async () => {
  show([], { "GET watch": () => [expired({ id: "cal", reads: ["calendar"] })] });
  expect(await screen.findByText(/^Your Example mail account's calendar isn't being read/)).toBeInTheDocument();
});

test("an account that is only retrying stays out of Today until it has gone a day, then it is a line that opens Connections", async () => {
  const retrying = (h: number) => source("mail-a", { account_state: "signed_in", last: { outcome: "failed", error_kind: "outage" } as Source["last"], read_at: hoursAgo(h) });
  show([], { "GET watch": () => [retrying(3)] });
  await screen.findAllByText(/Nothing|nothing/);
  expect(screen.queryByText(/isn't being read/)).toBeNull();
});

test("an account retrying for more than a day is a line with a button to Connections", async () => {
  const user = userEvent.setup();
  const old = source("mail-a", { account_state: "signed_in", last: { outcome: "failed", error_kind: "outage" } as Source["last"], read_at: hoursAgo(30) });
  const { onView } = show([], { "GET watch": () => [old] });
  expect(await screen.findByText(/^Your Example mail account's mail isn't being read/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open Connections" }));
  expect(onView).toHaveBeenCalled();
});

test("the line goes as soon as the account reads again", async () => {
  show([], { "GET watch": () => [source("mail-a")] });
  await screen.findAllByText(/Nothing needs you/);
  expect(screen.queryByText(/isn't being read/)).toBeNull();
});

// ---- the gaps in setup ---------------------------------------------------------------------------------------------------------

const STEPS = ["workspace", "work", "ai", "mail", "backup", "people"].map((id) => setupStep(id, id === "workspace" || id === "work" ? { done: true } : {}));

test("the gaps in setup are the last group, with how far setup is in its header, and are not counted among the things that need you", async () => {
  const { onOpenGuide } = show([decision(1), line("no_account", { key: "no_account", group: "setup", names: ["routine"] }), line("backup", { key: "backup", group: "setup", state: "unset" })], { "GET setup": () => setupView(STEPS) });
  const setup = await loaded("Finish setting up");
  expect(setup).toHaveTextContent("2 of 6 done");
  expect(rowsOf(setup)).toHaveLength(2);
  // Last of the groups, and the line above it is the only thing that needs the person.
  const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(heads[heads.length - 1]).toMatch(/^Finish setting up/);
  expect((await screen.findAllByText("1 thing needs you")).length).toBeGreaterThan(0);
  expect(screen.queryByRole("heading", { level: 3, name: /^At risk/ })).toBeNull();
  await userEvent.click(within(setup).getByRole("button", { name: "Continue setup" }));
  expect(onOpenGuide).toHaveBeenCalledWith("ai");
});

test("an assistant that worked and then stopped is At risk, not a gap in setup", async () => {
  show([line("no_account", { key: "no_account", group: "risk", names: ["routine"] })], { "GET setup": () => setupView(STEPS, { finished: true }) });
  const risk = await loaded("At risk");
  expect(rowsOf(risk)).toHaveLength(1);
  expect(risk).toHaveTextContent("Helper has stopped: add an AI account");
  expect((await screen.findAllByText("1 thing needs you")).length).toBeGreaterThan(0);
});

// ---- a heavy day ---------------------------------------------------------------------------------------------------------------

test("on a heavy day each group shows its first five lines and a button for the rest, and the page ends with the open to-dos", async () => {
  const user = userEvent.setup();
  const lines = [...Array.from({ length: 12 }, (_, n) => decision(n + 1)), ...Array.from({ length: 22 }, (_, n) => decision(n + 1, "risk")), ...Array.from({ length: 8 }, (_, n) => decision(n + 1, "review"))];
  const waiting = { changed: { total: 0, new: 0 }, handled: { total: 0, new: 0 }, followups: { total: 0, new: 0 }, open: { total: 112, new: 0 } };
  const { onView } = show(lines, { "GET waiting": () => waiting });
  const decide = await loaded("Decide");
  expect(rowsOf(decide)).toHaveLength(5);
  expect(rowsOf(groupOf("At risk"))).toHaveLength(5);
  expect(rowsOf(groupOf("Review"))).toHaveLength(5);
  await user.click(within(decide).getByRole("button", { name: "Show 7 more" }));
  expect(rowsOf(groupOf("Decide"))).toHaveLength(12);
  expect(await screen.findByText("112 open to-dos")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open To-dos" }));
  expect(onView).toHaveBeenCalledWith("work/open");
  await user.click(within(groupOf("Decide")).getByRole("button", { name: "Show fewer" }));
  expect(rowsOf(groupOf("Decide"))).toHaveLength(5);
});

test("a day below the threshold shows every line, and no count of open to-dos", async () => {
  show(Array.from({ length: 8 }, (_, n) => decision(n + 1)), { "GET waiting": () => ({ changed: { total: 0, new: 0 }, handled: { total: 0, new: 0 }, followups: { total: 0, new: 0 }, open: { total: 112, new: 0 } }) });
  const decide = await loaded("Decide");
  expect(rowsOf(decide)).toHaveLength(8);
  expect(screen.queryByText(/open to-dos/)).toBeNull();
});

test("under one side's filter an account that serves no side says Every side beside that side's own lines, and says nothing on it when the side has none", async () => {
  setSideChoice(OTHER.project);
  // The side has a line of its own: the line on no side says so, so it is never read as the side's.
  show([line("decision", { key: "question:Q-own", text: "Own question?", question: "Q-own", side: OTHER.project }), line("review", { group: "review", key: "review:1", count: 2 })], { "GET watch": () => [expired({ sides: [] })] });
  const risk = await loaded("At risk");
  expect(rowsOf(risk)[0]).toHaveTextContent("Every side");
  expect(document.querySelector('[data-queue-line="review"] [data-every-side]')).not.toBeNull();
  cleanup();
  // The side has nothing of its own: the empty card says so, and no row repeats "Every side" over a list that is all of it.
  show([line("review", { group: "review", key: "review:1", count: 2 })], { "GET watch": () => [expired({ sides: [] })] });
  const bare = await loaded("At risk");
  expect(await screen.findByText(/Nothing on the Lantern Row side today/)).toBeInTheDocument();
  expect(rowsOf(bare)[0]).not.toHaveTextContent("Every side");
  expect(document.querySelector("[data-every-side]")).toBeNull();
});

test("no part of an account's address is on Today: one account of a service is named by the service, whatever its label or sides", async () => {
  const all = () => `${document.body.textContent} ${Array.from(document.querySelectorAll("[title],[aria-label]")).map((e) => `${e.getAttribute("title")} ${e.getAttribute("aria-label")}`).join(" ")}`;
  const several = { account: "harper.quinn@example.com", label: "Inbox, harper.quinn@example.com", sides: [SIDE.project, OTHER.project] };
  show([], { "GET watch": () => [expired(several)] });
  expect(await screen.findByText(/^Your Example mail account's mail isn't being read/)).toBeInTheDocument();
  expect(all()).not.toMatch(/@|harper|quinn/i);
  cleanup();
  // A service the person can't be told by name leaves the wording sheet's plain phrase.
  show([], { "GET watch": () => [expired({ ...several, connector_label: "" })], "GET sign-ins": () => [] });
  expect(await screen.findByText(/^Your account's mail isn't being read/)).toBeInTheDocument();
  expect(all()).not.toMatch(/@|harper|quinn/i);
});
