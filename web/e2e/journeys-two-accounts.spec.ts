// S-0668: a person's path under a real service's limits. Two accounts of the made-up mail service, each with a real-sized mailbox, the
// service refusing an account's every request for a few seconds after a refusal (and longer for each request made inside that time),
// and the person walking setup from its first screen: the first account signed in and two weeks read in full on it, then, while that read
// is busy and the service has refused it, the second account signed in (H5-34: its "Read in full from" choice is on screen within
// seconds and its answer, given at once, is applied when its first read lands), then Continue and nothing else. What the person sees is
// checked (no line said twice on a card or in a message, First reading ends, People offers people, the older read ends by itself), and
// what the service was asked is read from its own log: no request for an account inside its penalty window, and no more fetches than
// messages.
// Names come from the fictional workspace the fake services serve, never written out here.
import { expect, type Locator, type Page } from "@playwright/test";
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
  reading: { state: string; why?: string; stage?: string; sources: number; read: number; found: number };
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
    test.setTimeout(1_500_000);
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

    // 2. The first account, through the service's own page.
    const row = main.locator('[data-service="journey-mail"]');
    /** Signs in the account numbered `n` (from 0) and returns the moment its sign-in was over (the service's page closed). */
    const signIn = async (n: number): Promise<number> => {
      if (n > 0) await main.getByRole("button", { name: /^Connect another account/ }).click();
      const button = n === 0 ? row.getByRole("button", { name: "Sign in to Example mail", exact: true }) : page.getByRole("dialog").getByRole("button", { name: "Add another account to Example mail", exact: true });
      const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
      const closed = popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
      await popup.getByRole("link", { name: addresses[n], exact: true }).click();
      await closed;
      return Date.now();
    };
    const signedIn = async (n: number) => {
      await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
      await expect(page.getByRole("dialog")).toHaveCount(0, LOADED);
      await expect(main.locator("[data-account-row]")).toHaveCount(n + 1, LOADED);
    };
    /** The lines an account's card says, each as its words: none may be said twice (one line per cause). */
    const linesOf = async (card: Locator) => (await card.locator("p.hint").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").trim()).filter(Boolean);
    await signIn(0);
    await signedIn(0);

    // 3. Two weeks in full on the first account: the window and what the service holds in it are asked before anything is read.
    const first = main.locator(`[data-account-row="${addresses[0]}"]`);
    const of = async (address: string) => (await watch(page)).filter((w) => w.account === address);
    const mine = () => of(addresses[0]);
    // With two accounts a connection's name tells them apart, so the inbox is the one that reads mail and is not the sent mail.
    const inboxOf = async (address: string) => (await of(address)).find((w) => w.reads?.includes("mail") && /inbox/i.test(w.label));
    const inbox = async () => {
      const found = await inboxOf(addresses[0]);
      expect(found, `an inbox of ${addresses[0]} among ${JSON.stringify((await watch(page)).map((w) => [w.label, w.account]))}`).toBeTruthy();
      return found!;
    };
    const pick = first.locator("[data-full-read]").getByRole("combobox");
    // The counts come with the first read: the journey waits for it, as a person reading the choices does.
    await expect.poll(async () => (await inboxOf(addresses[0]))?.looked_back_to ?? null, LOADED).not.toBeNull();
    const before = await inbox();
    expect(before.older_read ?? null).toBeNull();
    await expect(pick).toBeVisible(LOADED);
    await choose(pick, "2 weeks");
    await visit(page);
    await first.locator("[data-full-read]").getByRole("button", { name: "Read it" }).click();
    // The account reads its inbox and its sent mail, and every one that was open was answered: what the message and the card say of them is said once.
    const said = page.locator("[data-toast]").filter({ hasText: "older mail" });
    await expect(said.first()).toBeVisible(LOADED);
    const message = (await said.first().innerText()).replace(/\s+/g, " ");
    expect(message.match(/Reading the older mail in the background\./g) ?? [], `the message says it once: ${message}`).toHaveLength(1);
    const firstLines = await linesOf(first);
    expect(new Set(firstLines).size, `no line twice on the first account's card: ${JSON.stringify(firstLines)}`).toBe(firstLines.length);
    // The reach of 2 weeks: the older read is done when the inbox looks back that far (the first read took the last 7 days).
    const reach = new Date(Date.parse(before.looked_back_to + "T00:00:00Z") - 7 * 86_400_000).toISOString().slice(0, 10);

    // 3a. The second account, while the first is busy: its older read is under way and the service has refused it, so the first account
    // is reading or waiting out the service's time. The second account's choice is on screen within seconds of its sign-in all the same.
    await expect
      .poll(async () => (await asked()).some((r) => r.account === 1 && r.answer === "refused") && (await mine()).some((w) => w.older_read), { timeout: 240_000, message: "the first account's older read runs into the service's limit" })
      .toBe(true);
    const second = main.locator(`[data-account-row="${addresses[1]}"]`);
    const pickSecond = second.locator("[data-full-read]").getByRole("combobox");
    // The service is refusing the second account too when it signs in (a busy service, or a mailbox that takes minutes to read): its
    // first read cannot land for some seconds. The choice does not wait for that read.
    expect((await (await fetch(`${FAKE}/__e2e/quota/hold`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ account: 2, seconds: 20 }) })).json()) as { held: boolean }).toEqual({ held: true });
    const at = await signIn(1);
    await expect(pickSecond).toBeVisible({ timeout: 300_000 });
    const waited = (Date.now() - at) / 1000;
    const busy = (await mine()).filter((w) => w.older_read).map((w) => w.older_read?.kind);
    console.log(`second account: "Read in full from" on screen ${waited.toFixed(1)} s after its sign-in, the first account's older reads: ${JSON.stringify(busy)}`);
    test.info().annotations.push({ type: "second-account-choice-seconds", description: waited.toFixed(1) });
    expect(busy.length, "the first account is still reading older mail when the second signs in").toBeGreaterThan(0);
    expect((await inboxOf(addresses[1]))?.looked_back_to ?? null, "the second account's first read has not landed when its choice is up").toBeNull();
    expect(waited, "seconds from the second account's sign-in to its choice on screen").toBeLessThanOrEqual(5);
    await signedIn(1);
    // An answer given at once is kept, and applied when the account's first read lands: its older mail is read with no further press.
    await choose(pickSecond, "2 weeks");
    await second.locator("[data-full-read]").getByRole("button", { name: "Read it" }).click();
    await expect(second.locator("[data-full-read]")).toHaveCount(0, LOADED);
    await visit(page);
    const secondLines = await linesOf(second);
    expect(new Set(secondLines).size, `no line twice on the second account's card: ${JSON.stringify(secondLines)}`).toBe(secondLines.length);
    await expect
      .poll(
        async () => {
          const mail = (await of(addresses[1])).filter((w) => w.reads?.includes("mail") && w.looked_back_to);
          const back = (w: WatchSource) => new Date(Date.parse(w.looked_back_to + "T00:00:00Z")).getTime();
          // Applied: the read of older mail is queued or under way, or it has already reached further back than a first read looks.
          return mail.length > 0 && mail.every((w) => !w.full_read_open) && mail.some((w) => w.older_read != null || back(w) <= Date.parse(reach + "T00:00:00Z"));
        },
        { timeout: 300_000, message: "the second account's answer is applied when its first read lands" },
      )
      .toBe(true);

    // 4. Continue, and nothing after it: First reading ends (waiting lines are shown with a time, never an empty step) and People follows.
    // Both accounts were answered, so Continue asks nothing: no connection of either still has the question open.
    const open = (await watch(page)).filter((w) => w.full_read_open).map((w) => `${w.label} ${w.account}: looked back to ${w.looked_back_to ?? "nothing yet"}, last ${JSON.stringify((w as unknown as { last?: { outcome?: string } }).last?.outcome ?? null)}, older ${JSON.stringify(w.older_read ?? null)}`);
    expect(open, "a question still open after both accounts were answered").toEqual([]);
    const continued = Date.now();
    await main.getByRole("button", { name: "Continue" }).click();
    // What the journey shows when First reading does not end: what the service was asked and how each connection stands.
    const stages: [string, number][] = [];
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
          const stage = (await setup(page)).reading?.stage;
          if (stage && stage !== stages[stages.length - 1]?.[0]) stages.push([stage, Math.round((Date.now() - continued) / 1000)]);
          return await main.getByRole("heading", { level: 2, name: "People" }).count();
        },
        // Both accounts' choices were also their go, so the mail taken in is being worked while this step waits: on a busy machine
        // that is several minutes of the stand-in's answers, and the step ends when they are in.
        { timeout: 180_000, message: "First reading moves on to People with no click beyond Continue" },
      )
      .toBe(1)
      .catch(async (err: Error) => {
        throw new Error(`${err.message}\n${await showWhere()}`);
      });
    const readingSeconds = Math.round((Date.now() - continued) / 1000);
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
    const offersSeconds = Math.round((Date.now() - continued) / 1000);
    // H5-40: the times a person waits, whatever the older mail costs; the older read's work carries on in the background.
    console.log(`H5-40 times: Continue to First reading done ${readingSeconds} s, Continue to People offers ${offersSeconds} s; First reading stages (seconds from Continue): ${JSON.stringify(stages)}`);
    expect(offersSeconds, "People shows the assistant's offers within 3 minutes of Continue").toBeLessThanOrEqual(180);
    expect(await offers.innerText()).not.toMatch(INTERNAL);

    // 6. The older read ends by itself, with no click: its line is gone and the inbox looks back as far as the two weeks.
    await expect
      .poll(
        async () => {
          const w = await inbox();
          return !w.older_read && !!w.looked_back_to && w.looked_back_to <= reach;
        },
        { timeout: 300_000, message: "the older read of the first account ends by itself and reaches the 2 weeks" },
      )
      .toBe(true);
    expect((await inbox()).items).toBeGreaterThan(before.items);

    // 6a. One step: each account's reading choice was its only ask (the second account's was given before its first read), so it was
    // also the go for what the first window held and for what the two weeks bring. Today has no "Take in" line, for either account.
    interface Line {
      kind: string;
      source?: string | null;
      subject?: string | null;
      count?: number | null;
      parts?: Line[];
      items?: Line[];
    }
    const flat = (lines: Line[]): Line[] => lines.flatMap((l) => [l, ...flat(l.parts ?? []), ...flat(l.items ?? [])]);
    const takeIn = async () => flat((await (await page.request.get("api/today/queue", { headers: auth(info) })).json()) as Line[]).filter((l) => l.kind === "intake_go").map((l) => `${l.subject}: ${l.count}`);
    // A slice of older mail is taken in and queued in two writes, so the look is made again for a moment before it counts.
    await expect.poll(takeIn, { timeout: 30_000, message: "no Take in line is left on Today for either account" }).toEqual([]);

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
