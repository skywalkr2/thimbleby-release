// Journey 6, the exit test of the first phase in automated form: a person on a fresh install does everything through
// the walkthrough only, and the walkthrough's first result (the look back over the last two weeks of their mail, with its
// estimate, then the promises it found) comes before backups, people or anything else that asks about more. A workspace made by the init command with no template and started by the serve command, with
// nothing installed or set: no mail add-on, no account, no backup. The catalog (named through the app's environment,
// so no settings file is touched) offers the mail add-on as a wheel, and fakes play the outside services
// (tests/fake_services.py): the AI service over plain HTTP, and the sign-in, mail, calendar and catalog services over
// HTTPS with a throwaway authority the app trusts through its environment.
// The journey never touches the workspace: it reads the page, the fake services, the throwaway place add-ons are
// installed into, and the file the app's output is kept in to count restarts.
// Names come from the fictional workspace the fake services serve, never written out here.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect } from "@playwright/test";
import { test } from "./test";
import { choicesOf, choose } from "./choose";
import { collectProblems, expectFoundLine, fakeAddress, pressStart, revealNewLines, startOnToday, visit, type Info, type Requests, type SignInSeen, FIRST_SCREEN, openView, pickFolder, leaveOut, turnOnAndGoOn } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_NEW_START_FAKE_PORT", 8794);

let info: Info;
const problems: string[] = [];

const requests = async (): Promise<Requests> => (await fetch(`${FAKE}/__e2e/ai-requests`)).json();
const service = async (): Promise<SignInSeen> => (await fetch(`${FAKE}/__e2e/sign-in`)).json();

/** How many times the app restarted since it was started, from what it printed. */
const restarts = (): number => (existsSync(String(info.app_log)) ? readFileSync(String(info.app_log), "utf8").match(/Restarting, as asked/g) ?? [] : []).length;

test.describe.serial("journey: new start", () => {
  // The journey changes its server's state (a fresh workspace, signed-in accounts, a restart), and a re-run would start from
  // that used server and fail on its first line for that reason: a re-run proves nothing, so it takes none and shows its failure as it is.
  test.describe.configure({ retries: 0 });
  test.beforeAll(async () => {
    info = await (await fetch(`${FAKE}/__e2e/info`)).json();
  });

  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  test("J6. From a fresh install to my first promises, through the walkthrough only", async ({ page }) => {
    test.setTimeout(300_000);
    collectProblems(page, problems);
    expect(info.app_log).toBeTruthy();
    expect(info.install_target).toBeTruthy();
    const installed = join(String(info.install_target), "journey_mail");
    expect(restarts()).toBe(0);
    expect(existsSync(installed)).toBe(false);

    // 1. I open the link the start command printed. The walkthrough opens by itself and says nothing is spent yet.
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
    await expect(page.getByText("About 10–20 minutes. You can stop and come back.")).toBeVisible();
    await visit(page);
    await pressStart(page);
    const main = page.locator("main#main");

    // 2. You.
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible();
    await main.getByLabel("Your full name").fill(info.people[0]);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(page.locator('[data-screen="you"][data-state]')).toContainText("Done");
    // The save went on to the next screen, so its mark in the step list says it (a toast from one screen goes when the
    // next opens); that screen's own buttons can be pressed right away. The next screen is Work: Just me is chosen.
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible();
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible();
    await main.getByRole("button", { name: "Back" }).click({ trial: true });
    await visit(page);
    // A toast from one screen is gone when the next one opens.
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Notifications" }).getByText(/^Saved\./)).toHaveCount(0);

    // 3. Your AI account: the fake service, with Internal ticked, since my mail is internal material.
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible();
    await main.getByRole("radio", { name: /Something else/ }).check();
    await main.getByRole("button", { name: /^Another service/ }).click();
    await main.getByLabel(/^Another service/).check();
    await main.locator("#ai-key").fill("a-made-up-key");
    await main.getByRole("textbox", { name: "Service address" }).fill(info.ai_base_url);
    await main.getByRole("textbox", { name: "Service address" }).blur();
    // The check runs by itself, for every kind of work, before anything is saved.
    await expect(main.getByText("Works. Ready to use.")).toBeVisible();
    // One explicit yes lets this account read my mail and notes (the usual hand-in is internal material).
    await main.getByRole("radio", { name: /^Yes/ }).check();
    await main.getByRole("button", { name: "Continue" }).click();
    await turnOnAndGoOn(main);
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-screen="ai"][data-state]')).toContainText("Done");
    await visit(page);

    // 4. Mail and calendar: the mail add-on is not on this computer, but the catalog lists it, with what it reads and
    // what it reaches. One button installs and turns it on; nothing restarts yet.
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible();
    const row = main.locator('[data-service="journey-mail"]');
    await expect(row).toHaveAttribute("data-state", "not_installed");
    await expect(row).toContainText("Reads your mail and calendar");
    await expect(row.getByRole("button", { name: /^Connect Example mail/ })).toBeVisible();
    await expect(row).not.toContainText("Not on this computer");
    // What it reaches is behind a disclosure, in plain words, and none of the settings jargon is on the row.
    await expect(row.getByText("What it can access")).toBeVisible();
    expect(await row.innerText()).not.toMatch(/Signs in to|Websites:|Access keys you provide/);
    await row.getByText("What it can access").click();
    await expect(row).toContainText("You sign in on the service's own page");
    await expect(main.getByText(/Restart to finish connecting/)).toHaveCount(0);
    await visit(page);
    expect(existsSync(installed)).toBe(false);
    const before = await requests();
    expect(before.work).toBe(0);
    // The row is one line and one button: it says the app restarts first, and the button adds it and restarts.
    await expect(row.locator("[data-needs-addon]")).toContainText("The app restarts for a few seconds first");
    expect((await service()).authorizations).toBe(0);
    const appAddress = page.url();
    // One click installs, turns on and restarts the app; then "Sign in to Example mail" waits for the next click, which
    // opens the service's sign-in in its own window (a window the app opened by itself would be blocked); the setup
    // screen stays where it is.
    await row.getByRole("button", { name: /^Connect Example mail/ }).click();
    const signInButton = main.getByRole("button", { name: "Sign in to Example mail", exact: true });
    await expect(signInButton).toBeVisible({ timeout: 120_000 });
    const [popup] = await Promise.all([page.waitForEvent("popup", { timeout: 60_000 }), signInButton.click()]);
    // It went into the throwaway place the app installs into, and the one restart happened on that click.
    expect(existsSync(installed)).toBe(true);
    // And nowhere in the computer's own add-ons place.
    expect(existsSync(join(String(info.real_install_target), "journey_mail"))).toBe(false);
    expect(restarts()).toBe(1);
    // The sign-in is in its own window, and the app's window never left the walkthrough.
    expect(page.url()).toBe(appAddress);
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible();
    // The service sends that window back to the app, which tells this screen how it went and closes the window.
    await popup.waitForEvent("close", { timeout: 60_000 }).catch(() => undefined);
    // The step now leads with the result: the account is one row, and every way to add another is in the panel.
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", { timeout: 90_000 });
    await expect(main.locator("[data-account-row]")).toHaveCount(1);
    // S-0585: after the sign-in the step asks how far back to read mail in full: each reach with its estimate, none chosen, and
    // "Not now" among the choices. Nothing is read until one is picked.
    const fullRead = main.locator("[data-full-read]");
    await expect(fullRead).toHaveCount(1);
    const pick = fullRead.getByRole("combobox");
    await expect(pick).toBeVisible({ timeout: 60_000 });
    await expect(pick).toContainText("Choose…");
    await expect(fullRead.getByRole("button", { name: "Read it" })).toBeDisabled();
    const labels = (await choicesOf(pick)).map((c) => c.label);
    expect(labels).toHaveLength(4);
    for (const reach of ["1 week", "2 weeks", "Not now"]) expect(labels.join("|")).toContain(reach);
    await choose(pick, "Not now");
    await expect(fullRead.getByRole("button", { name: "Skip for now" })).toBeEnabled();
    await expect(main.getByText(/Restart to finish connecting/)).toHaveCount(0);
    await expect(main.locator("[data-service]")).toHaveCount(0);
    await main.getByRole("button", { name: "Connect another account" }).click();
    const panelRow = page.getByRole("dialog").locator('[data-service="journey-mail"]');
    await expect(panelRow).toHaveAttribute("data-state", "ready");
    await expect(main.locator("[data-account-row]")).toContainText(/.+@example\.com/);
    await page.keyboard.press("Escape");
    // A page opened fresh after the restart resumes at this screen.
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible();
    await visit(page);
    // Signed in once, nothing was asked of the assistant. A page opened fresh has the ways to add behind the one button.
    await main.getByRole("button", { name: "Connect another account" }).click();
    const again = page.getByRole("dialog").locator('[data-service="journey-mail"]');
    await expect(again).toHaveAttribute("data-signed-in", "");
    await expect(again).toContainText("Reading your mail and calendar.");
    await expect(again).not.toContainText("Sign in to start reading");
    await expect(again.getByRole("button", { name: /^Sign in/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    // The sign-in toast doesn't cover Back or Next either.
    await main.getByRole("button", { name: "Back" }).click({ trial: true });
    await main.getByRole("button", { name: "Continue" }).click({ trial: true });
    let seen = await service();
    expect(seen).toMatchObject({ authorizations: 1, exchanges: 1, refused: 0 });
    expect(page.url()).not.toMatch(/code=|state=|sign_in=/);
    // The screen says what is read now, and that it is fetched at sign-in and the AI is not used or paid until Start.
    const reading = main.locator("[data-reading]");
    await expect(reading.getByText("Your inbox")).toBeVisible();
    await expect(reading.getByText("Your calendar")).toBeVisible();
    await expect(reading.getByText(/Your mail and calendar are fetched when you sign in/)).toBeVisible();
    await expect(page.locator('[data-screen="mail"][data-state]')).toContainText("Done");
    await visit(page);
    // The go was given in the AI step (and nothing ran before it: the count was 0 there), so the first reading may already be
    // handing items in; what is checked is that each item is handed in once, below.
    const { mail: recentMail, events: recentEvents, noted: recentNoted } = seen.recent_items;
    // S-0519: the inbox holds a bulk notice filed under updates and written to me alone (no one else listed on it), and a mailing
    // of the same kind to many. The notice is handed in as work; the mailing is set aside.
    const notice = seen.notice!;
    expect(seen.intake_items.mail).toContain(notice.alone);
    expect(seen.intake_items.set_aside).not.toContain(notice.alone);
    expect(seen.intake_items.set_aside).toContain(notice.many);
    expect(seen.intake_items.mail).not.toContain(notice.many);
    expect(recentMail.length).toBeGreaterThan(0);
    expect(recentNoted.length).toBeGreaterThan(0);
    // The look back takes in the last 7 days of work mail and every event, so each is counted once below.
    // The sign-in also names the account's sent mail, which is read with the inbox and credited to me, with no folder chosen.
    const { mail, events, noted, sent, sent_to_check: sentToCheck, mail_to_check: mailToCheck, events_to_check: eventsToCheck } = seen.intake_items;
    expect(sent.length).toBeGreaterThan(0);
    const handedIn = mail.length + events.length + sent.length;
    expect(handedIn).toBeGreaterThan(recentMail.length + recentEvents.length);
    expect(noted).toHaveLength(0);
    // The assistant is asked, once, to read the message that holds a promise: the person's own, to send the venue list.
    const promiseLine = `${info.people[0]} will send the venue list by 2026-11-02.`;
    const scripted = await fetch(`${FAKE}/__e2e/script`, {
      method: "POST",
      body: JSON.stringify({
        when: "will send the venue list by 2026-11-02",
        answer: {
          summary: "Read by the journey's script.",
          ops: [
            {
              op: "action.add",
              text: "Send the venue list.",
              owners: ["me"],
              due: "2026-11-02",
              basis: "said",
              evidence: { quote: promiseLine },
            },
          ],
        },
      }),
    });
    expect(scripted.ok).toBe(true);
    // A second promise is only in the mail I sent: nothing I received repeats it.
    const sentLine = `${info.people[0]} will send the revised budget by 2026-11-05.`;
    const scriptedSent = await fetch(`${FAKE}/__e2e/script`, {
      method: "POST",
      body: JSON.stringify({
        when: "will send the revised budget by 2026-11-05",
        answer: {
          summary: "Read by the journey's script.",
          ops: [
            {
              op: "action.add",
              text: "Send the revised budget.",
              owners: ["me"],
              due: "2026-11-05",
              basis: "said",
              evidence: { quote: sentLine },
            },
          ],
        },
      }),
    });
    expect(scriptedSent.ok).toBe(true);
    await main.getByRole("button", { name: "Continue" }).click();
    // The account's "Read in full from" is unanswered, so Continue asks first (H5-12); going on without choosing goes on.
    await page.getByRole("button", { name: "Go on without choosing" }).click();

    // 5. After Mail and calendar the first reading is waited for on screen, and People follows it by itself, with the assistant's
    // offers. The assistant was turned on in the AI step, so its first reading is not held for a go on Today.
    await expect(main.getByRole("heading", { level: 2, name: "People" })).toBeVisible({ timeout: 120_000 });
    await expect(main.getByText("Optional extras")).toHaveCount(0);
    await visit(page);
    seen = await service();
    // The inbox and the sent folder are each read once; nobody chose a folder.
    expect(seen).toMatchObject({ mail_reads: 2, calendar_reads: 1, unauthorized: 0 });

    // 6. People: skipping is fine, after the confirmation. Who the person deals with is the assistant's reading, so the step
    // offers no one by the shape of a name or an address (the sent mail names several people and a newsletter's reply
    // address), and still lets the person add by hand. The reading has run, so the assistant's own offers may be listed, but
    // none of the machine-made addresses (a newsletter's reply address, an automatic sender).
    const suggested = main.locator("[data-people-suggestions]");
    await expect(suggested).toBeVisible();
    await expect(suggested).not.toContainText(/responses|8c4261ed|replies\./i);
    await visit(page);
    await leaveOut(page, main);

    // 7. Backups: a folder outside the workspace, checked before it is saved.
    await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible();
    await pickFolder(page, main, ["offsite"]);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(page.locator('[data-screen="backup"][data-state]')).toContainText("Done");
    // Choosing the folder makes the first backup at once, and Continue goes on to the last screen.
    await visit(page);

    // 8. Done: what was set up and what was skipped, then the optional extras. The last button lands on Today.
    // Something was passed by, so the last screen says where things stand and is not headed Done.
    await expect(main.getByRole("heading", { level: 2, name: "Where things stand" })).toBeVisible();
    const recap = main.getByRole("list", { name: "What was set up" });
    for (const step of ["workspace", "work", "ai", "mail", "backup"]) await expect(recap.locator(`[data-step="${step}"]`)).toContainText("Done");
    // The first look at the mail is no row here: it waits for the Start on Today.
    await expect(recap.locator('[data-step="promises"]')).toHaveCount(0);
    // Moving on from People with nobody added passes it, and says so.
    await expect(recap.locator('[data-step="people"]')).toContainText("No one added");
    await main.locator("summary", { hasText: "Optional extras" }).click();
    const extras = main.getByRole("region", { name: "Optional extras" });
    await expect(extras).toBeVisible();
    expect(await extras.getByRole("listitem").count()).toBeGreaterThan(0);
    await visit(page);
    await main.getByRole("button", { name: "Go to Today" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
    // The look back waits for the Start on Today, which shows its cost first. One request for each item taken in, each item
    // once, and the promises found arrive below as lines to look over, never in setup.
    await startOnToday(page);
    await expect
      .poll(async () => (await requests()).work, { timeout: 60_000 })
      .toBe(handedIn)
      .catch(async (err) => {
        const r = (await requests()) as unknown as { inputs?: string[] };
        throw new Error(`${err}\ninputs: ${(r.inputs ?? []).map((i) => i.replace(/\s+/g, " ").slice(0, i.startsWith("[ACT") ? 1500 : 110)).join("\n  ")}`);
      });
    // The weekly look at who the person deals with ran once after the first read, and is not counted as work.
    await expect.poll(async () => (await requests()).learning, { timeout: 60_000 }).toBe(1);
    const asked = await requests();
    // The reading of the week ahead is its own kind of run, made at most once a week, and only after the Start.
    expect(asked.week, `week-ahead runs: ${JSON.stringify(asked.week_runs, null, 1)}`).toBeLessThanOrEqual(1);
    // The work mail the rules could not place was sorted in one run for each source's batch (the inbox, and the sent mail
    // when the rules leave it unplaced); sorting is not counted as work.
    expect(asked.sorting).toBeGreaterThanOrEqual(1);
    expect(asked.sorting).toBeLessThanOrEqual(2);
    for (const title of [...mail, ...events, ...sent]) expect(asked.inputs.filter((input) => input.includes(title))).toHaveLength(1);
    // The first backup was made while setting up, so Today doesn't ask for one and the header chip doesn't say one is needed.
    await expect(page.getByRole("region", { name: "Backup", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^App status: / })).not.toContainText(/No backup yet|Backup (not set up|failed|overdue)/);

    // 9. The recent mail is on Came in within seconds; what is older isn't.
    const came = page.getByRole("region", { name: "Came in" });
    await expect(came.getByText(recentMail[0])).toBeVisible({ timeout: 10_000 });
    // Came in lists the first few rows; the notice (S-0519) is proven below by what the assistant was handed and by Handled for you.
    for (const title of recentMail.filter((t) => t !== notice.alone).slice(0, 3)) await expect(came.getByText(title, { exact: true })).toBeVisible();
    // Which day a meeting falls on is the Schedule's own check (schedule.spec.ts); a journey that crosses midnight must not depend on it.
    for (const title of recentNoted) await expect(came.getByText(title, { exact: true })).toHaveCount(0);
    await visit(page);

    // 10. What was found is one line for each source, not a line for each item: none of the items' own review lines is on
    // Today until I open the list.
    const found = page.locator('[data-queue-line="intake_review"]');
    // Only what needs a look is counted: a thank-you, an agreement or a plain announcement is filed quietly.
    await revealNewLines(page, found, 3);
    await expectFoundLine(found.filter({ hasText: "Your inbox" }), "your inbox", mailToCheck.length);
    await expectFoundLine(found.filter({ hasText: "Your calendar" }), "your calendar", eventsToCheck.length);
    // The sent mail is its own source, so it has its own line.
    await expectFoundLine(found.filter({ hasText: "Your sent mail" }), "your sent mail", sentToCheck.length);
    await expect(found).toHaveCount(3);
    await expect(page.locator('[data-queue-line="review"]')).toHaveCount(0);
    await visit(page);

    // Look over opens each list on Today without leaving it, and All looks good reviews it: the lines leave and nothing is
    // added to Today in their place.
    for (const label of ["Your inbox", "Your calendar", "Your sent mail"]) {
      await found.filter({ hasText: label }).getByRole("button", { name: "Look over", exact: true }).click();
      await expect(page).toHaveURL(/#today$/);
      // The items open under the line, or in the rail's column from 1280px.
      await found.filter({ hasText: label }).or(page.locator("[data-queue-inspector]")).getByRole("button", { name: /^Keep (it|all \d+)$/ }).click();
    }
    await expect(found).toHaveCount(0);
    await expect(page.locator('[data-queue-line="review"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Show \d+ new items?$/ })).toHaveCount(0);
    await visit(page);
    await expect(page.getByText(/stopped, see why below/)).toHaveCount(0);

    // S-0519, on Handled for you: the mailing to many is there, set aside; the notice to me alone is not, since Reginald has it.
    await visit(page);
    await openView(page, "Handled for you");
    const handled = page.locator("main#main");
    await expect(handled.getByRole("heading", { level: 1, name: "Handled for you" })).toBeVisible();
    // Each group is a button that opens its rows: the mailing is among the automated notices.
    for (const group of [/^Automated notices/, /^Sales, promotions and social updates/]) await handled.getByRole("button", { name: group }).click();
    await expect(handled.getByText(notice.many)).toBeVisible({ timeout: 30_000 });
    await expect(handled.getByText(notice.alone)).toHaveCount(0);

    // The whole path: one request per item and none before Start, one sign-in, and exactly one restart.
    expect((await requests()).work).toBe(handedIn);
    expect(await service()).toMatchObject({ authorizations: 1, exchanges: 1, unauthorized: 0, refused: 0 });
    expect(restarts()).toBe(1);
  });
});
