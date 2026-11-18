// Batch RE3, S-0642 and S-0641: setup asks what each connected account is for, and Handled for you shows what was set aside. A workspace
// made as a person makes it, with the mail add-on on and a job beside Personal, beside fake services that play two people, each with a
// mailing to many that the app sets aside and whose link names its account. Setup is walked from its first screen; Handled for you and
// Connections are then read on the same workspace.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { collectProblems, fakeAddress, leaveOut, pickFolder, pressStart, startOnToday, turnOnAndGoOn, type Info } from "./journey-helpers";
import { pickSide } from "./side-pick";

const FAKE = fakeAddress("JOURNEY_RE3_FAKE_PORT", 8713);
const LOADED = { timeout: 60_000 };
const JOB = "Example Employer";
/** Where the made-up mail service says a message opens; the address is built, never written out whole. */
const MAIL = "https" + "://mail.example.com/mail";
const problems: string[] = [];

const auth = (info: Info) => ({ Authorization: `Bearer ${info.token}` });

test.describe.serial("review RE3: what each account is for, and what Handled for you shows", () => {
  // These steps change their server's state (setup walked, accounts signed in or out, records added), and a re-run would start
  // from that used server and fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its
  // failure as it is (S-0560).
  test.describe.configure({ retries: 0 });
  test.use({ actionTimeout: 30_000 });
  let info: Info;
  let addresses: string[];

  test.beforeAll(async () => {
    info = (await (await fetch(`${FAKE}/__e2e/info`)).json()) as Info;
    addresses = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts.map((a) => a.address);
  });

  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  const handled = async (page: Page, side?: string) => {
    const query = side ? `&side=${encodeURIComponent(side)}` : "";
    const view = (await (await page.request.get(`api/handled?tab=set_aside${query}`, { headers: auth(info) })).json()) as {
      counts: { set_aside: number };
      groups: Array<{ items: Array<{ title: string; side: string | null; link: string | null; preview: string[] }> }>;
    };
    // Only the mailings this scenario seeds: the first account's inbox holds the demo's other set-aside mail too.
    return { counts: view.counts.set_aside, rows: view.groups.flatMap((g) => g.items).filter((r) => r.title.startsWith("Offer for account ")) };
  };

  test("S-0642. with a job beside Personal, each connected account is asked what it is for as a list, and leaving one for later is only through the confirmed choice", async ({ page }) => {
    test.setTimeout(300_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
    await pressStart(page);
    const main = page.locator("main#main");
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible(LOADED);
    await main.getByLabel("Your full name").fill(info.people[0]);
    await main.getByRole("button", { name: "Continue" }).click();
    // What it's for: a job beside the person's own life, so the Mail step has sides to ask about.
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
    await main.getByRole("checkbox", { name: "A job" }).check();
    await main.getByRole("textbox", { name: "What is your employer called?" }).fill(JOB);
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

    const row = main.locator('[data-service="journey-mail"]');
    for (const [n, address] of addresses.entries()) {
      if (n > 0) await main.getByRole("button", { name: /^Connect another account/ }).click();
      const button = n === 0 ? row.getByRole("button", { name: "Sign in to Example mail", exact: true }) : page.getByRole("dialog").getByRole("button", { name: "Add another account to Example mail", exact: true });
      const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
      await popup.getByRole("link", { name: address, exact: true }).click();
      await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
      await expect(page.getByRole("dialog")).toHaveCount(0, LOADED);
      await expect(main.locator("[data-account-row]")).toHaveCount(n + 1, LOADED);
    }

    // Each account's row asks the question as a list to pick from (the sides, and Both), never a link or a box to type in; nothing says
    // "For no side yet" or "Tick every one it serves".
    const first = main.locator(`[data-account-row="${addresses[0]}"]`);
    const second = main.locator(`[data-account-row="${addresses[1]}"]`);
    for (const account of [first, second]) {
      const question = account.getByRole("group", { name: "What is this account for?" });
      await expect(question).toBeVisible(LOADED);
      await expect(question.getByRole("radio")).toHaveCount(3);
      await expect(question.getByRole("radio", { name: "Personal" })).toBeVisible();
      await expect(question.getByRole("radio", { name: JOB })).toBeVisible();
      await expect(question.getByRole("radio", { name: "Both" })).toBeVisible();
      await expect(account.getByRole("textbox")).toHaveCount(0);
    }
    await expect(main.getByText(/Tick every one it serves|no side yet/)).toHaveCount(0);
    // Without an answer Continue waits and says why.
    const next = main.getByRole("button", { name: "Continue" });
    await expect(next).toBeDisabled();
    // The first account is for Personal: saved as the sides of its sources at once.
    await first.getByRole("radio", { name: "Personal" }).check();
    await expect(first.getByRole("radio", { name: "Personal" })).toBeChecked();
    const held = async () => {
      const read = (await (await page.request.get("api/settings", { headers: auth(info) })).json()) as { items: Array<{ key: string; value: unknown }> };
      return (read.items.find((i) => i.key === "watch.sources")!.value as Array<{ label: string; sides?: string[] }>).filter((s) => s.label.endsWith(addresses[0]));
    };
    await expect.poll(async () => (await held()).every((s) => (s.sides ?? []).length === 1), { timeout: 30_000 }).toBe(true);
    // The second is left for later, and only through the confirmed choice.
    await expect(next).toBeDisabled();
    await main.getByRole("button", { name: "I'll say later" }).click();
    const sure = page.getByRole("dialog", { name: "Leave these accounts not assigned?" });
    await sure.getByRole("button", { name: "Keep this step" }).click();
    await expect(next).toBeDisabled();
    await main.getByRole("button", { name: "I'll say later" }).click();
    await page.getByRole("dialog", { name: "Leave these accounts not assigned?" }).getByRole("button", { name: "Leave it out" }).click();
    await expect(second.getByText("Not assigned")).toBeVisible();
    await expect(next).toBeEnabled();
    await next.click();
    // The rest of setup, as the other journeys walk it.
    await expect(main.getByRole("heading", { level: 2, name: "People" })).toBeVisible({ timeout: 120_000 });
    await leaveOut(page, main);
    await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible(LOADED);
    await pickFolder(page, main, ["offsite"]);
    await expect(main.getByText(/That folder works/)).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Continue" }).click();
    const stale = main.getByRole("alert").filter({ hasText: "The settings changed since you opened them" });
    await expect(main.getByRole("heading", { level: 2, name: "Where things stand" }).or(stale)).toBeVisible(LOADED);
    if (await stale.isVisible()) {
      await page.reload();
      await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible(LOADED);
      if ((await main.getByLabel("Folder", { exact: true }).inputValue()) === "") {
        await pickFolder(page, main, ["offsite"]);
        await expect(main.getByText(/That folder works/)).toBeVisible(LOADED);
      }
      await main.getByRole("button", { name: "Continue" }).click();
    }
    await expect(main.getByRole("heading", { level: 2, name: "Where things stand" })).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Go to Today" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
    // The first Start is pressed on Today, so the reading of both accounts' mail goes on.
    await startOnToday(page);
  });

  test("S-0641. Handled for you previews each set-aside message, shows it whole, opens it by the source's own link, and counts an unassigned account's mail once", async ({ page }) => {
    test.setTimeout(240_000);
    collectProblems(page, problems);
    // Both accounts' mailings are set aside once the first reading has run.
    await expect
      .poll(async () => (await handled(page)).rows.length, { timeout: 150_000 })
      .toBe(2)
      .catch(async (err) => {
        const all = (await (await page.request.get("api/handled?tab=set_aside", { headers: auth(info) })).json()) as { groups: Array<{ items: Array<{ title: string }> }> };
        const changes = (await (await page.request.get("api/changes", { headers: auth(info) })).json()) as Array<{ id: string; state: string; waiting: string | null }>;
        const watch = (await (await page.request.get("api/watch", { headers: auth(info) })).json()) as Array<{ label: string; items: number; last?: { outcome?: string; error?: string } | null }>;
        const rows = (await handled(page)).rows.map((r) => r.title);
        throw new Error(`${err}\nall set aside: ${JSON.stringify(all.groups.flatMap((g) => g.items.map((i) => i.title)))}\nchanges: ${JSON.stringify(changes.map((c) => [c.id, c.state, c.waiting]))}\nhandled: ${JSON.stringify(rows)}\nsources: ${JSON.stringify(watch.map((w) => [w.label, w.items, w.last?.outcome, w.last?.error]))}`);
      });
    const sides = ((await (await page.request.get("api/setup/business", { headers: auth(info) })).json()) as { personal: string; sides: Array<{ project: string }> });
    const job = sides.sides[0].project;
    // Counted once: the first account's mailing is Personal's, the second's is not assigned, and neither is under every side.
    expect((await handled(page, sides.personal)).rows.map((r) => r.title)).toEqual(["Offer for account 1"]);
    expect((await handled(page, job)).rows).toHaveLength(0);
    expect((await handled(page, "unassigned")).rows.map((r) => r.title)).toEqual(["Offer for account 2"]);
    const everyone = await handled(page);
    expect(everyone.rows.find((r) => r.title === "Offer for account 2")!.side).toBe("unassigned");
    // The link carried is the source's own, unchanged, and names its account.
    const links = Object.fromEntries(everyone.rows.map((r) => [r.title, r.link]));
    expect(links["Offer for account 1"]).toBe(`${MAIL}/u/0/#inbox/a0-promo`);
    expect(links["Offer for account 2"]).toBe(`${MAIL}/u/1/#inbox/a1-promo`);

    // On the screen: the side filter says Not assigned, and each choice lists its own mailing and no other.
    await page.addInitScript(() => {
      (window as unknown as { __opened: unknown[][] }).__opened = [];
      window.open = ((...args: unknown[]) => ((window as unknown as { __opened: unknown[][] }).__opened.push(args), null)) as typeof window.open;
    });
    await page.goto(`?token=${info.token}#work/handled`);
    await expect(page.getByRole("heading", { level: 1, name: "Handled for you" })).toBeVisible(LOADED);
    const list = page.locator("[data-handled]");
    await expect(list.getByText("Offer for account 1")).toBeVisible(LOADED);
    await expect(list.getByText("Offer for account 2")).toBeVisible();
    await pickSide(page, "Not assigned");
    await expect(list.getByText("Offer for account 2")).toBeVisible();
    await expect(list.getByText("Offer for account 1")).toHaveCount(0);
    await pickSide(page, "Personal");
    await expect(list.getByText("Offer for account 1")).toBeVisible();
    await expect(list.getByText("Offer for account 2")).toHaveCount(0);
    await pickSide(page, JOB);
    await expect(list.getByText(/Offer for account/)).toHaveCount(0);
    await pickSide(page, "All");
    await expect(list.getByText("Offer for account 1")).toBeVisible();
    await expect(list.getByText("Offer for account 2")).toBeVisible();

    // A row: two or three lines of the message as text, and Show the message opens it whole.
    const rowTwo = list.getByRole("listitem").filter({ hasText: "Offer for account 2" });
    const preview = rowTwo.getByRole("group", { name: "The start of the message" });
    await expect(preview).toContainText("Half price at the shop this week, sent to account 2.");
    await expect(preview.locator("p")).toHaveCount(3);
    await rowTwo.getByRole("button", { name: "Show the message: Offer for account 2" }).click();
    const whole = rowTwo.getByRole("region", { name: "Offer for account 2" });
    await expect(whole).toContainText("A third line of the offer.", LOADED);
    await rowTwo.getByRole("button", { name: "Hide the message: Offer for account 2" }).click();
    await expect(whole).toHaveCount(0);
    // Go to mail opens the link the source gave for the message in the account it names, not the browser's first mail account.
    await rowTwo.getByRole("button", { name: "More actions for Offer for account 2" }).click();
    await page.getByRole("menuitem", { name: "Open the message" }).click();
    // The menu closes first, then the action runs.
    await expect
      .poll(() => page.evaluate(() => (window as unknown as { __opened: unknown[][] }).__opened), { timeout: 10_000 })
      .toEqual([[`${MAIL}/u/1/#inbox/a1-promo`, "_blank", "noopener,noreferrer"]]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);

    // A side said later moves the mail already read: Connections gives the second account its side, and with no new read the
    // mailing counts under it, and is no longer not assigned.
    await page.goto(`?token=${info.token}#settings/connections`);
    const connections = page.getByRole("list", { name: "Connections", exact: true }).first();
    const inbox = connections.getByRole("listitem", { name: `Your inbox, ${addresses[1]}` });
    await expect(inbox).toBeVisible(LOADED);
    await inbox.getByRole("button", { name: `More actions for Your inbox, ${addresses[1]}` }).click();
    await page.getByRole("menuitem", { name: "Change" }).click();
    const group = page.getByRole("group", { name: `Your inbox, ${addresses[1]}: who is it for?` });
    await expect(group).toBeVisible(LOADED);
    await group.getByRole("checkbox", { name: JOB }).check();
    await expect.poll(async () => (await handled(page, job)).rows.map((r) => r.title), { timeout: 30_000 }).toEqual(["Offer for account 2"]);
    expect((await handled(page, "unassigned")).rows).toHaveLength(0);
    expect((await handled(page, sides.personal)).rows.map((r) => r.title)).toEqual(["Offer for account 1"]);

    // H4-03: an account that serves two sides shows its mail under each of them and under no side it does not serve.
    await group.getByRole("checkbox", { name: "Personal" }).check();
    await expect
      .poll(async () => (await handled(page, sides.personal)).rows.map((r) => r.title).sort(), { timeout: 30_000 })
      .toEqual(["Offer for account 1", "Offer for account 2"]);
    expect((await handled(page, job)).rows.map((r) => r.title)).toEqual(["Offer for account 2"]);
    expect((await handled(page, "unassigned")).rows).toHaveLength(0);
    expect((await handled(page, "PRJ-no-such-side")).rows).toHaveLength(0);
    await page.goto(`?token=${info.token}#work/handled`);
    const shown = page.locator("[data-handled]");
    await expect(shown.getByText("Offer for account 2")).toBeVisible(LOADED);
    await pickSide(page, JOB);
    await expect(shown.getByText("Offer for account 2")).toBeVisible();
    await expect(shown.getByText("Offer for account 1")).toHaveCount(0);
    await pickSide(page, "Personal");
    await expect(shown.getByText("Offer for account 1")).toBeVisible();
    await expect(shown.getByText("Offer for account 2")).toBeVisible();
  });
});
