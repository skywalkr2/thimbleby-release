import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { Refuse, fakeApi, renderApp } from "../test-utils";
import { AccountCosts, AiCostsSpending } from "./AiCosts";

const TODAY = new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

const account = (extra: Partial<S["AiAccountView"]> = {}): S["AiAccountView"] => ({
  name: "main",
  label: "Main account",
  kind: null,
  adapter: "adapter-one",
  base_url: null,
  models: { everyday: "model-a" },
  used_for: [],
  backup_for: [],
  has_key: true,
  key_state: "saved",
  key_where: null,
  key_ending: false,
  answered_at: null,
  spent_today_usd: 0,
  checked_for: [],
  check_failed_for: [],
  checked_at: null,
  paused_until: null,
  check_usd: null,
  accepted_unchecked: false,
  cost_report_offered: true,
  billing_key_state: "saved",
  billing_key_id: "key-1",
  cost_report_hours: 4,
  ...extra,
});

const day = (when: string, extra: Partial<S["AiCostDay"]> = {}): S["AiCostDay"] => ({
  day: when,
  reported: true,
  amount: 12.5,
  currency: "USD",
  read_at: `${TODAY}T08:00:00+00:00`,
  open: false,
  app_usd: 10,
  by_task: {},
  gap: false,
  ...extra,
});

const entry = (extra: Partial<S["AiCostAccount"]> = {}): S["AiCostAccount"] => ({
  name: "main",
  label: "Main account",
  scope: "key",
  read_at: `${TODAY}T08:00:00+00:00`,
  partial: false,
  failing: null,
  days: [],
  ...extra,
});

const costs = (...accounts: S["AiCostAccount"][]) => ({ "GET ai/costs": () => ({ accounts }) });

test("a day not reported yet says so and never shows nothing or zero, today says so far, and an open day may change", async () => {
  fakeApi({
    ...costs(
      entry({
        days: [
          day(TODAY, { reported: false, amount: null, currency: null, open: true, app_usd: 0.4 }),
          day(daysAgo(1), { open: true, amount: 3 }),
          day(daysAgo(5), { amount: 12.5, app_usd: 10 }),
        ],
      }),
    ),
  });
  renderApp(<AccountCosts account={account()} local />);
  const table = await screen.findByRole("table");
  const rows = within(table).getAllByRole("row");
  // header + three days, newest first, each day marked as a UTC day
  expect(rows).toHaveLength(4);
  expect(within(rows[1]).getByRole("rowheader")).toHaveTextContent("(UTC day)");
  expect(rows[1]).toHaveTextContent("not reported yet");
  expect(rows[1]).not.toHaveTextContent("$0.00");
  expect(rows[1]).toHaveTextContent("$0.40");
  expect(rows[2]).toHaveTextContent("$3.00, may still change");
  expect(rows[3]).toHaveTextContent("$12.50");
  expect(rows[3]).toHaveTextContent("$10.00");
  expect(rows[3]).not.toHaveTextContent("may still change");
});

test("today's figure reads so far when the service has reported it", async () => {
  fakeApi({ ...costs(entry({ days: [day(TODAY, { open: true, amount: 2 })] })) });
  renderApp(<AccountCosts account={account()} local />);
  expect(await screen.findByText("$2.00 so far")).toBeInTheDocument();
});

test("the figure of the app is split by kind of work, in words, never by an id", async () => {
  fakeApi({ ...costs(entry({ days: [day(daysAgo(3), { by_task: { notes: 6, "zz-internal-id": 4 } })] })) });
  renderApp(<AccountCosts account={account()} local />);
  const split = await screen.findByRole("list", { name: /by kind of work/ });
  expect(within(split).getAllByRole("listitem")).toHaveLength(2);
  expect(split).not.toHaveTextContent("zz-internal-id");
  expect(split).toHaveTextContent("$6.00");
});

test("a report of the whole organization says it includes use outside the app; another currency is shown, not compared", async () => {
  fakeApi({ ...costs(entry({ scope: "organization", days: [day(daysAgo(3), { currency: "EUR", amount: 5 })] })) });
  renderApp(<AccountCosts account={account({ billing_key_id: null })} local />);
  expect(await screen.findByText(/includes use outside/)).toBeInTheDocument();
  expect(screen.getByText("A report in another currency is shown, not compared.")).toBeInTheDocument();
});

test("a partial reading and a failing one are said, with why", async () => {
  fakeApi({ ...costs(entry({ partial: true, failing: "auth", days: [day(daysAgo(3))] })) });
  renderApp(<AccountCosts account={account()} local />);
  expect(await screen.findByText(/stopped early, so some days may be missing/)).toBeInTheDocument();
  expect(screen.getByText("The service didn't accept the billing key.")).toBeInTheDocument();
});

test("an account whose adapter has no report shows nothing, and asks the server for nothing", async () => {
  const calls = fakeApi({ ...costs() });
  const { container } = renderApp(<AccountCosts account={account({ cost_report_offered: false })} local />);
  expect(container.querySelector("[data-account-costs]")).toBeNull();
  expect(calls.filter((c) => c.route === "GET ai/costs")).toHaveLength(0);
});

test("a report that is off offers to be set up and shows no table", async () => {
  fakeApi({ ...costs() });
  renderApp(<AccountCosts account={account({ cost_report_hours: 0, billing_key_state: "none", billing_key_id: null })} local />);
  expect(await screen.findByRole("button", { name: "Read what Main account charged" })).toBeInTheDocument();
  expect(screen.queryByRole("table")).toBeNull();
});

test("setting it up: the cursor is in the key field, the keys are picked from a list, and what is saved is the key, the pick and the hours", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    ...costs(),
    "GET settings": () => ({ fingerprint: "fp-1", items: [] }),
    "POST ai/accounts/main/billing-keys": () => ({
      keys: [
        { id: "key-1", name: "Runs", hint: "abcd" },
        { id: "key-2", name: "Tests", hint: "wxyz" },
      ],
      problem: null,
    }),
    "POST ai/accounts/main/billing": () => ({ changes: [], fingerprint: "fp-2", needs_restart: false }),
  });
  renderApp(<AccountCosts account={account({ cost_report_hours: 0, billing_key_state: "none", billing_key_id: null })} local />);
  await user.click(await screen.findByRole("button", { name: "Read what Main account charged" }));
  const field = screen.getByLabelText("Billing key");
  expect(field).toHaveFocus();
  expect(field).toHaveAttribute("type", "password");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // nothing to save without a key
  await user.type(field, "admin-key");
  await user.click(screen.getByRole("button", { name: "Find my keys" }));
  await user.selectOptions(await screen.findByRole("combobox", { name: "The key this account runs with" }), "key-2");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST ai/accounts/main/billing")).toBe(true));
  const sent = calls.find((c) => c.route === "POST ai/accounts/main/billing")?.body as Record<string, unknown>;
  expect(sent).toMatchObject({ key: "admin-key", key_id: "key-2", hours: 4, fingerprint: "fp-1" });
  expect(calls.find((c) => c.route === "POST ai/accounts/main/billing-keys")?.body).toEqual({ key: "admin-key" });
});

test("a refused key is said where it was typed and nothing is closed", async () => {
  const user = userEvent.setup();
  fakeApi({
    ...costs(),
    "GET settings": () => ({ fingerprint: "fp-1", items: [] }),
    "POST ai/accounts/main/billing": () => new Refuse(400, "The service didn't accept the billing key. Add it again, or set the hours to 0 to stop asking."),
  });
  renderApp(<AccountCosts account={account({ cost_report_hours: 0, billing_key_state: "none", billing_key_id: null })} local />);
  await user.click(await screen.findByRole("button", { name: "Read what Main account charged" }));
  await user.type(screen.getByLabelText("Billing key"), "wrong");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("didn't accept the billing key");
  expect(screen.getByLabelText("Billing key")).toBeInTheDocument();
});

test("Settings lists every account whose report is on, and nothing when none is", async () => {
  fakeApi({
    ...costs(entry({ days: [day(daysAgo(3))] })),
    "GET ai/accounts": () => [account()],
    "GET ai/endpoints": () => [],
  });
  const { unmount } = renderApp(<AiCostsSpending />);
  expect(await screen.findByRole("heading", { name: "What the services charged" })).toBeInTheDocument();
  expect(await screen.findByRole("table")).toBeInTheDocument();
  unmount();
  fakeApi({ ...costs(), "GET ai/accounts": () => [], "GET ai/endpoints": () => [] });
  const { container } = renderApp(<AiCostsSpending />);
  await waitFor(() => expect(container.querySelector("[data-ai-costs]")).toBeNull());
});
