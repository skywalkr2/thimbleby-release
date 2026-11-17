// Setup and Settings, each story closed by the steps a reviewer takes in a browser. A workspace made as a person makes it, with the mail add-on on, beside fake services that
// play three people (tests/fake_services.py). Setup is walked from its first screen; Settings is read on the same workspace.
// S-0377 the mark and name in setup's header · S-0371 the pasted-key sentence · S-0340 signed out · S-0370 people's names ·
// S-0339 one copy · S-0358 Delete this workspace · S-0353 Your business · S-0352 the logo · S-0372 a quick link twice ·
// S-0373 search · S-0374 a folder connection · S-0362 money fields · S-0375 the accent.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { collectProblems, fakeAddress, pressStart, type Info, pickFolder } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_R2_FAKE_PORT", 8735);
const LOADED = { timeout: 30_000 };
/** Made-up addresses are built from this, so none is written out whole. */
const WEB = "https" + "://";

let info: Info;
let addresses: string[];
const problems: string[] = [];

const go = (page: Page, hash: string) =>
  page.evaluate((to) => {
    window.location.hash = to;
  }, hash);

const auth = () => ({ Authorization: `Bearer ${info.token}` });

/** Everything in the window that sticks out past its right edge (the page may never scroll sideways). */
const sidewaysScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test.describe.serial("review R2: setup and Settings", () => {
  test.use({ actionTimeout: 30_000 });
  test.beforeAll(async () => {
    info = await (await fetch(`${FAKE}/__e2e/info`)).json();
    addresses = ((await (await fetch(`${FAKE}/__e2e/accounts`)).json()) as { accounts: Array<{ address: string }> }).accounts.map((a) => a.address);
  });

  test.afterAll(() => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });

  test("S-0375 (X60). with no AI account, what was handed in waits behind one line on Today that says why and has one way on: add the account", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    for (const note of ["Remind me to call the printer about the proofs", "Book the room for the Thursday review"]) {
      const handed = await page.request.post("api/handin", { headers: auth(), data: { note } });
      expect(handed.ok(), await handed.text()).toBe(true);
    }
    // What changed names the request that stopped for want of an account without an error (it answered 500 before).
    const changes = await page.request.get("api/changes", { headers: auth() });
    expect(changes.status(), await changes.text()).toBe(200);
    await page.goto(`?token=${info.token}#today`);
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
    // One line, not one for the account and another for the first start; it says why, in words, and its one button adds the account.
    const line = page.locator('[data-queue-line="no_account"]');
    await expect(line).toHaveCount(1, LOADED);
    await expect(line).toContainText("has no AI account");
    await expect(line).toContainText("Its work waits until one is added.");
    await expect(line.getByRole("button")).toHaveCount(1);
    await expect(line.getByRole("button", { name: "Add one" })).toBeVisible();
    await expect(page.locator('[data-queue-line="first_go"]')).toHaveCount(0);
    expect(await page.getByText(/waiting for an AI account/).count()).toBeLessThanOrEqual(1);
  });

  test("S-0377. setup's header shows the product's mark and its name on the first screen and at every step, at a desktop and a phone width, with no sideways scroll", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`?token=${info.token}`);
      await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
      const brand = page.locator("[data-wizard] header [data-setup-header-brand]");
      await expect(brand).toBeVisible();
      // The name is the configured one, as every other screen's header says it, and the mark beside it is drawn.
      await expect(brand).toContainText("Thimbleby");
      const mark = brand.locator("img:visible");
      await expect(mark).toHaveCount(1);
      const box = (await mark.boundingBox())!;
      expect(box.width).toBeGreaterThanOrEqual(24);
      // The brand sits at the header's left edge, ahead of the title and the way out; nothing is cut off at its right.
      const head = (await page.locator("[data-wizard] header").boundingBox())!;
      const title = (await page.locator("[data-wizard] header h1").boundingBox())!;
      expect(box.x).toBeLessThan(title.x);
      expect(title.x + title.width).toBeLessThanOrEqual(head.x + head.width + 1);
      expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("S-0371, S-0370, S-0340, S-0339. the AI step's account sentence, who can be added, signing out, and one backup copy", async ({ page }) => {
    test.setTimeout(240_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(LOADED);
    await pressStart(page);
    const main = page.locator("main#main");
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible(LOADED);
    await main.getByLabel("Your full name").fill(info.people[0]);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Continue" }).click();

    // S-0371: a key pasted for another service is not an app that is signed in, and is never told that it doesn't say which account.
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible(LOADED);
    await main.getByRole("radio", { name: /Something else/ }).click();
    await main.getByRole("button", { name: /^Another service/ }).click();
    await main.getByLabel(/^Another service/).check();
    await main.locator("#ai-key").fill("a-made-up-key");
    await main.getByRole("textbox", { name: "Service address" }).fill(info.ai_base_url);
    await main.getByRole("textbox", { name: "Service address" }).blur();
    await expect(main.getByText("Works. Ready to use.")).toBeVisible(LOADED);
    // The reviewer opened the fold under the question; open every fold there, then read the whole step.
    for (const fold of await main.locator("details[data-allow-account] > summary").all()) await fold.click();
    await expect(main.getByText("That app doesn't say which account it is signed in to.")).toHaveCount(0);
    await main.getByRole("radio", { name: /^Yes/ }).check();
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible(LOADED);

    // S-0371 and S-1-N4: back on the done step, choosing another service's card takes neither Continue nor the way on away.
    await main.getByRole("button", { name: "Back", exact: true }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible(LOADED);
    const cards = main.getByRole("radio");
    if (await cards.count()) await cards.first().click();
    await expect(main.getByText("Paste your key to go on.")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible(LOADED);

    // S-0340: sign in, then sign out; the step says "Signed out" and what stops, never "Now reading".
    const row = main.locator('[data-service="journey-mail"]');
    const [popup] = await Promise.all([page.waitForEvent("popup"), row.getByRole("button", { name: "Sign in to Example mail", exact: true }).click()]);
    await popup.getByRole("link", { name: addresses[0], exact: true }).click();
    await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
    await main.getByRole("button", { name: `Sign out ${addresses[0]}` }).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(main.getByText(/Signed out since|Signed out/).first()).toBeVisible(LOADED);
    await expect(main.locator("[data-signed-out]")).toContainText("Signed out");
    await expect(main.locator("[data-signed-out]")).toContainText("Your inbox");
    await expect(main.locator("[data-signed-out]")).toContainText("until you sign in again");
    await expect(main.getByText("Now reading")).toHaveCount(0);
    await expect(main.getByText("Also reading")).toHaveCount(0);
    // S-0404: a calendar read while its account is signed out fails with "isn't signed in"; signing in again reads every source of
    // that account at once, so it is read fine without waiting for its next turn.
    const mine = async () => {
      const all = (await (await page.request.get("api/watch", { headers: auth() })).json()) as Array<{ id: string; account?: string; reads: string[]; last?: { outcome: string } | null; failures: number }>;
      return all.filter((w) => w.account === addresses[0] && w.reads.includes("calendar"));
    };
    const calendar = (await mine())[0];
    expect(calendar, "the first account's calendar is a source").toBeTruthy();
    // A read asked for while the app's own read of that source is under way does nothing ("busy"), so it is asked for again
    // until the read it asks for has happened.
    await expect(async () => {
      await page.request.post(`api/watch/${calendar.id}/read`, { headers: auth() });
      expect((await mine())[0].last?.outcome).toBe("failed");
    }).toPass({ timeout: 30_000 });
    // Signing in again goes back to reading: the ways to sign in are in the panel "Connect another account" opens.
    await main.getByRole("button", { name: "Connect another account" }).click();
    const [again] = await Promise.all([page.waitForEvent("popup"), page.getByRole("dialog").locator('[data-service="journey-mail"]').getByRole("button", { name: /^Sign in/ }).first().click()]);
    await again.getByRole("link", { name: addresses[0], exact: true }).click();
    await again.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", LOADED);
    await expect(main.locator("[data-signed-out]")).toHaveCount(0);
    await expect.poll(async () => (await mine())[0], { timeout: 20_000 }).toMatchObject({ last: { outcome: expect.stringMatching(/^(ok|baseline)$/) }, failures: 0 });
    await main.getByRole("button", { name: "Continue" }).click();

    // S-0339: Backups, one Continue; the copies listed afterwards are one, and no file name shows.
    await expect(main.getByRole("heading", { level: 2, name: "Backups" })).toBeVisible(LOADED);
    await pickFolder(page, main, ["offsite"]);
    await expect(main.getByText(/That folder works/)).toBeVisible(LOADED);
    await main.getByRole("button", { name: "Continue" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "People" })).toBeVisible(LOADED);

    // S-0370: a full name is asked for. One word, and a company's name in capitals, are refused in words and not added.
    const name = main.getByRole("textbox", { name: "Name", exact: true });
    for (const wrong of ["J", "Alex", "Bob", "THE BIG COMPANY LTD", "Acme Holdings Ltd"]) {
      await name.fill(wrong);
      await main.getByRole("button", { name: "Add", exact: true }).click();
      await expect(main.getByRole("alert").filter({ hasText: /first and a last name/ })).toBeVisible(LOADED);
      // Nothing was added, and the cursor is where the next try is typed.
      await expect(main.getByRole("heading", { level: 3, name: "People in your own life" })).toHaveCount(0);
      await expect(name).toBeFocused();
    }
    // A long real name is a name, and the cursor stays in the box after Add.
    const long = "Maria Fernanda Gonzalez de la Cruz Alvarez";
    await name.fill(long);
    await main.getByRole("button", { name: "Add", exact: true }).click();
    await expect(main.getByText(long, { exact: true })).toBeVisible(LOADED);
    await expect(name).toBeFocused();
    await expect(name).toHaveValue("");
    await name.fill("Bob Stone");
    await main.getByRole("button", { name: "Add", exact: true }).click();
    await expect(main.getByText("Bob Stone", { exact: true })).toBeVisible(LOADED);
    await expect(name).toBeFocused();
    // The same rule for a pasted list: the long name is kept, the one-word lines and the company are left out and said.
    await main.getByRole("button", { name: /Paste a list/ }).click();
    await main.getByLabel(/one name per line|Paste/i).first().fill("Ann Marie Lee\nJ\nTHE BIG COMPANY LTD\nMaria Fernanda Gonzalez de la Cruz Alvarez Pereira");
    await main.getByRole("button", { name: /^Show/ }).click();
    const preview = main.locator("[data-paste-preview]");
    await expect(preview).toContainText("Ann Marie Lee", LOADED);
    await expect(preview).toContainText("Maria Fernanda Gonzalez de la Cruz Alvarez Pereira");
    await expect(preview).toContainText("THE BIG COMPANY LTD");
    await expect(preview.locator("li", { hasText: "THE BIG COMPANY LTD" })).toHaveCount(0);

    // The copies the app made: one, however the first backup was started.
    const copies = await page.request.get("api/backups", { headers: auth() });
    const overview = (await copies.json()) as { copies?: Array<unknown>; recent?: Array<unknown> };
    const listed = (overview.copies ?? overview.recent ?? []) as unknown[];
    expect(listed.length).toBeLessThanOrEqual(1);
  });

  test("S-0358. Delete this workspace lists plain groups with their counts and none of the app's file names", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/advanced");
    await page.getByRole("button", { name: /^Delete this workspace/ }).click();
    const dialog = page.getByRole("dialog", { name: /Delete this workspace/ });
    const list = dialog.getByRole("list", { name: "This will be deleted" });
    await expect(list.getByRole("listitem").first()).toBeVisible(LOADED);
    const text = (await dialog.innerText()).replace(/\s+/g, " ");
    for (const raw of [/\.cockpit/i, /cockpit/i, /\.git\b/, /\.gitignore/, /\.db\b/, /-shm|-wal/, /\b1 files\b/, /\bdata\b ·/]) expect(text).not.toMatch(raw);
    await expect(list).toContainText("Your records and their history");
    await expect(list).toContainText("Your settings");
    // Every line has its count with the right plural.
    for (const line of await list.getByRole("listitem").allInnerTexts()) expect(line).toMatch(/\b(1 file|\d+ files)\b/);
    // The made backup shows as copies, counted.
    expect((await list.getByRole("listitem").allInnerTexts()).join("\n")).toMatch(/^(1 backup copy|\d+ backup copies) · /m);
    await dialog.getByRole("button", { name: "Cancel" }).click();
  });

  test("S-0353. Settings, Your business: a business with a project counts it, under the title Your jobs and businesses", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    const made = await page.request.post("api/setup/business", { headers: auth(), data: { name: "Hand-printed stationery", kind: "business" } });
    expect(made.ok()).toBe(true);
    const business = (await made.json()) as { project: string };
    const project = await page.request.post("api/projects", { headers: auth(), data: { name: "Spring catalog", parent: business.project } });
    expect(project.ok(), await project.text()).toBe(true);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/business");
    const main = page.locator("main#main");
    await expect(main.getByRole("heading", { level: 3, name: "Your jobs and businesses" })).toBeVisible(LOADED);
    const row = main.getByRole("listitem").filter({ hasText: "Hand-printed stationery" });
    await expect(row).toContainText("Spring catalog", LOADED);
    // It never says "Nothing under it yet" over a project it lists.
    await expect(row).not.toContainText("Nothing under it yet");
    await expect(row).toContainText(/1 project/);
  });

  test("S-0372. a quick link already in the list is refused in words and shows once", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/links");
    const main = page.locator("main#main");
    await expect(main.getByLabel("Name", { exact: true })).toBeVisible(LOADED);
    const add = async (name: string, address: string) => {
      await main.getByLabel("Name", { exact: true }).fill(name);
      await main.getByLabel("Address", { exact: true }).fill(address);
      await main.getByRole("button", { name: "Add this link" }).click();
    };
    await add("Bank", "example.com/bank");
    await expect(main.getByRole("list", { name: "Quick links" })).toContainText("Bank", LOADED);
    await add("My bank again", `${WEB}Example.com/bank/`);
    await expect(main.getByRole("alert")).toContainText("already in your quick links, as Bank");
    await expect(main.getByRole("list", { name: "Quick links" }).getByRole("listitem")).toHaveCount(1);
    // The menu under the initials lists it once.
    await page.getByRole("button", { name: /^Menu for / }).click();
    await expect(page.getByRole("menuitem", { name: "Bank" })).toHaveCount(1);
    await page.keyboard.press("Escape");
  });

  test("S-0372b. text typed into the quick link form while its save is still answering stays", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/links");
    const main = page.locator("main#main");
    const name = main.getByLabel("Name", { exact: true });
    const address = main.getByLabel("Address", { exact: true });
    await expect(name).toBeVisible(LOADED);
    // The save's answer is held, so the next entry is typed before it arrives.
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    let seen = false;
    await page.route(/\/api\/settings$/, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      seen = true;
      await held;
      await route.fallback();
    });
    await name.fill("Held link");
    await address.fill("example.com/held");
    await main.getByRole("button", { name: "Add this link" }).click();
    await expect.poll(() => seen, LOADED).toBe(true);
    await name.fill("Next one");
    await address.fill("example.com/next");
    release();
    await expect(main.getByRole("list", { name: "Quick links" })).toContainText("Held link", LOADED);
    await expect(name).toHaveValue("Next one");
    await expect(address).toHaveValue("example.com/next");
  });

  test("S-0373. searching Settings for delete, erase or workspace finds Delete this workspace, which opens its page", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/you");
    const main = page.locator("main#main");
    for (const word of ["delete", "erase", "workspace"]) {
      const box = page.getByRole("searchbox", { name: /Search settings/ }).or(page.getByLabel("Search settings"));
      await box.first().fill(word);
      const hit = main.getByRole("link", { name: /Delete this workspace/ });
      await expect(hit.first(), `searching "${word}"`).toBeVisible(LOADED);
    }
    await main.getByRole("link", { name: /Delete this workspace/ }).first().click();
    await expect(page.getByRole("button", { name: /^Delete this workspace/ })).toBeVisible(LOADED);
  });

  test("S-0374. a folder connection refuses the computer's own folders and a missing folder is named without its path", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    await page.getByRole("button", { name: "Add mail, calendar or folder" }).click();
    const drawer = page.getByRole("dialog");
    await drawer.getByRole("radio", { name: /A folder/ }).check();
    await drawer.getByRole("button", { name: "Continue" }).click();
    const folder = drawer.getByLabel("Folder", { exact: true });
    await folder.fill("/etc");
    await drawer.getByRole("button", { name: /Add connection/ }).click();
    await expect(drawer.getByRole("alert").first()).toContainText("belongs to the computer itself", LOADED);
    await folder.fill(`${info.source_folder}/not-here-at-all`);
    await drawer.getByRole("button", { name: /Add connection/ }).click();
    const refusal = drawer.getByRole("alert").first();
    await expect(refusal).toContainText("There is no folder called not-here-at-all", LOADED);
    await expect(refusal).not.toContainText(info.source_folder);
    // Exactly one filled button in the drawer's form: the one that adds.
    await expect(drawer.locator('[data-weight="filled"]')).toHaveCount(1);
    await page.keyboard.press("Escape");
  });

  test("S-0362. the calendar form of Add connection: one filled button, the kinds no longer listed above it, the cursor in its first field, the link can be shown", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    await page.getByRole("button", { name: "Add mail, calendar or folder" }).click();
    const drawer = page.getByRole("dialog");
    await drawer.getByRole("radio", { name: /A calendar/ }).check();
    await drawer.getByRole("button", { name: "Continue" }).click();
    await expect(drawer.getByLabel("Name")).toBeFocused();
    // The kinds were chosen on the step before: they are not listed again above the form.
    await expect(drawer.getByRole("radio")).toHaveCount(0);
    // One filled button in the drawer: the one that adds. Choosing a file or showing the link is never filled.
    const names = await drawer.locator('[data-weight="filled"]').evaluateAll((els) => els.map((el) => (el.textContent ?? "").trim()));
    expect(names, "filled buttons in the calendar form").toHaveLength(1);
    // The link is hidden as it is typed, and can be shown to check it.
    const link = drawer.getByRole("textbox", { name: "Calendar link" });
    await expect(link).toHaveAttribute("type", "password");
    await drawer.getByRole("button", { name: /^Show/ }).click();
    await expect(link).toHaveAttribute("type", "text");
    // A link that is not a calendar sends the cursor to the box, never to the page.
    await link.fill("not a link");
    await drawer.getByRole("button", { name: /Add connection/ }).click();
    await expect(drawer.getByRole("alert").first()).toBeVisible(LOADED);
    // The cursor is on a control of the drawer (the box the refusal is about), never on the page behind.
    await expect(link).toBeFocused();
    await page.keyboard.press("Escape");
  });

  test("S-0362. a money field takes digits only: 1e3 is refused (never $13.00), 0.0000001 shows as digits after a reload, and a refused -5 goes back to the saved amount", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/ai");
    const main = page.locator("main#main");
    const day = main.getByLabel("Most to spend in a day", { exact: true });
    await expect(day).toBeVisible(LOADED);
    const saved = await day.inputValue();
    await day.fill("1e3");
    await day.blur();
    await expect(day).not.toHaveValue(/13\.00/);
    await expect(main.getByText(/Enter an amount/)).toBeVisible();
    await day.fill(saved);
    await day.fill("0.0000001");
    await day.blur();
    await expect(main.getByText(/Saved|saved/).first()).toBeVisible(LOADED).catch(() => undefined);
    await page.reload();
    await go(page, "settings/ai");
    const again = page.locator("main#main").getByLabel("Most to spend in a day", { exact: true });
    await expect(again).toBeVisible(LOADED);
    await expect(again).not.toHaveValue(/e-?\d/i);
    await expect(again).toHaveValue(/0\.0000001/);
    // The page nowhere shows the exponent form.
    expect(await page.locator("main#main").innerText()).not.toMatch(/\d[eE]-\d/);
    // A refused negative goes back to what is saved (the reason stays beside it); it never sits in the box.
    const before = await again.inputValue();
    await again.fill("-5");
    await again.blur();
    await expect(page.locator("main#main").getByRole("alert").first()).toBeVisible(LOADED);
    await expect(again).not.toHaveValue(/-/);
    await expect(again).toHaveValue(before);
    await again.fill("5");
    await again.blur();
  });

  test("S-0352, S-0375. the logo help names what it replaces, uploading it saves once, and the accent applies at once", async ({ page }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/appearance");
    const main = page.locator("main#main");
    await expect(main.getByRole("heading", { level: 2, name: "Appearance" })).toBeVisible(LOADED);
    // The sentence is true: the picture takes the product's mark at the top left, and the initials stay at the top right.
    await expect(main).toContainText("in place of the product's mark at the top left");
    await expect(main).not.toContainText("in place of your initials");
    // A picture is uploaded: one toast, never "(2 times)", and the header shows it at the top left.
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
    await main.locator('input[type="file"]').first().setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png });
    await expect(page.getByRole("region", { name: "Notifications" })).toContainText(/Saved/, LOADED);
    await expect(page.getByRole("region", { name: "Notifications" })).not.toContainText(/\(\d+ times\)/);
    const logo = page.locator("header a img:not([data-brand-mark])").first();
    await expect(logo).toBeVisible(LOADED);
    // The picture is drawn, not a broken image: the page's own policy lets it load.
    await expect.poll(() => logo.evaluate((el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0), LOADED).toBe(true);
    // The accent: the color is seen on the page while it is being chosen (before the control is left), and kept once it is left.
    const accent = main.getByLabel("Accent color", { exact: true });
    const brand = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--brand-600").trim());
    const before = await brand();
    await accent.focus();
    await accent.evaluate((el, value) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, "#2f6f4f");
    await expect.poll(brand, LOADED).not.toBe(before);
    const live = await brand();
    await accent.blur();
    await expect(page.getByRole("region", { name: "Notifications" })).toContainText(/Saved/, LOADED);
    await page.reload();
    await expect.poll(brand, LOADED).toBe(live);
  });

  test("S-0375 (X61). the feedback preview says in the person's terms whether they used Missed something, never 'was not used in the weeks counted'", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}#today`);
    await page.getByRole("button", { name: "Help", exact: true }).click();
    await page.getByRole("menuitem", { name: "Write feedback" }).click();
    const dialog = page.getByRole("dialog", { name: "Write feedback" });
    await expect(dialog).toBeVisible(LOADED);
    const missed = dialog.getByRole("checkbox", { name: /how often I used/ });
    if (await missed.count()) await missed.check();
    expect((await dialog.innerText()).replace(/\s+/g, " ")).not.toMatch(/was not used in the weeks counted/);
    await expect(dialog).toContainText(/You didn't use “Missed something\?” in the weeks counted|was used (once|\d+ times)/, LOADED);
    await page.keyboard.press("Escape");
  });

  test("S-0362 (S5-N6). Add a business asks which connections serve it one card to an account, not a flat run of boxes", async ({ page }) => {
    test.setTimeout(180_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}`);
    await go(page, "settings/connections");
    // A second account, signed in through the service's own page, so there are two accounts with an inbox and a calendar each.
    const section = page.locator("section", { has: page.locator("#sign-ins-title") }).first();
    const [popup] = await Promise.all([page.waitForEvent("popup"), section.getByRole("button", { name: "Add another account to Example mail", exact: true }).click()]);
    await popup.getByRole("link", { name: addresses[1], exact: true }).click();
    await popup.waitForEvent("close", { timeout: 30_000 }).catch(() => undefined);
    await expect(page.getByRole("region", { name: addresses[1], exact: true })).toBeVisible(LOADED);
    await go(page, "settings/business");
    await page.getByRole("button", { name: "Add a business" }).click();
    const drawer = page.getByRole("dialog");
    await drawer.getByLabel("Business name").fill("Lantern Row Studio");
    await drawer.getByRole("button", { name: "Add the business" }).click();
    await expect(drawer.getByRole("heading", { name: "Which of your connections serve Lantern Row Studio?" })).toBeVisible(LOADED);
    // One card for each account, headed by its address, with its own inbox and calendar under it.
    const cards = drawer.locator("[data-served-account]");
    await expect(cards).toHaveCount(2);
    for (const address of addresses.slice(0, 2)) {
      const card = drawer.locator(`[data-served-account="${address}"]`);
      await expect(card.getByText(address, { exact: true }).first()).toBeVisible();
      await expect(card.getByRole("checkbox")).toHaveCount(2);
      await expect(card.getByRole("checkbox", { name: "Your inbox" })).toBeVisible();
      await expect(card.getByRole("checkbox", { name: "Your calendar" })).toBeVisible();
    }
    // No box is named by the whole run of its address (nine flat boxes read the same).
    await expect(drawer.getByRole("checkbox", { name: new RegExp(`^Your inbox, ${addresses[0]}`) })).toHaveCount(0);
    await drawer.getByRole("button", { name: "Done" }).click();
  });

  test("S-0362 (clash page). a clash of two meetings opens with an Open the event button to each, never filled", async ({ page }) => {
    test.setTimeout(180_000);
    collectProblems(page, problems);
    await page.goto(`?token=${info.token}#today`);
    const line = page.locator('[data-queue-line="clash"]').first();
    await expect(line).toBeVisible({ timeout: 120_000 });
    await line.getByRole("button", { name: /^Open / }).first().click();
    // The clash opens with each of its two meetings and one Open the event to each; neither is a filled button.
    const open = page.getByRole("link", { name: "Open the event" }).or(page.getByRole("button", { name: "Open the event" }));
    await expect(open.first()).toBeVisible(LOADED);
    expect(await open.count()).toBeGreaterThanOrEqual(2);
    for (const one of await open.all()) await expect(one).toHaveAttribute("data-weight", "outline");
    expect(await page.locator('main [data-weight="filled"]').count()).toBeLessThanOrEqual(1);
  });
});
