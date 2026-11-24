// A person with several accounts and sides (design 6.32, 7.7, 7.9; re-sweep X77 to X82, X84, X45): three accounts of one mail
// and calendar service are signed in through the service's own page, one at a time, then read; the screens tell them apart and
// tell each one's state from its own. A workspace made by the init command with no template, started by the serve command, with
// the mail add-on on, and the fake services (tests/fake_services.py) playing three people (`--accounts 3`): each with an inbox
// and a calendar of their own, one invitation and one thread in the first two, and one calendar entry in the first two that
// overlap. /__e2e/failing makes one account fail afterwards. Addresses come from the fake services, never written out here.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choicesOf, choose } from "./choose";
import { collectProblems, fakeAddress, pressStart, showSteps, type Info, toToday } from "./journey-helpers";
import { pickSide, sideFilter } from "./side-pick";

const FAKE = `http://127.0.0.1:${process.env.JOURNEY_ACCOUNTS_FAKE_PORT ?? 8769}`;
void fakeAddress;

const LOADED = { timeout: 60_000 };
let info: Info;
let addresses: string[];
const problems: string[] = [];

// The Schedule shortens a calendar's name to the part before the "@" when every calendar shares one domain.
// Three calendars with the same name are told apart by a number, never by any part of an address (S3).
const CALENDAR_NAMES = ["Your calendar", "Your calendar (2)", "Your calendar (3)"];

const go = (page: Page, hash: string) =>
  page.evaluate((to) => {
    window.location.hash = to;
  }, hash);

async function signIn(page: Page, address: string, first: boolean) {
  const section = page.locator("section", { has: page.locator("#sign-ins-title") }).first();
  const card = page.getByRole("region", { name: address, exact: true });
  const button = first ? section.getByRole("button", { name: "Sign in to Example mail", exact: true }) : section.getByRole("button", { name: "Add another account to Example mail", exact: true });
  const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
  // The service's own page asks which account; the made-up one lists each address as a link.
  await popup.getByRole("link", { name: address, exact: true }).click();
  await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
  // The account is a card of its own once it is signed in.
  await expect(card).toBeVisible(LOADED);
}

const connections = (page: Page) => page.getByRole("list", { name: "Connections", exact: true }).first();
/** One account's card, by its address. */
const card = (page: Page, address: string) => page.locator(`[data-connection-card="${address}"]`);

test.describe.serial("several accounts", () => {
  // These steps change their server's state (setup walked, accounts signed in or out, records added), and a re-run would start
  // from that used server and fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its
  // failure as it is (S-0560).
  test.describe.configure({ retries: 0 });
  test.beforeAll(async () => {
    info = await (await fetch(`${FAKE}/__e2e/info`)).json();
    addresses = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts.map((a) => a.address);
    expect(addresses).toHaveLength(3);
  });
  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  test("X79. three accounts signed in: each connection is named by its account, never three identical Your inbox", async ({ page }) => {
    test.setTimeout(240_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible(LOADED);
    if (await page.locator("[data-walkthrough]").count()) await toToday(page);
    await go(page, "settings/connections");
    await expect(page.getByRole("heading", { level: 2, name: "Connections" })).toBeVisible(LOADED);
    for (const [n, address] of addresses.entries()) await signIn(page, address, n === 0);
    // Six connections, each named by its account; none of them is just "Your inbox".
    for (const address of addresses) {
      await expect(connections(page).getByRole("listitem", { name: `Your inbox, ${address}` })).toBeVisible(LOADED);
      await expect(connections(page).getByRole("listitem", { name: `Your calendar, ${address}` })).toBeVisible(LOADED);
    }
    await expect(connections(page).getByRole("listitem", { name: "Your inbox", exact: true })).toHaveCount(0);
    // Every row is read, and every account is asked for no sign-in while all are well.
    for (const address of addresses) {
      await expect(connections(page).getByRole("listitem", { name: `Your inbox, ${address}` })).toContainText("Read", LOADED);
    }
    // One card for each account address, each holding that account's inbox and calendar, and none asking to sign in.
    await expect(page.locator("[data-connection-card]")).toHaveCount(3);
    for (const address of addresses) {
      await expect(card(page, address).getByRole("heading", { name: address, exact: true })).toBeVisible();
      await expect(card(page, address).getByRole("listitem")).toHaveCount(2);
      await expect(card(page, address)).toContainText("Connected", LOADED);
    }
    await expect(page.locator("[data-connection-card][data-need]")).toHaveCount(0);
    await expect(page.locator("table")).toHaveCount(0);
    await expect(page.locator("[data-status]").first()).not.toHaveAttribute("data-status", "connection_failed");
  });

  test("S-0354 (X57). each healthy account's card on Connections says Signed in as its address with a Sign out beside it, which asks before it signs out and keeps the account on Keep signed in", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    for (const address of addresses) {
      const one = card(page, address);
      await expect(one).toBeVisible(LOADED);
      // The line the reviewer asked for: who is signed in, and Sign out, on the card itself and not in its menu.
      const line = one.locator("[data-signed-in-as]");
      await expect(line).toContainText(`Signed in as ${address}`);
      await expect(line.getByRole("button", { name: "Sign out", exact: false })).toBeVisible();
    }
    // Sign out asks first, and Cancel signs no one out.
    const first = card(page, addresses[0]);
    await first.locator("[data-signed-in-as]").getByRole("button", { name: /Sign out/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Keep signed in" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(first.locator("[data-signed-in-as]")).toBeVisible();
    // The same line holds at a phone width without sideways scroll.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(first.locator("[data-signed-in-as]")).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("X78 and X45. the same invitation is one entry on the Schedule naming both calendars; the legend tells the calendars apart and hides one", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`?token=${info.token}`);
    await go(page, "schedule");
    await expect(page.getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible(LOADED);
    // Month shows every day of the invitation once: Quarterly review appears one time, not once for each account.
    await page.getByRole("tab", { name: "Month" }).click();
    const review = page.getByRole("button", { name: /Quarterly review/ });
    await expect(review.first()).toBeVisible(LOADED);
    await expect(review).toHaveCount(1);
    await expect(review.first()).toContainText(/also in Your calendar \(\d\)/);
    for (const address of addresses) await expect(review.first()).not.toContainText(address.split("@")[0]);
    // The legend: the calendars are one button that opens their list; in it, a button for each calendar with its name,
    // pressed while its entries show.
    await page.getByRole("button", { name: /^Calendars \(\d+\)/ }).click();
    const legend = page.getByRole("list", { name: "Calendars", exact: true });
    await expect(legend.getByRole("button")).toHaveCount(3);
    for (const name of CALENDAR_NAMES) await expect(legend.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
    // Each calendar has a color of its own, never two the same, beside its name.
    const colors = await legend.locator("[data-color]").evaluateAll((els) => els.map((el) => el.getAttribute("data-color")));
    expect(new Set(colors).size).toBe(3);
    // Hiding the third calendar hides its entries and says so in words, not only by the mark.
    const third = legend.getByRole("button", { name: CALENDAR_NAMES[2] });
    const before = await page.locator("[data-entry-key]").count();
    await third.click();
    await expect(third).toHaveAttribute("aria-pressed", "false");
    await expect(third).toContainText("Hidden");
    expect(await page.locator("[data-entry-key]").count()).toBeLessThan(before);
    await third.click();
    await expect(third).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    // The entry's page says which calendars hold it.
    await review.first().click();
    // (The row names them too, in words for a screen reader; the page's own label is the whole text of its term.)
    await expect(page.getByText("Also in", { exact: true }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("X78. the same thread in two mailboxes is one row of Came in, naming the other mailbox", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`?token=${info.token}`);
    await go(page, "today");
    const came = page.getByRole("region", { name: /Came in/ });
    await expect(came).toBeVisible(LOADED);
    // The card lists the first rows of what came in (`ui.today.rail_rows`) and folds the rest behind "N more".
    // The rows are read before the fold is looked for, so a slow read can't be mistaken for "nothing is folded".
    await expect(came.getByRole("listitem").first()).toBeVisible(LOADED);
    const more = came.getByRole("button", { name: /^\d+ more$/ });
    if (await more.count()) await more.click();
    const thread = came.getByText("Joint lease renewal");
    await expect(thread.first()).toBeVisible(LOADED);
    await expect(thread).toHaveCount(1);
    await expect(came.getByText(/also in Your inbox, /)).toHaveCount(1);
  });

  test("X82. a business added after the accounts asks which of the connected mailboxes and calendars serve it, and Connections can change it later", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/business");
    await page.getByRole("button", { name: "Add a business" }).click();
    const form = page.getByRole("dialog", { name: "Add a business" });
    await form.getByRole("textbox", { name: /^Business name/ }).fill("Harborview Community Support Partnership Incorporated");
    await form.getByRole("button", { name: "Add the business" }).click();
    const ask = page.getByRole("dialog", { name: /^Which of your connections serve/ });
    await expect(ask).toBeVisible(LOADED);
    // Every connected mailbox and calendar is a tick; the second account's two serve the business.
    const group = ask.getByRole("group", { name: /^Serve / });
    await expect(group.getByRole("checkbox")).toHaveCount(6);
    // The ticks are grouped by the account's address: each group holds its own inbox and calendar.
    const second = group.getByRole("group", { name: addresses[1], exact: true });
    await second.getByRole("checkbox", { name: "Your inbox" }).check();
    await second.getByRole("checkbox", { name: "Your calendar" }).check();
    await expect(second.getByRole("checkbox", { name: "Your inbox" })).toBeChecked();
    // Each tick is saved as it is made, one after the other; both are in the settings before the drawer is closed.
    await expect
      .poll(
        async () => {
          const read = (await (await page.request.get("api/settings", { headers: { Authorization: `Bearer ${info.token}` } })).json()) as { items: Array<{ key: string; value: unknown }> };
          const held = read.items.find((i) => i.key === "watch.sources")!.value as Array<{ label: string; sides?: string[] }>;
          return held.filter((x) => x.label.endsWith(addresses[1]) && (x.sides ?? []).length > 1).length;
        },
        { timeout: 30_000 },
      )
      .toBe(2);
    await ask.getByRole("button", { name: "Done" }).click();
    // Later, the same sides are in the connection's own change form, beside the rest of its settings.
    await go(page, "settings/connections");
    const row = connections(page).getByRole("listitem", { name: `Your inbox, ${addresses[1]}` });
    await row.getByRole("button", { name: `More actions for Your inbox, ${addresses[1]}` }).click();
    await page.getByRole("menuitem", { name: "Change" }).click();
    const sides = page.getByRole("group", { name: `Your inbox, ${addresses[1]}: who is it for?` });
    await expect(sides).toBeVisible(LOADED);
    await expect(sides.getByRole("checkbox", { name: "Harborview Community Support Partnership Incorporated" })).toBeChecked();
    await expect(sides.getByRole("checkbox", { name: "Personal" })).toBeChecked();
  });

  test("G5b. the business page puts a section's gap under its buttons and a small one under the label of its rows; Connections stands the accounts a section's gap below its last card", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`?token=${info.token}#settings/business`);
    const label = page.getByRole("heading", { level: 3, name: "Your jobs and businesses" });
    await expect(label).toBeVisible(LOADED);
    const buttons = (await page.getByRole("button", { name: "Add a job" }).boundingBox())!;
    const words = (await label.boundingBox())!;
    const rows = (await page.locator("[data-side]").first().boundingBox())!;
    // Measured: 32px (a section's gap) under the buttons, at most 12px between the label and its first row.
    expect(words.y - (buttons.y + buttons.height)).toBeGreaterThanOrEqual(28);
    expect(rows.y - (words.y + words.height)).toBeLessThanOrEqual(12);
    await go(page, "settings/connections");
    const accounts = page.locator("#sign-ins-title");
    await expect(accounts).toBeVisible(LOADED);
    const last = (await page.locator("[data-connection-card]").last().boundingBox())!;
    const heading = (await accounts.boundingBox())!;
    expect(heading.y - (last.y + last.height)).toBeGreaterThanOrEqual(28);
  });

  test("X80. under the business filter Today leaves out what is only Personal: the first account's mail, and a clash that is not on the business", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`?token=${info.token}`);
    await go(page, "today");
    await expect(sideFilter(page)).toBeVisible(LOADED);
    const came = page.getByRole("region", { name: /Came in/ });
    // The card lists the first rows of what came in (`ui.today.rail_rows`) and folds the rest behind "N more": opened before a row is looked for.
    const all = async () => {
      await expect(came).toBeVisible(LOADED);
      const more = came.getByRole("button", { name: /^\d+ more$/ });
      if (await more.count()) await more.click();
    };
    await all();
    await expect(came.getByText("Question for account 1")).toBeVisible(LOADED);
    await pickSide(page, "Harborview Community Support Partnership Incorporated");
    await all();
    // The first account serves only Personal: its own mail is not shown under the business, the second account's (which serves both) is.
    await expect(came.getByText("Question for account 1")).toHaveCount(0);
    await expect(came.getByText("Question for account 2")).toBeVisible();
    // The clash between the first and the second account's meetings is between Personal and the business: it shows under the business.
    await expect(page.locator('[data-queue-line="clash"]').first()).toBeVisible(LOADED);
    await pickSide(page, "Personal");
    await all();
    await expect(came.getByText("Question for account 1")).toBeVisible();
    await pickSide(page, "All");
  });

  test("X77. one account failing is one line naming it with Sign in again; its rows say so, the others still say Read, and the header says a connection failed", async ({ page }) => {
    test.setTimeout(180_000);
    await fetch(`${FAKE}/__e2e/failing`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ account: 2, how: "expired" }) });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    const failing = addresses[1];
    // Read it now: the service refuses the second account's sign-in.
    for (const label of [`Your inbox, ${failing}`, `Your calendar, ${failing}`]) {
      const row = connections(page).getByRole("listitem", { name: label });
      await row.getByRole("button", { name: `More actions for ${label}` }).click();
      await page.getByRole("menuitem", { name: "Read now" }).click();
    }
    const needs = page.locator("[data-connection-card][data-need]");
    await expect(needs).toHaveCount(1, LOADED);
    await expect(needs).toHaveAttribute("data-connection-card", failing);
    await expect(needs.getByRole("button", { name: `Sign in again as ${failing}` })).toBeVisible();
    // Not nine identical red lines: the rows say what they need, and none of this account's says Read.
    for (const label of [`Your inbox, ${failing}`, `Your calendar, ${failing}`]) {
      const row = connections(page).getByRole("listitem", { name: label });
      await expect(row).toContainText(/Not read (since|yet)/);
      await expect(row).not.toContainText(/\bRead\b(?! every)/);
      await expect(row.locator(".problem-note")).toHaveCount(0);
    }
    // The other accounts are read.
    for (const address of [addresses[0], addresses[2]]) await expect(connections(page).getByRole("listitem", { name: `Your inbox, ${address}` })).toContainText("Read");
    // A restart waiting would take the header's place ("Restart to finish" outranks a failed connection), and it is not what this
    // test is about: if one waits, the failure names what it is for (settings keys, or "code") instead of showing a wrong chip.
    const waiting = (await (await page.request.get("api/status", { headers: { Authorization: `Bearer ${info.token}` } })).json()) as { restart_needed?: string | null; restart_for?: string[] };
    expect(waiting.restart_needed ?? null, `a restart waits for: ${(waiting.restart_for ?? []).join(", ") || "nothing named"}`).toBeNull();
    // The header never says all good beside it; its popover names the account once.
    await expect(page.locator("[data-status]").first()).toHaveAttribute("data-status", "connection_failed", LOADED);
    await page.locator("[data-status]").first().click();
    const dialog = page.getByRole("dialog", { name: "Status" });
    // The account is one row, said once, and the sign-in lines of the page and the header are the same row.
    const rows = dialog.getByRole("list", { name: "Accounts" }).getByRole("listitem");
    await expect(rows.filter({ hasText: failing })).toHaveCount(1);
    await expect(rows.filter({ hasText: failing })).toContainText("Needs sign-in");
    await expect(dialog.locator("[data-coverage='unread']")).toHaveCount(0);
    await page.keyboard.press("Escape");
    // A failure becomes a line on Today only once it has lasted longer than the connection's read interval since its last good read
    // (`watch.unread_gap_factor`). The test server moves the account's reads back in time, as if they had been made hours ago;
    // Today then holds one line for the account, never one for each of its connections.
    const aged = await page.request.post(new URL("/__e2e/age-runs", page.url()).href, { data: { account: failing, minutes: 6 * 60 } });
    expect(aged.ok(), await aged.text()).toBe(true);
    await go(page, "today");
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
    await expect(page.locator('[data-queue-line="source_unread"]')).toHaveCount(1, LOADED);
    // Neither it nor the account's At risk line says any part of the address: the account is named by its service (S-0543).
    await expect(page.locator('[data-queue-line="source_unread"]')).not.toContainText(failing.split("@")[0]);
    const accountLine = page.locator("[data-account-line]");
    await expect(accountLine).toHaveCount(1, LOADED);
    await expect(accountLine).toContainText(/Your .* account (\(\d\) )?|isn't being read|aren't being read/);
    await expect(accountLine).not.toContainText(failing.split("@")[0]);
  });

  test("VC13. with one of three accounts failing the header says 1 account needs you, and its popover is one state row for each account, not a wall of red lines", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    const chip = page.locator("[data-status]").first();
    await expect(chip).toHaveAttribute("data-status", "connection_failed", LOADED);
    // The pill and the page say the same thing: one account, named once, in the same words.
    await expect(chip).toContainText("1 account needs you");
    await expect(chip).toHaveAttribute("data-tone", "danger");
    const failing = addresses[1];
    const onPage = page.locator("[data-connection-card][data-need]");
    await expect(onPage).toHaveCount(1);
    const pageWords = ((await onPage.locator("header [data-state-mark]").first().innerText()) ?? "").trim();
    expect(pageWords).toMatch(/^Needs sign-in/);

    await chip.click();
    const dialog = page.getByRole("dialog", { name: "Status" });
    const rows = dialog.getByRole("list", { name: "Accounts" }).getByRole("listitem");
    // One row for each of the three accounts, whatever number of connections each holds.
    await expect(rows).toHaveCount(3);
    for (const address of addresses) await expect(rows.filter({ hasText: address })).toHaveCount(1);
    // The failing one has the edge, the tint, its words and its button; the others are a dot and a word and nothing more.
    const bad = rows.filter({ hasText: failing });
    await expect(bad).toHaveAttribute("data-state", "danger");
    await expect(bad.locator("[data-state-mark]")).toHaveText(pageWords);
    await expect(bad.locator("[data-state-mark] svg")).toHaveCount(1);
    await expect(bad.getByRole("button", { name: `Sign in again as ${failing}` })).toBeVisible();
    for (const address of [addresses[0], addresses[2]]) {
      const ok = rows.filter({ hasText: address });
      await expect(ok).not.toHaveAttribute("data-state", /./);
      await expect(ok.locator("[data-state-mark]")).toContainText("Read");
      await expect(ok.getByRole("button")).toHaveCount(0);
    }
    // Nothing in the popover is a red line of its own: the state is the row's.
    await expect(dialog.locator(".problem-note")).toHaveCount(0);
    // The edge is drawn: a 3px bar on the failing row's leading side.
    const edge = await bad.evaluate((el) => {
      const after = getComputedStyle(el, "::before");
      return { width: after.width, content: after.content };
    });
    expect(edge.width).toBe("3px");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    await page.keyboard.press("Escape");
  });

  test("VS06. the calendars are toggles with their color: pressing one hides its entries and says Hidden, pressing it again shows them", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto(`?token=${info.token}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await go(page, "schedule");
    // The month: the third calendar's one entry is an all-day holiday three days ahead, which the day view of today never shows.
    // The shortcut is the Schedule's own, so the screen is drawn before it is pressed.
    await expect(page.getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible(LOADED);
    await page.locator("body").press("4");
    // When the toggles don't fit in a row they are one "Calendars (n)" button that opens them in a popover.
    const folded = page.getByRole("button", { name: /^Calendars \(\d+\)/ });
    const toggles = page.getByRole("list", { name: "Calendars", exact: true });
    await expect(toggles.or(folded).first()).toBeVisible(LOADED);
    if (await folded.isVisible()) await folded.click();
    await expect(toggles.getByRole("button")).toHaveCount(3, LOADED);
    // The third calendar's one entry is the all-day holiday. Entries are coloured by their side, not their calendar (S3), so its
    // toggle is found by what it does: the one whose press hides the holiday.
    const mine = page.locator("main [data-entry-key]").filter({ hasText: "Public holiday" });
    await expect(mine.first()).toBeVisible(LOADED);
    const buttons = toggles.getByRole("button");
    let third = buttons.first();
    for (let n = 0; n < 3; n += 1) {
      const toggle = buttons.nth(n);
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-pressed", "false");
      const hidden = (await mine.count()) === 0;
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      if (hidden) {
        third = toggle;
        break;
      }
    }
    await third.click();
    await expect(third).toHaveAttribute("aria-pressed", "false");
    await expect(third).toContainText("Hidden");
    await expect(mine).toHaveCount(0);
    await third.click();
    await expect(third).toHaveAttribute("aria-pressed", "true");
    await expect(mine.first()).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });

  test("S-0368. the app's own calendar is one of the calendars: listed beside the three accounts', hidden and shown like them, and named in the Timeline's key", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto(`?token=${info.token}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    const today = ((await (await page.request.get("api/schedule", { headers: { Authorization: `Bearer ${info.token}` } })).json()) as { today: string }).today;
    // A day with nothing else on it: the calendars' made-up entries fall around the hour the run starts (past midnight, onto
    // tomorrow), and a month's day shows only a few entries before "more", so the entry must not share its day.
    const week = (await (await page.request.get(`api/schedule?from=${today}&days=14`, { headers: { Authorization: `Bearer ${info.token}` } })).json()) as { days: Array<{ date: string; all_day: unknown[]; timed: unknown[] }> };
    const empty = week.days.find((d) => d.date > today && d.all_day.length === 0 && d.timed.length === 0);
    expect(empty, "a day within two weeks with nothing on it").toBeDefined();
    const title = "Own calendar check";
    const made = await page.request.post("api/calendar/meetings", { headers: { Authorization: `Bearer ${info.token}` }, data: { what: title, day: empty!.date, time: "16:00", until: "16:30" } });
    expect(made.ok()).toBe(true);
    await go(page, "schedule");
    await expect(page.getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible(LOADED);
    await page.getByRole("tab", { name: "Month" }).click();
    const mine = page.locator("main [data-entry-key]").filter({ hasText: title });
    await expect(mine.first()).toBeVisible(LOADED);
    // The reviewer's "Calendars (3)" is now four: the three accounts' and the app's own.
    await page.getByRole("button", { name: /^Calendars \(\d+\)/ }).click();
    const legend = page.getByRole("list", { name: "Calendars", exact: true });
    await expect(legend.getByRole("button")).toHaveCount(4);
    const own = legend.getByRole("button", { name: "The app's own calendar" });
    await expect(own).toHaveAttribute("aria-pressed", "true");
    await own.click();
    await expect(own).toHaveAttribute("aria-pressed", "false");
    await expect(own).toContainText("Hidden");
    await expect(mine).toHaveCount(0);
    await own.click();
    await expect(own).toHaveAttribute("aria-pressed", "true");
    await expect(mine.first()).toBeVisible();
    await page.keyboard.press("Escape");
    // The Timeline's key names it as the pane does, not only "Calendar entry".
    await page.getByRole("tab", { name: "Timeline" }).click();
    await expect(page.locator('main [aria-label="Key"]')).toContainText("The app's own calendar", LOADED);
  });

  test("VS18. on a phone the failing account's card is first, its name, its state and Sign in again before anything else; signing in as another account is refused in words, and the header agrees", async ({ page }) => {
    test.setTimeout(180_000);
    // The second account is still the one the service refused (set in the earlier tests).
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    const failing = addresses[1];
    const chip = page.locator("[data-status]").first();
    await expect(chip).toContainText("1 account needs you", LOADED);
    // One card for each account, the one that needs the person first.
    const cards = page.locator("[data-connection-card]");
    await expect(cards).toHaveCount(3, LOADED);
    const first = cards.first();
    await expect(first).toHaveAttribute("data-connection-card", failing);
    await expect(first).toHaveAttribute("data-need", /./);
    // Its name, its state and its one button come before what kind of service it is and before its connections.
    const top = async (locator: ReturnType<Page["locator"]>) => (await locator.first().boundingBox())!.y;
    const name = await top(first.getByRole("heading", { name: failing, exact: true }));
    const state = await top(first.locator("[data-state-mark]"));
    const again = await top(first.getByRole("button", { name: `Sign in again as ${failing}` }));
    const service = await top(first.getByText("Example mail", { exact: true }));
    const parts = await top(first.getByRole("listitem"));
    expect(name).toBeLessThan(state);
    expect(state).toBeLessThan(again);
    expect(again).toBeLessThan(service);
    expect(service).toBeLessThan(parts);
    // The pill and the cards count the same accounts.
    await expect(page.locator("[data-connection-card][data-need]")).toHaveCount(1);
    // Signing in again as the wrong account: the service's page is asked for the first account, which is not this one.
    const [popup] = await Promise.all([page.waitForEvent("popup"), first.getByRole("button", { name: `Sign in again as ${failing}` }).click()]);
    await popup.getByRole("link", { name: addresses[0], exact: true }).click();
    await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
    const refused = first.getByRole("alert");
    await expect(refused).toContainText(`That was a different account: ${addresses[0]}. Sign in as ${failing}.`, LOADED);
    await expect(refused.getByRole("button", { name: "Try again" })).toBeVisible();
    // Nothing was added or replaced: still three accounts, the same one needing the person, and the pill says the same.
    await expect(cards).toHaveCount(3);
    await expect(page.locator("[data-connection-card][data-need]")).toHaveCount(1);
    await expect(chip).toContainText("1 account needs you");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("X84. setup's mail step with three accounts is one compact row for each, not a wall", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`?token=${info.token}`);
    await go(page, "setup");
    // The walkthrough opens on its welcome the first time; its steps are listed once it is started.
    await pressStart(page);
    await showSteps(page);
    await page.getByRole("navigation", { name: "Setup steps" }).getByRole("button", { name: /^Mail and calendar/ }).click();
    const result = page.locator("[data-mail-result]");
    await expect(result).toBeVisible(LOADED);
    const rows = result.getByRole("list", { name: "The accounts being read" }).getByRole("listitem");
    await expect(rows).toHaveCount(3);
    for (const [n, address] of addresses.entries()) await expect(rows.nth(n)).toContainText(address);
    // Three rows and a Continue, not a page of blocks: the whole result is short and never wider than the window.
    const box = (await result.boundingBox())!;
    expect(box.height, "the mail step's result is a short list, not a 1900px wall").toBeLessThan(900);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("X85. each follow-up draft says which mailbox it is sent from: a list of the three, starting on the one the conversation is in", async ({ page }) => {
    test.setTimeout(120_000);
    const auth = { Authorization: `Bearer ${info.token}` };
    // Someone who writes to the second account, and a to-do for them to send a message about.
    const person = (await (await page.request.post("api/people", { headers: auth, data: { full_name: "Pat Sample", how_to_reach: { email: ["pat.sample@partner.example.com"] } } })).json()) as { id: string };
    const added = await page.request.post("api/todos", { headers: auth, data: { text: "Send the lease papers", owners: [person.id] } });
    expect(added.ok()).toBe(true);
    await page.goto(`?token=${info.token}`);
    await go(page, "work/followups");
    await expect(page.getByRole("heading", { level: 1, name: "Follow-ups" })).toBeVisible(LOADED);
    // At this width the first person's card is open beside the list already; the only button named for them is its menu.
    await expect(page.getByRole("heading", { level: 2, name: "Pat Sample" })).toBeVisible(LOADED);
    const pick = page.getByRole("combobox", { name: "Send to Pat Sample from" });
    await expect(pick).toBeVisible(LOADED);
    expect((await choicesOf(pick)).map((c) => c.label)).toEqual(addresses);
    // Mail from them was read in the first account's mailbox, so that is where the draft starts.
    await expect(pick).toHaveAttribute("value", addresses[0]);
    await choose(pick, addresses[2]);
    await expect(pick).toHaveAttribute("value", addresses[2]);
  });

  test("R1 / S-0337. a failing account whose server answers in its own long words shows a plain sentence with Sign in again as a button and the server's words only behind Show details, shown whole, on every screen that says it failed", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await fetch(`${FAKE}/__e2e/failing`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ account: 2, how: "refused" }) });
    const failing = addresses[1];
    // The server's own words, none written out here: its fictional steps and its error code.
    const SERVER = /fictional-step|AuthenticationFailed|app-passwords|A17 NO/;
    const bodyText = (p: Page) => p.locator("body").innerText();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    for (const label of [`Your inbox, ${failing}`, `Your calendar, ${failing}`]) {
      const row = connections(page).getByRole("listitem", { name: label });
      await row.getByRole("button", { name: `More actions for ${label}` }).click();
      await page.getByRole("menuitem", { name: "Read now" }).click();
    }
    const bad = card(page, failing);
    await expect(bad).toHaveAttribute("data-need", /./, LOADED);
    // The card: a plain sentence, a Sign in again button, and nothing in the server's words.
    await expect(bad.getByRole("button", { name: `Sign in again as ${failing}` })).toBeVisible();
    expect(await bad.innerText()).not.toMatch(SERVER);
    const sentence = bad.locator("[data-problem-sentence]");
    await expect(sentence).toBeVisible();
    expect((await sentence.innerText()).length, "a sentence, not the reply").toBeLessThan(320);
    // The details are behind a button, and open in full: the last of the server's words is readable, wrapped inside the card (H2-09).
    const show = bad.getByRole("button", { name: "Show details" });
    await expect(show).toBeVisible();
    await show.click();
    const details = bad.locator("[data-problem-details]");
    await expect(details).toContainText("fictional-step");
    await expect(details).toContainText("fictional-step-16");
    const fit = await details.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const card = el.closest("[data-need]")!.getBoundingClientRect();
      return { whole: el.scrollHeight <= Math.ceil(box.height), inside: box.right <= card.right + 1, shown: getComputedStyle(el).webkitLineClamp };
    });
    expect(fit.whole, "no part of the reply is cut off").toBe(true);
    expect(fit.inside, "the reply stays inside the card").toBe(true);
    expect(fit.shown).toBe("none");
    // One remedy that fits how the account signed in (H2-03): it signed in on the service's page, so there is no password box to name.
    expect(await bad.locator("[data-problem-sentence]").innerText()).not.toMatch(/app password|password box/i);
    expect(await bad.locator("[data-problem-sentence]").innerText()).toMatch(/sign in again/i);
    await bad.getByRole("button", { name: "Hide details" }).click();
    expect(await bad.innerText()).not.toMatch(SERVER);
    // The rows under the card, the Read now toast's text and the whole page say none of it.
    expect(await bodyText(page)).not.toMatch(SERVER);
    // The header's popover.
    await page.locator("[data-status]").first().click();
    expect(await page.getByRole("dialog", { name: "Status" }).innerText()).not.toMatch(SERVER);
    await page.keyboard.press("Escape");
    // Today, once the failure has lasted (a line for the account), and every other place the failure is told.
    const aged = await page.request.post(new URL("/__e2e/age-runs", page.url()).href, { data: { account: failing, minutes: 6 * 60 } });
    expect(aged.ok(), await aged.text()).toBe(true);
    for (const hash of ["today", "records/questions", "records/changes"]) {
      await go(page, hash);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOADED);
      expect(await bodyText(page), `${hash} says none of the server's words`).not.toMatch(SERVER);
    }
    await go(page, "today");
    await expect(page.locator('[data-queue-line="source_unread"]')).toHaveCount(1, LOADED);
    expect(await page.locator('[data-queue-line="source_unread"]').innerText()).not.toMatch(SERVER);
    // Setup's mail step.
    await go(page, "setup");
    await pressStart(page);
    await showSteps(page);
    await page.getByRole("navigation", { name: "Setup steps" }).getByRole("button", { name: /^Mail and calendar/ }).click();
    await expect(page.locator("[data-mail-result]")).toBeVisible(LOADED);
    expect(await bodyText(page)).not.toMatch(SERVER);
    await fetch(`${FAKE}/__e2e/failing`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ account: 2, how: "expired" }) });
  });

  test("S-0351 (S4-N02). with the accounts signed in but not switched on to act, Notices says what is really missing and never that no calendar or mailbox is signed in", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/today");
    const calendar = page.locator('[data-unavailable="calendar"]');
    const mail = page.locator('[data-unavailable="mail"]');
    await expect(calendar).toBeVisible(LOADED);
    await expect(mail).toBeVisible();
    for (const choice of [calendar, mail]) {
      // What the reviewer read: signed in, yet told one is missing.
      await expect(choice).not.toContainText(/Needs a (signed-in calendar|connected mailbox)/);
      await expect(choice).toContainText("not switched on to act");
      await expect(choice).toHaveAttribute("data-missing", "acting_off");
    }
    // The way to put it right is one link, to where acting is switched on.
    await expect(calendar.getByRole("link", { name: "Switch it on" })).toBeVisible();
  });

  test("X53. after a person's own sign-out the rows and the status say signed out, and the header says so as a warning: not Read, not All good, not Connection failed", async ({ page }) => {
    test.setTimeout(180_000);
    const auth = { Authorization: `Bearer ${info.token}` };
    await page.goto(`?token=${info.token}`);
    const listed = (await (await page.request.get("api/sign-ins", { headers: auth })).json()) as Array<{ name: string; accounts: Array<{ key: string; address: string | null }> }>;
    const signIn = listed.find((l) => l.accounts.some((a) => a.address === addresses[1]))!;
    const account = signIn.accounts.find((a) => a.address === addresses[1])!;
    // Signing out the account that was failing leaves only a deliberate sign-out: nothing was refused any more.
    const out = await page.request.delete(`api/sign-ins/${signIn.name}?account=${encodeURIComponent(account.key)}`, { headers: auth });
    expect(out.ok()).toBe(true);
    await go(page, "settings/connections");
    for (const label of [`Your inbox, ${addresses[1]}`, `Your calendar, ${addresses[1]}`]) {
      const row = connections(page).getByRole("listitem", { name: label });
      await expect(row).toContainText(/Not read (since|yet)/, LOADED);
      await expect(row).not.toContainText(/\bRead\b(?! every)/);
    }
    await expect(card(page, addresses[1])).toContainText("Signed out");
    const chip = page.locator("[data-status]").first();
    await expect(chip).toHaveAttribute("data-status", "connection_signed_out", LOADED);
    // The account needs the person (to sign in again), and the header counts it the way Connections lists it.
    await expect(chip).toContainText("1 account needs you");
    await expect(chip).not.toContainText("All good");
    await expect(chip).not.toContainText("Connection failed");
    await expect(chip).toHaveAttribute("data-tone", "warn");
  });
});
