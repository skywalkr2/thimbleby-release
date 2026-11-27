// S-0643: setup walked on a real-sized mailbox, where a small made-up mailbox would hide what goes wrong: a full read of many
// messages that the service slows down partway, a sign-out and sign-in again while the rest waits, and the reading step and People
// behind them. Here the made-up mail service holds hundreds of
// messages over two months (inbox, sent, archive, deleted), slows a read of older mail down partway, and the person signs out of the
// account in the Mail step and signs in again. A workspace made as a person makes it, with the mail add-on on and a job beside
// Personal, is walked from its first screen to People, and the rest of the read finishes without a click.
// Names come from the fictional workspace the fake services serve, never written out here.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choose } from "./choose";
import { collectProblems, fakeAddress, turnOnAndGoOn, pressStart, visit, type Info } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_RE4_FAKE_PORT", 8601);
const LOADED = { timeout: 60_000 };
const JOB = "Example Employer";
/** How long the service asks to wait before the next page, in seconds: long enough for the person to sign out and in meanwhile. */
const RETRY_AFTER = 40;
const BIG_PAGE = 50;
const problems: string[] = [];
/** What a real low-cost model answered when given the look's packet for this mailbox (H5-36), kept word for word: the look here is
 * answered with it, never with the stand-in's rule that offers every line with enough messages. It is one op by itself, with no
 * list around it, which is the shape the model gave and the one that once left People empty. */
const LOOK_ANSWER = JSON.parse(readFileSync(fileURLToPath(new URL("./fixtures/people-look-real-answer.json", import.meta.url)), "utf8")) as {
  op: string;
  people: Array<{ address: string; name: string; why: string }>;
};
const OFFERED = LOOK_ANSWER.people;
/** The words only the look's packet holds: the list of who the person deals with. */
const LOOK_PACKET = '<untrusted source="contact-tally">';

/** Words that belong to the app's insides or to the service, never to the person. */
const INTERNAL = /ConnectorError|throttled|TooManyRequests|ServiceBusy|HTTP 429|\b429\b|Retry-After|watch_run|older_read|traceback|undefined|\[object/i;

/** What a failed read that kept nothing says to the person. */
const NOTHING_KEPT = /didn't work|is busy|try again/i;

interface WatchSource {
  id: string;
  account?: string;
  account_state?: string;
  looked_back_to?: string | null;
  full_read_open?: boolean | null;
  label: string;
  items: number;
  older_read?: { taken: number; kind: string; at?: string | null; gave_up: boolean } | null;
  last?: { outcome?: string; error?: string } | null;
}
interface SetupSeen {
  steps: Array<{ id: string; done: boolean }>;
  reading: { state: string; why?: string; stage?: string; sources: number; read: number; found: number };
  people_by_hand: boolean;
}
interface BigMailbox {
  folders: Record<string, number>;
  older_asked: Array<{ folder: string; since: string; before: string; answer: string; purpose: string }>;
  slowed: number;
  armed: boolean;
}

const auth = (info: Info) => ({ Authorization: `Bearer ${info.token}` });

test.describe.serial("journey: real-sized mailbox", () => {
  // The journey changes its server's state (a fresh workspace, signed-in accounts, a restart), and a re-run would start from
  // that used server and fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its failure as it is.
  test.describe.configure({ retries: 0 });
  test.use({ actionTimeout: 30_000 });
  let info: Info;
  let address: string;

  test.beforeAll(async () => {
    info = (await (await fetch(`${FAKE}/__e2e/info`)).json()) as Info;
    address = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts[0].address;
  });

  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  const setup = async (page: Page) => (await (await page.request.get("api/setup", { headers: auth(info) })).json()) as SetupSeen;
  const watch = async (page: Page) => (await (await page.request.get("api/watch", { headers: auth(info) })).json()) as WatchSource[];
  const mailbox = async () => (await (await fetch(`${FAKE}/__e2e/big-mailbox`)).json()) as BigMailbox;

  test("S-0643. a real-sized mailbox, a rate limit partway through a full read, and a sign-out and sign-in again walk setup to People with offers", async ({ page }) => {
    test.setTimeout(420_000);
    collectProblems(page, problems);
    // The mailbox is real-sized: several hundred messages over two months, in four folders.
    const held = await mailbox();
    expect(Object.keys(held.folders).sort()).toEqual(["Archive", "Deleted", "inbox", "sent"]);
    expect(Object.values(held.folders).reduce((n, c) => n + c, 0)).toBeGreaterThanOrEqual(400);

    // The look at who the person deals with gets a real model's answer for this mailbox.
    expect(LOOK_ANSWER.op).toBe("person.offer");
    expect(OFFERED.length).toBeGreaterThan(0);
    const scripted = await fetch(`${FAKE}/__e2e/script`, { method: "POST", body: JSON.stringify({ when: LOOK_PACKET, answer: LOOK_ANSWER }) });
    expect(scripted.ok).toBe(true);

    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
    await pressStart(page);
    const main = page.locator("main#main");

    // 1. You, and What it's for: a job beside Personal, so the Mail step has sides to ask about.
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible(LOADED);
    await main.getByLabel("Your full name").fill(info.people[0]);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
    await main.getByRole("checkbox", { name: "A job" }).check();
    await main.getByRole("textbox", { name: "What is your employer called?" }).fill(JOB);
    await main.getByRole("button", { name: "Continue" }).click();

    // 2. The AI step: the fake service, with one explicit yes, and the assistant turned on.
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

    // 3. Mail: connect the account.
    const row = main.locator('[data-service="journey-mail"]');
    const signIn = async () => {
      const button = row.getByRole("button", { name: "Sign in to Example mail", exact: true });
      const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
      // One person signs in, so the service's page sends the window straight back (it names no accounts to choose from).
      await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
    };
    await signIn();
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
    const account = main.locator(`[data-account-row="${address}"]`);
    await expect(account).toBeVisible(LOADED);
    // 4. What it is for: with a job beside Personal, the account is asked, and this one is Personal's.
    const question = account.getByRole("group", { name: "What is this account for?" });
    await expect(question.getByRole("radio")).toHaveCount(3);
    await question.getByRole("radio", { name: "Personal" }).check();
    await expect(question.getByRole("radio", { name: "Personal" })).toBeChecked();
    await visit(page);

    // 5. A full read of 2 weeks, with the service slowing a later page of older mail down. The window the read covers, and what the
    // service holds in it, are asked before anything is read.
    const inbox = async () => (await watch(page)).find((w) => w.label === "Your inbox")!;
    const first = await inbox();
    expect(first.older_read ?? null).toBeNull();
    const since = new Date(Date.parse(first.looked_back_to + "T00:00:00Z") - 7 * 86_400_000).toISOString().slice(0, 10);
    const inWindow = ((await (await fetch(`${FAKE}/__e2e/big-mailbox?folder=inbox&since=${since}&before=${first.looked_back_to}`)).json()) as { window: number }).window;
    // More than one page of mail is waiting there, or the rate limit would have nothing to land on.
    expect(inWindow).toBeGreaterThan(BIG_PAGE);
    const fullRead = account.locator("[data-full-read]");
    const pick = fullRead.getByRole("combobox");
    await expect(pick).toBeVisible(LOADED);
    await choose(pick, "2 weeks");
    // Having the choice open asks the service for each count once per reach and source, however often the window is focused or
    // anything changes (S-0644): focus it a few times, let the screen read again, then count what the service was asked.
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => {
        window.dispatchEvent(new Event("focus"));
        document.dispatchEvent(new Event("visibilitychange"));
      });
      // A read of the source is a change the screen is told of, as the worker's own reads are.
      expect((await page.request.post(`api/watch/${first.id}/read`, { headers: auth(info) })).ok()).toBe(true);
      await expect(async () => expect((await watch(page)).find((w) => w.id === first.id)?.last).toBeTruthy()).toPass(LOADED);
    }
    await visit(page);
    const reaches = 2; // watch.full_read_choices of the fresh workspace: 7 and 14 days
    const open = (await watch(page)).filter((w) => w.full_read_open).length;
    const counts = (await mailbox()).older_asked.filter((a) => a.purpose === "count").length;
    expect(open).toBeGreaterThan(0);
    expect(counts, "count requests while the Mail step is open").toBeLessThanOrEqual(reaches * open);
    await fetch(`${FAKE}/__e2e/slow-down`, { method: "POST", body: JSON.stringify({ ends_before: first.looked_back_to, retry_after: RETRY_AFTER }) });
    await fullRead.getByRole("button", { name: "Read it" }).click();
    // H4-06: one press answers every source of the account that is open (the inbox and the sent mail), the choice then leaves, and a read that
    // goes through never shows a failure.
    await expect
      .poll(async () => (await watch(page)).filter((w) => w.account === address && w.full_read_open).length, { timeout: 180_000 })
      .toBe(0);
    await expect(fullRead).toHaveCount(0, { timeout: 180_000 });
    await expect(page.getByRole("region", { name: "Notifications" })).not.toContainText("That didn't work");
    // Read it returned at once: the line says the older mail is being read in the background, in the person's words, with none of the
    // service's own words and no failure.
    const toasts = page.getByRole("region", { name: "Notifications" });
    await expect(toasts).toContainText("Reading the older mail in the background.", LOADED);
    const said = await toasts.innerText();
    expect(said).not.toMatch(INTERNAL);
    expect(said).not.toMatch(NOTHING_KEPT);
    // The worker reads it a page at a time: what a page held was kept, and when the service slows a later page down the rest waits for
    // its time, which the account's row says (a wait is never a failure).
    await expect.poll(async () => (await inbox()).older_read?.kind, LOADED).toBe("throttled");
    const stopped = await inbox();
    expect(stopped.older_read!.taken).toBeGreaterThan(0);
    expect(stopped.older_read!.gave_up).toBe(false);
    expect(stopped.items - first.items).toBe(stopped.older_read!.taken);
    // The service's wait is RETRY_AFTER seconds, a short one, which the row says in words and not as a time of day (H5-07).
    await expect(account.locator(`[data-older-read="${first.id}"]`)).toContainText("continues in a minute or so", LOADED);
    expect(await account.locator(`[data-older-read="${first.id}"]`).innerText()).not.toMatch(INTERNAL);
    expect((await mailbox()).slowed).toBe(1);

    // 6. Signing out of the account, in the Mail step, while the rest of the read waits: the step is back at its start, and nothing
    // that is signed out is counted as read or waited for.
    await main.getByRole("button", { name: `Sign out ${address}` }).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(row.getByRole("button", { name: "Sign in to Example mail", exact: true })).toBeVisible(LOADED);
    await expect(main.locator("[data-mail-result]")).toHaveCount(0);
    await expect(main.locator("[data-account-row]")).toHaveCount(0);
    await expect(main.getByText("Now reading")).toHaveCount(0);
    await expect(async () => {
      const view = await setup(page);
      expect(view.steps.find((st) => st.id === "mail")?.done).toBe(false);
      expect(view.reading).toMatchObject({ state: "none", why: "no_mail" });
    }).toPass(LOADED);
    await visit(page);

    // 7. Signing in again: the account is connected again, and what it is for is still answered.
    await signIn();
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
    await expect(account).toBeVisible(LOADED);
    await expect(question.getByRole("radio", { name: "Personal" })).toBeChecked();
    await visit(page);

    // 8. The rest of the read finishes by itself, from where it stopped: the worker carries it on when its time comes, with no click.
    await expect
      .poll(async () => {
        const w = await inbox();
        return w.older_read ? "waiting" : w.items - first.items;
      }, { timeout: 240_000, message: "the rest of the full read carries on by itself" })
      .toBe(inWindow);
    expect((await mailbox()).older_asked.filter((a) => a.answer === "slow down")).toHaveLength(1);
    // The two weeks' answer was the account's, so its sent mail reads two weeks too, in its own slices after the inbox's: every older read of
    // the account is over before the count the reading step shows is compared with the final one.
    await expect
      .poll(async () => (await watch(page)).filter((w) => w.older_read).length, { timeout: 240_000, message: "every older read of the account ends" })
      .toBe(0);

    // 9. The reading step counts the sources that are read now, and what it counts matches what was read.
    const sources = (await watch(page)).filter((w) => w.account_state === "signed_in");
    expect(sources.map((w) => w.label).sort()).toEqual(["Your calendar", "Your inbox", "Your sent mail"]);
    await main.getByRole("button", { name: "Continue" }).click();
    const shown: string[] = [];
    await expect
      .poll(
        async () => {
          const working = main.locator('[data-reading="working"]');
          if (await working.count()) {
            const text = (await working.innerText().catch(() => "")).replace(/\s+/g, " ");
            shown.push(text);
            const of = /(\d+) of your (\d+) mailboxes and calendars are read/.exec(text);
            if (of) expect(Number(of[2])).toBe(sources.length);
            expect(text).not.toMatch(INTERNAL);
          }
          return await main.getByRole("heading", { level: 2, name: "People" }).count();
        },
        { timeout: 240_000, message: "the first reading moves on to People" },
      )
      .toBe(1);
    const reading = (await setup(page)).reading;
    expect(reading).toMatchObject({ sources: sources.length, read: sources.length });
    // Every item the full read took in is counted, and the count the screen showed while it worked is the one the setup view holds
    // (every older read of the account was over before Continue, so it no longer changes).
    expect(reading.found).toBeGreaterThanOrEqual(inWindow);
    for (const text of shown) {
      const found = /(\d+) items? taken in so far/.exec(text);
      if (found) expect(Number(found[1])).toBe(reading.found);
    }
    expect((await inbox()).items).toBe(first.items + inWindow);

    // 10. People: the step is never empty (S-0667): it shows offers, or says what it waits for, with its time when it waits for the
    // mail service; then the assistant's offers are there, from the mail read.
    const offers = main.locator("[data-people-suggestions]");
    await expect(offers.getByRole("checkbox").or(offers.locator("[data-people-look-state]")).first()).toBeVisible(LOADED);
    const saying = offers.locator("[data-people-look-state]");
    if (await saying.count()) {
      const words = (await saying.first().innerText()).trim();
      expect(words.length).toBeGreaterThan(0);
      if (/waiting for the mail service/.test(words)) expect(words).toMatch(/\d{1,2}:\d{2}/);
    }
    await expect(offers.getByRole("checkbox").first()).toBeVisible({ timeout: 120_000 });
    expect(await offers.innerText()).not.toMatch(INTERNAL);
    // The people shown are the ones the model's answer offered, each by name, and nobody else.
    const names = await offers.getByRole("checkbox").evaluateAll((boxes) => boxes.map((b) => b.closest("label")?.textContent ?? ""));
    expect(names.length).toBeGreaterThan(0);
    // Each is shown with the reason the model gave, in its words: the offers are its answer, not the stand-in's rule.
    for (const name of names) expect(OFFERED.some((p) => name.includes(p.name) && name.includes(p.why))).toBe(true);
    await visit(page);
    // Nothing was refused, kept nothing, or stopped in setup on the way.
    expect(await main.innerText()).not.toMatch(NOTHING_KEPT);
  });
});
