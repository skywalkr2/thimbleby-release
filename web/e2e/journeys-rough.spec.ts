// The screens' failure paths, from a person's first evening on a fresh install. Each test here reproduces one reported
// failure and is marked as an expected failure (`test.fail`) with the line's id
// and what is wrong today; when the fix lands the test passes, Playwright reports the mark as wrong, and the fixer removes it.
//
// One workspace made by the init command with no template, started as the new-start journey starts it: the mail add-on is
// installed from the catalog (which restarts the app once), beside fakes that play the outside services. A person walks the
// walkthrough pressing only Continue and "I'll do this later", opens Today, presses Start once, then does what a person does on the
// screens after it. The walk only records what it saw; each line below asserts on what was recorded, so one line's failure never
// hides another's. Names come from the fictional workspace the fake services serve, never written out here.
import { expect, type Locator, type Page } from "@playwright/test";
import { followServer, test } from "./test";
import {
  collectProblems,
  fakeAddress,
  pressStart,
  settingsSections,
  type Info,
  type Requests,
  FIRST_SCREEN,
} from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_ROUGH_FAKE_PORT", 8741);
const LOADED = { timeout: 20_000 };

let info: Info;
let page: Page;
const problems: string[] = [];

const requests = async (): Promise<Requests> => (await fetch(`${FAKE}/__e2e/ai-requests`)).json();

/** The narrowest a step's name is drawn in the step list, in characters, at the width the page was measured at. */
interface RailReading {
  screen: string;
  label: string;
  narrowest: number;
}

interface Seen {
  /** The heading of the step the Continue on Mail and calendar went to. */
  afterMail: string;
  /** The names of the steps in the step list when the walk reached People. */
  railNames: string[];
  /** The step list's narrowest name at each step from the one after Mail and calendar on. */
  rail: RailReading[];
  /** What the last screen says about each step: its row's text, by step. */
  recap: Record<string, string>;
  /** The last screen's heading. */
  recapHeading: string;
  /** Every sign the app was offline that the page showed while it restarted for the mail add-on. */
  offline: string[];
  /** Pick-lists that took typed letters in a text box, in the steps and on the screens of Settings. */
  typedInto: string[];
  /** How many presses of the one Start it took before the assistant began (or 0 if it never did). */
  startPresses: number;
  /** What Today drew while the first read arrived: a "Show N new items" button over another line, and empty cards. */
  overlaps: string[];
  emptyCards: string[];
  /** Whether Today went on to draw the lines the read found. */
  foundLines: number;
}

const seen: Seen = {
  afterMail: "",
  railNames: [],
  rail: [],
  recap: {},
  recapHeading: "",
  offline: [],
  typedInto: [],
  startPresses: 0,
  overlaps: [],
  emptyCards: [],
  foundLines: 0,
};

/** Opens every pick-list inside `scope`, types two letters that match nothing and reports each one that took them in a text
 * box: a list to pick from must not look like, or act as, a field to type in (the Thimbleby UI rules). */
async function typeIntoPickLists(scope: Locator, where: string): Promise<string[]> {
  const found: string[] = [];
  const lists = scope.locator('[data-ui="select"]:visible');
  const count = await lists.count();
  for (let i = 0; i < count; i++) {
    const list = lists.nth(i);
    if (!(await list.isEnabled())) continue;
    const name = await list.evaluate(
      (el) => el.getAttribute("aria-label") ?? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() ?? el.id ?? "a list",
    );
    await list.click();
    const panel = page.locator("[data-select-panel]");
    await panel.waitFor(LOADED);
    await page.keyboard.type("zq");
    const typed = await panel.locator('input[type="text"]').evaluateAll((boxes) => boxes.map((b) => (b as HTMLInputElement).value).filter(Boolean));
    if (typed.length > 0) found.push(`${where}: "${name}" took "${typed.join(",")}" typed into a text box`);
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "detached", timeout: 5000 });
  }
  // A list written as a box (the time zone is one): the same two letters go into it, and are taken out again.
  const boxes = scope.locator('input[role="combobox"][type="text"]:visible');
  for (let i = 0; i < (await boxes.count()); i++) {
    const box = boxes.nth(i);
    if (!(await box.isEnabled()) || (await box.evaluate((el) => !!el.closest("[data-select-panel]")))) continue;
    const name = await box.evaluate((el) => el.getAttribute("aria-label") ?? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() ?? el.id ?? "a list");
    const before = await box.inputValue();
    await box.click();
    await page.keyboard.type("zq");
    const after = await box.inputValue();
    if (after.includes("zq")) found.push(`${where}: "${name}" took "zq" typed into a text box`);
    for (let k = 0; k < 2; k++) await page.keyboard.press("Backspace");
    await page.keyboard.press("Escape");
    if ((await box.inputValue()) !== before) await box.fill(before);
    await box.blur();
  }
  return found;
}

/** The narrowest each step's name is drawn in the step list, in characters of its own font. */
async function readRail(screen: string): Promise<RailReading[]> {
  // A step the person has passed by says so beside its name once the setup state has been read again; measure after it has.
  const passed = page.locator('nav button[data-screen="promises"]');
  if (screen !== "Your promises" && (await passed.count()) > 0) {
    await passed.locator("span[class*=exception]").waitFor({ state: "visible", timeout: 5000 }).catch(() => undefined);
  }
  const readings = await page.evaluate(() => {
    const canvas = document.createElement("canvas").getContext("2d")!;
    return Array.from(document.querySelectorAll<HTMLElement>("nav button[data-screen]")).map((button) => {
      const name = button.querySelector<HTMLElement>("span[class*=label] > span") ?? button;
      const box = name.getBoundingClientRect();
      const style = getComputedStyle(name);
      canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const char = canvas.measureText("n").width || 8;
      return { screen: button.getAttribute("data-screen") ?? "", label: (name.textContent ?? "").trim(), narrowest: Math.round((box.width / char) * 10) / 10 };
    });
  });
  return readings.map((r) => ({ ...r, screen: `${screen} > ${r.screen}` }));
}

test.describe.serial("rough paths: a fresh install, pressing only Continue and skip", () => {
  test.beforeAll(async () => {
    info = await (await fetch(`${FAKE}/__e2e/info`)).json();
  });
  test.afterAll(async () => {
    await page?.context().close();
  });

  test("the walk: a fresh workspace from Welcome to Today, pressing only Continue and I'll do this later", async ({ browser }, testInfo) => {
    test.setTimeout(420_000);
    const baseURL = (testInfo.project.use as { baseURL: string }).baseURL;
    const context = await browser.newContext({ baseURL, ignoreHTTPSErrors: true, permissions: ["clipboard-read", "clipboard-write"], reducedMotion: "reduce" });
    await followServer(context, baseURL);
    page = await context.newPage();
    collectProblems(page, problems);
    await page.setViewportSize({ width: 1280, height: 900 });
    // Sees every sign of "offline" the page shows, whatever its length: the banner, or the header's status saying Offline.
    await page.addInitScript(() => {
      const w = window as unknown as { __offline: string[] };
      w.__offline = [];
      const look = () => {
        if (document.querySelector("[data-offline-banner]")) w.__offline.push("the offline bar");
        for (const el of Array.from(document.querySelectorAll("button[aria-label^='App status: ']"))) {
          const label = el.getAttribute("aria-label") ?? "";
          if (/Offline|Connecting/.test(label)) w.__offline.push(label);
        }
      };
      new MutationObserver(look).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    });
    await page.goto(`?token=${info.token}`);
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
    await pressStart(page);
    const main = page.locator("main#main");

    // You: the name, and the time zone is a list.
    await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible();
    await main.getByLabel("Your full name").fill(info.people[0]);
    seen.typedInto.push(...(await typeIntoPickLists(main, "the You step")));
    await main.getByRole("button", { name: "Continue" }).click();
    // What it's for: Just me is chosen.
    await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible();
    await main.getByRole("button", { name: "Continue" }).click();
    // An AI account, as the journeys have it.
    await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible();
    await main.getByRole("radio", { name: /Something else/ }).check();
    await main.getByRole("button", { name: /^Another service/ }).click();
    await main.getByLabel(/^Another service/).check();
    await main.locator("#ai-key").fill("a-made-up-key");
    await main.getByRole("textbox", { name: "Service address" }).fill(info.ai_base_url);
    await main.getByRole("textbox", { name: "Service address" }).blur();
    await expect(main.getByText("Works. Ready to use.")).toBeVisible();
    await main.getByRole("radio", { name: /^Yes/ }).check();
    await main.getByRole("button", { name: "Continue" }).click();
    // Mail and calendar: one click installs the add-on and restarts the app; the sign-in is in its own window.
    await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible({ timeout: 30_000 });
    const row = main.locator('[data-service="journey-mail"]');
    // The page said "Connecting…" while it first opened, which is not the restart: what is looked for starts here, at the click that restarts.
    await page.evaluate(() => {
      (window as unknown as { __offline: string[] }).__offline = [];
    });
    await row.getByRole("button", { name: /^Connect Example mail/ }).click();
    const signIn = main.getByRole("button", { name: "Sign in to Example mail", exact: true });
    await expect(signIn).toBeVisible({ timeout: 120_000 });
    seen.offline.push(...(await page.evaluate(() => (window as unknown as { __offline: string[] }).__offline)));
    const [popup] = await Promise.all([page.waitForEvent("popup", { timeout: 60_000 }), signIn.click()]);
    await popup.waitForEvent("close", { timeout: 60_000 }).catch(() => undefined);
    await expect(main.locator("[data-mail-result]")).toContainText("Example mail is connected.", { timeout: 90_000 });
    seen.offline.push(...(await page.evaluate(() => (window as unknown as { __offline: string[] }).__offline)));
    await main.getByRole("button", { name: "Continue" }).click();

    // The step after mail. Whatever it is, the step list is read on it and on every step after it, and Continue is pressed.
    const heading = main.getByRole("heading", { level: 2 });
    await expect(heading).not.toHaveText("Mail and calendar", LOADED);
    seen.afterMail = (await heading.innerText()).trim();
    seen.railNames = (await page.locator("nav button[data-screen]").allInnerTexts()).map((t) => t.split("\n")[0].trim());
    seen.rail.push(...(await readRail(seen.afterMail)));
    if (seen.afterMail === "Your promises") {
      await main.getByRole("button", { name: "Continue" }).click();
      await expect(heading).not.toHaveText("Your promises", LOADED);
    }
    // Backups, then People: each is passed by.
    for (const step of ["Backups", "People"]) {
      await expect(heading).toHaveText(step, LOADED);
      seen.rail.push(...(await readRail(step)));
      await main.getByRole("button", { name: "I'll do this later" }).click();
    }
    // The last screen.
    await expect(heading).toHaveText(/^(Done|Where things stand|You're set\.?)$/, LOADED);
    seen.recapHeading = (await heading.innerText()).trim();
    seen.rail.push(...(await readRail("the last screen")));
    const recap = main.getByRole("list", { name: "What was set up" });
    for (const li of await recap.locator("[data-step]").all()) {
      seen.recap[(await li.getAttribute("data-step")) ?? ""] = ((await li.innerText()) ?? "").replace(/\s+/g, " ").trim();
    }
    await main.getByRole("button", { name: "Go to Today" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
  });

  test("Today: Start is pressed once, and what arrives is watched", async () => {
    test.setTimeout(240_000);
    const line = page.locator('[data-queue-line="first_go"], [data-queue-line="intake_go"]');
    await expect(line.first()).toBeVisible({ timeout: 60_000 });
    // From here every change to the page is looked at for a "Show N new items" button drawn over another line, and for a card with nothing in it.
    await page.evaluate(() => {
      const w = window as unknown as { __today: { overlaps: string[]; empty: string[] } };
      w.__today = { overlaps: [], empty: [] };
      let waiting = false;
      const look = () => {
        waiting = false;
        const buttons = Array.from(document.querySelectorAll<HTMLElement>("button")).filter((b) => /^Show \d+ new items?$/.test((b.textContent ?? "").trim()));
        const lines = Array.from(document.querySelectorAll<HTMLElement>("[data-queue-line]"));
        for (const b of buttons) {
          const a = b.getBoundingClientRect();
          for (const l of lines) {
            if (l.contains(b)) continue;
            const r = l.getBoundingClientRect();
            const across = Math.min(a.right, r.right) - Math.max(a.left, r.left);
            const down = Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top);
            if (across > 2 && down > 2) w.__today.overlaps.push(`"${(b.textContent ?? "").trim()}" over ${l.getAttribute("data-queue-line")} by ${Math.round(down)}px`);
          }
        }
        for (const l of lines) {
          const r = l.getBoundingClientRect();
          if (r.height > 0 && (l.textContent ?? "").trim() === "") w.__today.empty.push(`${l.getAttribute("data-queue-line")} has no words`);
        }
        for (const card of Array.from(document.querySelectorAll<HTMLElement>("main section, main [role=region]"))) {
          const r = card.getBoundingClientRect();
          if (r.height > 0 && (card.textContent ?? "").trim() === "") w.__today.empty.push(`a ${card.tagName.toLowerCase()} card has no words`);
        }
      };
      new MutationObserver(() => {
        if (!waiting) {
          waiting = true;
          requestAnimationFrame(look);
        }
      }).observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
    });
    // One press of the first Start; "it began" is that Start leaving or the assistant being asked something. The line is found
    // again at each press, not by its key: while the first read arrives the same line may be redrawn as another kind of line
    // (the first Start, then the intake's), and a press on a line that has gone says nothing about whether Start works.
    const pressable = line.getByRole("button", { name: "Start", exact: true });
    for (let press = 1; press <= 4 && seen.startPresses === 0; press++) {
      const before = await pressable.count();
      if (before === 0) break;
      await pressable.first().click({ timeout: 15_000 });
      const began = await expect
        .poll(async () => (await pressable.count()) < before || (await requests()).work > 0, { timeout: 8000 })
        .toBe(true)
        .then(
          () => true,
          () => false,
        );
      if (began) seen.startPresses = press;
    }
    // The rest of the Starts (one for each source) are pressed as the journeys do, so the look back is read. Only a line that holds a
    // Start button is pressed; one that is working, or one the list keeps in place behind "Show N new items", is left.
    const starts = page.locator('[data-queue-line="first_go"], [data-queue-line="intake_go"]').getByRole("button", { name: "Start", exact: true });
    for (let round = 0; round < 6 && (await starts.count()) > 0; round++) {
      const before = await starts.count();
      // A line seen a moment ago may have been settled since (the list redraws as sources are read): a press that failed because its
      // Start went away is not a fault, and the next round looks again. A Start still there that can't be pressed is.
      const failed = await starts.first().click({ timeout: 15_000 }).then(
        () => null,
        (error: unknown) => error,
      );
      if (failed) {
        if ((await starts.count()) < before) continue;
        throw failed;
      }
      await expect.poll(async () => (await starts.count()) !== before, { timeout: 30_000 }).toBe(true);
    }
    // What was found is lines to look over; they may wait behind "Show N new items" while the cursor is in the list.
    const found = page.locator('[data-queue-line="intake_review"]');
    await expect.poll(async () => (await found.count()) + (await page.getByRole("button", { name: /^Show \d+ new items?$/ }).count()), { timeout: 120_000 }).toBeGreaterThan(0);
    seen.foundLines = await found.count();
    const today = await page.evaluate(() => (window as unknown as { __today: { overlaps: string[]; empty: string[] } }).__today);
    seen.overlaps = today.overlaps;
    seen.emptyCards = today.empty;
  });

  // ----- The lines -----

  test("U4 8: the walkthrough has no step that only explains and does nothing (Your promises)", async () => {
    expect(seen.afterMail).not.toBe("Your promises");
    expect(seen.railNames.join("|")).not.toContain("Your promises");
  });

  test("U4 9: the step list draws every step's name in a column wide enough to read, on every step after Mail and calendar", async () => {
    if (process.env.U4_SHOW_REASON) console.log(`RAIL ${JSON.stringify(seen.rail)}`);
    const narrow = seen.rail.filter((r) => r.narrowest < 8).map((r) => `${r.screen}: "${r.label}" ${r.narrowest} characters wide`);
    expect(narrow, "the narrowest column of each step's name, under 8 characters wide").toEqual([]);
  });

  test("U4 12: the last screen has no row for a step that has nothing to set up, so the walkthrough can end clean", async () => {
    expect(seen.recap["promises"], "a row for the promises step").toBeUndefined();
    // Nothing in the summary is set to be 'Set up' by a step the person cannot do anything in.
    expect(Object.values(seen.recap).join(" | ")).not.toContain("Starts when you press Start on Today");
  });

  test("U4 6: the restart for the mail add-on is not shown as offline and then online", async () => {
    expect([...new Set(seen.offline)]).toEqual([]);
  });

  // Passes today in this setup (one press began the assistant), so it is kept as a plain test and not marked.
  test("U4 13: Start works with one press", async () => {
    expect(seen.startPresses, "presses of Start before the assistant began (0 = it never did)").toBe(1);
  });

  test("U4 14: nothing on Today is drawn over another line, and no card is empty, while the first read arrives", async () => {
    expect({ overlaps: [...new Set(seen.overlaps)], empty: [...new Set(seen.emptyCards)] }).toEqual({ overlaps: [], empty: [] });
  });

  test("U4 21: a message about what was done on one screen is gone when the person moves on", async () => {
    await page.evaluate(() => {
      window.location.hash = "work/open";
    });
    await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "To-dos and questions" })).toBeVisible(LOADED);
    const field = page.getByRole("textbox", { name: "Add a to-do" });
    await field.fill("A to-do with no day yet");
    await field.press("Enter");
    const toasts = page.getByRole("region", { name: "Notifications" });
    await expect(toasts).toContainText("Added: A to-do with no day yet", LOADED);
    // A person reads the message before moving on: a message shown in the instant of a move is about that move (0.4 s) and stays.
    await page.waitForTimeout(600);
    // Moving on to the setup page (where such a message was seen to stay) and to a Settings page.
    await page.evaluate(() => {
      window.location.hash = "setup";
    });
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(LOADED);
    await expect(toasts.getByText(/^Added: /)).toHaveCount(0, { timeout: 3000 });
  });

  test("U4 18: a to-do with no date is listed with a date to pick beside it, not behind a link", async () => {
    await page.evaluate(() => {
      window.location.hash = "work/open";
    });
    await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "To-dos and questions" })).toBeVisible(LOADED);
    // The to-do is added in the 21 test; add one here only if it is not there, so this one stands alone.
    const list = page.getByRole("list", { name: "Open to-dos" });
    if ((await list.getByText("A to-do with no day yet").count()) === 0 && (await page.getByText("A to-do with no day yet").count()) === 0) {
      const field = page.getByRole("textbox", { name: "Add a to-do" });
      await field.fill("A to-do with no day yet");
      await field.press("Enter");
    }
    await expect(page.locator("[data-needs-date-line], [data-needs-date]").first()).toBeVisible(LOADED);
    const row = page.getByRole("listitem").filter({ hasText: "A to-do with no day yet" }).last();
    await expect(row).toBeVisible({ timeout: 3000 });
    await expect(row.getByLabel(/^Date for /)).toBeVisible({ timeout: 3000 });
  });

  test("U4 5: an account added in Settings is tested at once, with no button to press", async () => {
    await page.evaluate(() => {
      window.location.hash = "settings/ai";
    });
    const section = page.getByRole("region", { name: /^AI accounts/ });
    await expect(section.getByRole("heading", { name: /^AI accounts/ })).toBeVisible(LOADED);
    await section.getByRole("button", { name: "Add an account" }).click();
    const drawer = page.getByRole("dialog", { name: "Add an account" });
    await expect(drawer).toBeVisible(LOADED);
    await drawer.getByText("More options", { exact: true }).first().click();
    await drawer.getByRole("radio", { name: /Another service/ }).check();
    await drawer.locator("#ai-key").fill("a-made-up-key-2");
    const address = drawer.getByRole("textbox", { name: "Service address" });
    if (await address.count()) await address.fill(info.ai_base_url);
    await drawer.getByRole("button", { name: "Check", exact: true }).click();
    // Checking the key lists its models, and the rest of the form (its name, what it is for) comes with them.
    await expect(drawer.getByLabel("Name it")).toBeVisible({ timeout: 30_000 });
    await drawer.getByLabel("Name it").fill("Second account");
    // An account added to keep and try is "Nothing yet".
    await drawer.getByRole("radio", { name: /Nothing yet/ }).check();
    seen.typedInto.push(...(await typeIntoPickLists(drawer, "the Add an account drawer")));
    await drawer.getByRole("button", { name: "Add account" }).click();
    await expect(drawer).toBeHidden(LOADED);
    const added = section.locator("li[data-row]").filter({ hasText: "Second account" });
    await expect(added).toBeVisible(LOADED);
    // Tested at once: it does not say it waits, and the person is not given a Test button to press.
    await expect(added).not.toContainText("Not tested yet", { timeout: 20_000 });
    await expect(added.getByRole("button", { name: /^Test /, exact: false })).toHaveCount(0);
  });

  test("U4 1: nothing is typed into a text box in any pick-list in setup or Settings", async () => {
    test.setTimeout(300_000);
    await page.evaluate(() => {
      window.location.hash = "settings/you";
    });
    const links = await (await settingsSections(page)).getByRole("link").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""));
    expect(links.length).toBeGreaterThan(3);
    for (const href of links) {
      await page.evaluate((h) => {
        window.location.hash = h.split("#").pop() ?? "";
      }, href);
      await expect(page.locator("main [data-skeleton]")).toHaveCount(0, LOADED);
      await expect(page.locator("main h2").first(), `a heading on ${href}, at ${page.url()}`).toBeVisible(LOADED);
      seen.typedInto.push(...(await typeIntoPickLists(page.locator("main"), `Settings ${href}`)));
    }
    expect([...new Set(seen.typedInto)]).toEqual([]);
  });

  test("U4 Settings search: the cursor stays in the search box while the next page loads slowly", async () => {
    // A page opened fresh, where the answer about the person (what the You page waits for) is held back, as it is on a slow or busy computer.
    const slow = await page.context().newPage();
    try {
      await slow.route("**/api/me", async (route) => {
        await new Promise((done) => setTimeout(done, 4000));
        await route.continue();
      });
      await slow.goto(`?token=${info.token}#settings/connections`);
      await expect(slow.getByRole("heading", { level: 2, name: "Connections", exact: true })).toBeVisible(LOADED);
      const search = slow.getByRole("searchbox", { name: "Search settings" });
      await search.click();
      // A person types at their own speed: the page changes after the first letters, and the rest keep coming.
      await slow.keyboard.type("time zone", { delay: 100 });
      await expect.poll(() => new URL(slow.url()).hash, LOADED).toBe("#settings/you");
      const box = slow.getByRole("searchbox", { name: "Search settings" });
      await expect(box).toHaveValue("time zone", LOADED);
      await expect(box).toBeFocused();
    } finally {
      await slow.close();
    }
  });

  test("the browser reported nothing wrong", () => {
    expect(problems.filter((p) => !p.includes("Failed to load resource"))).toEqual([]);
  });
});
