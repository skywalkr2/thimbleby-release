// S-0668: a person's path under a real service's limits. Two accounts of the made-up mail service, each with a real-sized mailbox, the
// service refusing an account's every request for a few seconds after a refusal (and longer for each request made inside that time),
// and the person walking setup from its first screen: both accounts signed in, a month read in full on the first, then Continue and
// nothing else. What the person sees is checked (First reading ends, People offers people, the older read ends by itself), and what the
// service was asked is read from its own log: no request for an account inside its penalty window, and no more fetches than messages.
// Names come from the fictional workspace the fake services serve, never written out here.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choose } from "./choose";
import { collectProblems, fakeAddress, turnOnAndGoOn, pressStart, visit, type Info } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_RE5_FAKE_PORT", 8604);
const LOADED = { timeout: 60_000 };
/** Seconds the service refuses an account after a refusal: the config sets it for the fake services and tells the journey. */
const PENALTY = Number(process.env.JOURNEY_RE5_QUOTA_PENALTY ?? 6);
const problems: string[] = [];

/** Words that belong to the app's insides or to the service, never to the person. */
const INTERNAL = /ConnectorError|throttled|TooManyRequests|ServiceBusy|HTTP 429|\b429\b|Retry-After|watch_run|older_read|traceback|undefined|\[object/i;

interface WatchSource {
  id: string;
  account?: string;
  account_state?: string;
  looked_back_to?: string | null;
  full_read_open?: boolean | null;
  label: string;
  reads?: string[];
  items: number;
  older_read?: { taken: number; kind: string; at?: string | null; gave_up: boolean } | null;
}
interface SetupSeen {
  reading: { state: string; why?: string; sources: number; read: number; found: number };
}
/** One request the made-up service counted: for which account (from 1), when (seconds), which endpoint, and how it answered. */
interface Asked {
  account: number;
  time: number;
  endpoint: string;
  answer: "ok" | "refused";
}

const auth = (info: Info) => ({ Authorization: `Bearer ${info.token}` });

/** The requests that fall inside a penalty window: a refusal opens one for `penalty` seconds, and any request, answered or not, made
 * before it ends is a request the app should not have sent. A refusal outside a window only opens the next. */
function insidePenalty(log: Asked[], penalty: number): Asked[] {
  const found: Asked[] = [];
  for (const account of new Set(log.map((r) => r.account))) {
    let until = 0;
    for (const r of log.filter((x) => x.account === account).sort((a, b) => a.time - b.time)) {
      if (r.time < until) found.push(r);
      if (r.answer === "refused") until = r.time + penalty;
    }
  }
  return found;
}

test.describe.serial("journey: two accounts under a rate limit", () => {
  // The journey changes its server's state (a fresh workspace, signed-in accounts), and a re-run would start from that used server and
  // fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its failure as it is (S-0560).
  test.describe.configure({ retries: 0 });
  test.use({ actionTimeout: 30_000 });
  let info: Info;
  let addresses: string[];

  test.beforeAll(async () => {
    info = (await (await fetch(`${FAKE}/__e2e/info`)).json()) as Info;
    addresses = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts.map((a) => a.address);
    expect(addresses).toHaveLength(2);
  });

  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  const setup = async (page: Page) => (await (await page.request.get("api/setup", { headers: auth(info) })).json()) as SetupSeen;
  const watch = async (page: Page) => (await (await page.request.get("api/watch", { headers: auth(info) })).json()) as WatchSource[];
  const asked = async () => ((await (await fetch(`${FAKE}/__e2e/requests`)).json()) as { requests: Asked[] }).requests;

  test("S-0668. two accounts, a real-sized mailbox each and a limit that refuses: no request inside a penalty window, First reading ends, People offers people, the older read ends by itself", async ({ page }) => {
    test.setTimeout(600_000);
    const began = Date.now();
    collectProblems(page, problems);
    // The service refuses like a real one: the stand-in was started with its limit on.
    expect(PENALTY).toBeGreaterThan(0);
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
    await pressStart(page);
    const main = page.locator("main#main");

    // 1. You, what it is for (Personal alone), the AI step with its one explicit yes, and the assistant turned on.
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible(LOADED);
    await main.getByLabel("Your full name").fill(info.people[0]);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible(LOADED);
    await main.getByRole("radio", { name: /Something else/ }).check();
    await main.getByRole("button", { name: /^Another service/ }).click();
    await main.getByLabel(/^Another service/).check();
    await main.locator("#ai-key").fill("a-made-up-key");
    await main.getByRole("textbox", { name: "Service address" }).fill(info.ai_base_url);
    await main.getByRole("textbox", { name: "Service address" }).blur();
    await expect(main.getByText("Works. Ready to use.")).toBeVisible(LOADED);
    await main.getByRole("radio", { name: /^Yes/ }).check();
    await main.getByRole("button", { name: "Continue" }).click();
    await turnOnAndGoOn(main);
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible(LOADED);

    // 2. Both accounts, one after the other, through the service's own page.
    const row = main.locator('[data-service="journey-mail"]');
    for (const [n, address] of addresses.entries()) {
      if (n > 0) await main.getByRole("button", { name: /^Connect another account/ }).click();
      const button = n === 0 ? row.getByRole("button", { name: "Sign in to Example mail", exact: true }) : page.getByRole("dialog").getByRole("button", { name: "Add another account to Example mail", exact: true });
      const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
      await popup.getByRole("link", { name: address, exact: true }).click();
      await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
      await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
      await expect(page.getByRole("dialog")).toHaveCount(0, LOADED);
      await expect(main.locator("[data-account-row]")).toHaveCount(n + 1, LOADED);
    }

    // 3. A month in full on the first account: the window and what the service holds in it are asked before anything is read.
    const first = main.locator(`[data-account-row="${addresses[0]}"]`);
    const mine = async () => (await watch(page)).filter((w) => w.account === addresses[0]);
    // With two accounts a connection's name tells them apart, so the inbox is the one that reads mail and is not the sent mail.
    const inbox = async () => {
      const found = (await mine()).find((w) => w.reads?.includes("mail") && /inbox/i.test(w.label));
      expect(found, `an inbox of ${addresses[0]} among ${JSON.stringify((await watch(page)).map((w) => [w.label, w.account]))}`).toBeTruthy();
      return found!;
    };
    const before = await inbox();
    expect(before.older_read ?? null).toBeNull();
    const pick = first.locator("[data-full-read]").getByRole("combobox");
    await expect(pick).toBeVisible(LOADED);
    await choose(pick, "1 month");
    await visit(page);
    await first.locator("[data-full-read]").getByRole("button", { name: "Read it" }).click();
    // The reach of one month: the older read is done when the inbox looks back that far (the first read took the last 14 days).
    const reach = new Date(Date.parse(before.looked_back_to + "T00:00:00Z") - 16 * 86_400_000).toISOString().slice(0, 10);

    // 4. Continue, and nothing after it: First reading ends (waiting lines are shown with a time, never an empty step) and People follows.
    await main.getByRole("button", { name: "Continue" }).click();
    // The second account's "Read in full from" was left unanswered, so Continue asks once whether to go on without choosing: that is
    // the person's own Continue, answered by going on.
    await page.getByRole("button", { name: "Go on without choosing" }).click();
    // What the journey shows when First reading does not end: what the service was asked and how each connection stands.
    const showWhere = async () => {
      const log = await asked();
      const per = (n: number) => log.filter((r) => r.account === n);
      const sources = (await watch(page)).map((w) => `${w.label} ${w.account}: items ${w.items}, older ${JSON.stringify(w.older_read)}, last ${JSON.stringify((w as unknown as { last?: unknown }).last)}`);
      return `requests ${log.length} (1: ${per(1).length}, 2: ${per(2).length}), refused ${log.filter((r) => r.answer === "refused").length}, inside a window ${insidePenalty(log, PENALTY).length}; last ten: ${JSON.stringify(log.slice(-10))}; ${sources.join(" | ")}; ${JSON.stringify((await setup(page)).reading)}`;
    };
    await expect
      .poll(
        async () => {
          const working = main.locator('[data-reading="working"]');
          if (await working.count()) {
            const text = (await working.innerText().catch(() => "")).replace(/\s+/g, " ");
            expect(text).not.toMatch(INTERNAL);
          }
          return await main.getByRole("heading", { level: 2, name: "People" }).count();
        },
        { timeout: 300_000, message: "First reading moves on to People with no click beyond Continue" },
      )
      .toBe(1)
      .catch(async (err: Error) => {
        throw new Error(`${err.message}\n${await showWhere()}`);
      });
    const reading = (await setup(page)).reading;
    expect(reading.sources).toBeGreaterThan(0);

    // 5. People: never empty. It offers people, or says what it is waiting for (with a time when the mail service asked to wait), and then offers.
    const offers = main.locator("[data-people-suggestions]");
    await expect(offers.getByRole("checkbox").or(offers.locator("[data-people-look-state]")).first()).toBeVisible(LOADED);
    const saying = offers.locator("[data-people-look-state]");
    if (await saying.count()) {
      const words = (await saying.first().innerText()).trim();
      expect(words.length).toBeGreaterThan(0);
      if (/waiting for the mail service/.test(words)) expect(words).toMatch(/\d{1,2}:\d{2}/);
    }
    await expect(offers.getByRole("checkbox").first()).toBeVisible({ timeout: 240_000 });
    expect(await offers.innerText()).not.toMatch(INTERNAL);

    // 6. The older read ends by itself, with no click: its line is gone and the inbox looks back as far as the month.
    await expect
      .poll(
        async () => {
          const w = await inbox();
          return !w.older_read && !!w.looked_back_to && w.looked_back_to <= reach;
        },
        { timeout: 300_000, message: "the older read of the first account ends by itself and reaches the month" },
      )
      .toBe(true);
    expect((await inbox()).items).toBeGreaterThan(before.items);

    // 7. What the service was asked, from its own log. The limit was exercised (it refused at least once), and no request for an
    // account fell inside its penalty window.
    const log = await asked();
    const refused = log.filter((r) => r.answer === "refused");
    expect(refused.length, "the limit refused at least once, so the windows below mean something").toBeGreaterThan(0);
    expect(insidePenalty(log, PENALTY), "requests made inside a penalty window").toEqual([]);
    // Fetches stay near the message count: no more mail requests than 1.2 times the messages the first account holds.
    const mail = (account: number) => log.filter((r) => r.account === account && r.endpoint.startsWith("/mail/v1/")).length;
    const held = (await mine()).filter((w) => w.reads?.includes("mail")).reduce((n, w) => n + w.items, 0);
    expect(held).toBeGreaterThan(0);
    expect(mail(1), "mail requests for the first account").toBeLessThanOrEqual(Math.ceil(held * 1.2));
    const numbers = `requests ${log.length} (account 1: ${log.filter((r) => r.account === 1).length}, account 2: ${log.filter((r) => r.account === 2).length}), refused ${refused.length}, mail fetches ${mail(1)} for ${held} messages, ${Math.round((Date.now() - began) / 1000)} s`;
    test.info().annotations.push({ type: "numbers", description: numbers });
    console.log(`two accounts under a limit: ${numbers}`);
    await visit(page);
  });
});
