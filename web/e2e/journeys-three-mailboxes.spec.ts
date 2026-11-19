// S-0356 (review of fb08fa7a, S5-N3): one sent message held by three mailboxes is one to-do. A workspace made as a person makes it,
// with the mail add-on on, beside fake services that play three people, each with a sent folder holding the same message
// (the same Message-ID, a key of each mailbox's own). Setup is walked from its first screen with all three accounts signed in, the
// first Start is pressed on Today, the assistant's scripted answer to the message is one to-do, and To-dos shows it once.
import { expect } from "@playwright/test";
import { test } from "./test";
import { collectProblems, fakeAddress, pressStart, startOnToday, type Info, pickFolder, leaveOut, turnOnAndGoOn } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_THREE_FAKE_PORT", 8721);
const LOADED = { timeout: 60_000 };
const problems: string[] = [];

test.describe.serial("journey: one sent message in three mailboxes", () => {
  // The journey changes its server's state (a fresh workspace, signed-in accounts, a restart), and a re-run would start from
  // that used server and fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its failure as it is.
  test.describe.configure({ retries: 0 });
  test.use({ actionTimeout: 30_000 });
  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  test("S-0356. three mailboxes holding one sent message give one to-do after setup and the first Start", async ({ page }) => {
    test.setTimeout(300_000);
    collectProblems(page, problems);
    const info = (await (await fetch(`${FAKE}/__e2e/info`)).json()) as Info;
    const addresses = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts.map((a) => a.address);
    expect(addresses).toHaveLength(3);
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
    await pressStart(page);
    const main = page.locator("main#main");
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

    // The go was given in the AI step, so the reading starts at the first sign-in: the assistant's answer is scripted first.
    // The assistant's answer to the sent message is one to-do.
    const sentLine = `${info.people[0]} will send the revised budget by 2026-11-05.`;
    const scripted = await fetch(`${FAKE}/__e2e/script`, {
      method: "POST",
      body: JSON.stringify({
        when: "will send the revised budget by 2026-11-05",
        answer: {
          summary: "Read by the journey's script.",
          ops: [{ op: "action.add", text: "Send the revised budget.", owners: ["me"], due: "2026-11-05", basis: "said", evidence: { quote: sentLine } }],
        },
      }),
    });
    expect(scripted.ok).toBe(true);
    // Three accounts, one after the other through the service's own page.
    const row = main.locator('[data-service="journey-mail"]');
    for (const [n, address] of addresses.entries()) {
      // Once an account is in, the ways to add another are in the panel that "Connect another account" opens.
      if (n > 0) await main.getByRole("button", { name: /^Connect another account/ }).click();
      const button = n === 0 ? row.getByRole("button", { name: "Sign in to Example mail", exact: true }) : page.getByRole("dialog").getByRole("button", { name: "Add another account to Example mail", exact: true });
      const [popup] = await Promise.all([page.waitForEvent("popup"), button.click()]);
      await popup.getByRole("link", { name: address, exact: true }).click();
      await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
      await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
      // The panel closes by itself when the account is in, and the account is one row more.
      await expect(page.getByRole("dialog")).toHaveCount(0, LOADED);
      await expect(main.locator("[data-account-row]")).toHaveCount(n + 1, LOADED);
    }
    // Three accounts are three rows, the ways to add are not on the page, and the Back and Continue bar is the footer at the
    // window's foot with the step ending above it (S-0557: it was reported mid-page with the step continuing under it).
    await expect(main.locator("[data-account-row]")).toHaveCount(3);
    await expect(main.locator("[data-service], [data-mailbox-choice]")).toHaveCount(0);
    const bar = page.locator("[data-step-footer]");
    // Scrolled to the end, the step's last line is above the bar and not under it; the bar stands at the window's foot.
    await page.evaluate(() => {
      const end = document.scrollingElement ?? document.documentElement;
      end.scrollTop = end.scrollHeight;
    });
    const barBox = (await bar.boundingBox())!;
    const lineBox = (await main.locator("[data-set-aside-line]").boundingBox())!;
    expect(Math.round(barBox.y + barBox.height)).toBe(page.viewportSize()!.height);
    expect(lineBox.y + lineBox.height).toBeLessThanOrEqual(barBox.y + 1);
    await main.getByRole("button", { name: "Continue" }).click();
    // The account's "Read in full from" is unanswered, so Continue asks first (H5-12); going on without choosing goes on.
    await page.getByRole("button", { name: "Go on without choosing" }).click();
    // The first reading of the three accounts is waited for on screen, then People follows by itself.
    await expect(main.getByRole("heading", { level: 2, name: "People" })).toBeVisible({ timeout: 120_000 });
    await leaveOut(page, main);
    await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible(LOADED);
    await pickFolder(page, main, ["offsite"]);
    await expect(main.getByText(/That folder works/)).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Continue" }).click();
    // With three accounts still being read, the settings can change under the step (the app says so); pressing Continue again goes on.
    const stale = main.getByRole("alert").filter({ hasText: "The settings changed since you opened them" });
    await expect(main.getByRole("heading", { level: 2, name: "Where things stand" }).or(stale)).toBeVisible(LOADED);
    if (await stale.isVisible()) {
      // Looking again, as the message says: the page is read afresh and the step goes on from where it was.
      await page.reload();
      await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible(LOADED);
      const folder = main.getByLabel("Folder", { exact: true });
      if ((await folder.inputValue()) === "") {
        await pickFolder(page, main, ["offsite"]);
        await expect(main.getByText(/That folder works/)).toBeVisible(LOADED);
      }
      await main.getByRole("button", { name: "Continue" }).click();
    }
    await expect(main.getByRole("heading", { level: 2, name: "Where things stand" })).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Go to Today" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
    // Setting up never asks for a restart: everything setup saves is taken in at once.
    const status = (await (await page.request.get("api/status", { headers: { Authorization: `Bearer ${info.token}` } })).json()) as { restart_needed: string | null; restart_for: string[] };
    expect(status.restart_for, "settings that wait for a restart after setup").toEqual([]);
    expect(status.restart_needed).toBeNull();
    await startOnToday(page);

    // The assistant reads what the Start took in; the promise in the sent message is made a to-do once, though three mailboxes hold it.
    const auth = { Authorization: `Bearer ${info.token}` };
    const listed = async () => ((await (await page.request.get("api/open-items", { headers: auth })).json()) as { actions: Array<{ text: string }> }).actions.filter((a) => a.text === "Send the revised budget.").length;
    await expect
      .poll(listed, { timeout: 150_000 })
      .toBeGreaterThan(0)
      .catch(async (err) => {
        const asked = (await (await fetch(`${FAKE}/__e2e/ai-requests`)).json()) as { inputs: string[] };
        const changes = (await (await page.request.get("api/changes", { headers: auth })).json()) as Array<{ id: string; state: string; waiting: string | null }>;
        throw new Error(`${err}\ninputs: ${asked.inputs.map((i) => i.slice(0, 80)).join(" | ")}\nchanges: ${JSON.stringify(changes.map((c) => [c.id, c.state, c.waiting]))}`);
      });
    // Every request the Start made has finished, so a second copy would be there by now.
    await expect
      .poll(async () => ((await (await page.request.get("api/changes", { headers: auth })).json()) as Array<{ state: string }>).every((c) => !["queued", "running"].includes(c.state)), { timeout: 150_000 })
      .toBe(true);
    expect(await listed()).toBe(1);
    // And To-dos shows it once.
    await page.evaluate(() => {
      window.location.hash = "work/open";
    });
    await expect(page.getByRole("heading", { level: 1, name: "To-dos and questions" })).toBeVisible(LOADED);
    const rows = page.getByRole("list", { name: "Open to-dos" }).getByRole("listitem").filter({ hasText: "Send the revised budget." });
    await expect(rows.first()).toBeVisible(LOADED);
    await expect(rows).toHaveCount(1).catch(async (err) => {
      const all = (await (await page.request.get("api/open-items", { headers: auth })).json()) as { actions: Array<Record<string, unknown>> };
      throw new Error(`${err}\nopen-items: ${JSON.stringify(all.actions.map((a) => [a.id, a.text, a.due, a.source]))}\nrows: ${(await rows.allInnerTexts()).join(" || ")}\ninputs: ${((await (await fetch(`${FAKE}/__e2e/ai-requests`)).json()) as { inputs: string[] }).inputs.map((i) => i.replace(/\s+/g, " ").slice(0, 160)).join(" ||| ")}`);
    });
  });
});
