// The shell and the visual system (design 7.1, 7.11-7.13) in a real browser: the style guide and Today in light and dark at four
// widths with accessibility checks, how much of the screen the content uses, a header that never wraps, views that are links,
// the offline state, and the phone's bottom bar. Screenshots go to the folder named by E2E_SHOTS, when it is set.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choicesOf, choose } from "./choose";
import { pressStart, showSteps, FIRST_SCREEN } from "./journey-helpers";
import { openScreen, screenReady } from "./open-screen";

/** The assistant's configured name, as the app reports it. */
async function assistantName(page: Page): Promise<string> {
  const response = await page.request.get("api/runtime-config");
  expect(response.ok()).toBe(true);
  return (await response.json()).assistant_name;
}

async function signIn(page: Page, hash = "") {
  await openScreen(page, hash);
}

/** A save, an Undo and the reload after them are several requests; a computer that is busy takes longer than a screen's own wait. */
const SAVED = { timeout: 20_000 };

async function shoot(page: Page, name: string) {
  const folder = process.env.E2E_SHOTS;
  if (folder) await page.screenshot({ path: `${folder}/${name}.png`, fullPage: false });
}

async function expectNoViolations(page: Page) {
  // The header sticks to the top, so what it covers depends on the scroll position; check from the top.
  await page.evaluate(() => window.scrollTo(0, 0));
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const found = results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(found).toEqual([]);
}

/** Resolves when the page's height has stayed the same for a run of drawn frames (counted in frames, so a slow machine
 * simply takes longer): a screen that is still loading rows keeps changing its height. */
async function layoutSettled(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        let height = -1;
        let same = 0;
        const frame = () => {
          const now = document.documentElement.scrollHeight;
          same = now === height ? same + 1 : 0;
          height = now;
          if (same >= 20) resolve();
          else requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }),
  );
}

const WIDTHS = [390, 1024, 1440, 1920];
const HEIGHT = 900;

test.describe("the visual system", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`the style guide passes the accessibility checks in ${scheme} at every width`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signIn(page);
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: HEIGHT });
        await page.evaluate(() => {
          window.location.hash = "styleguide";
        });
        await screenReady(page);
        await expect(page.getByRole("heading", { level: 1, name: "Style guide" })).toBeVisible();
        await expect(page.locator("html")).toHaveCSS("color-scheme", scheme);
        await expectNoViolations(page);
        await shoot(page, `styleguide-${scheme}-${width}`);
      }
    });

    test(`Today passes the accessibility checks in ${scheme} at every width`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signIn(page);
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: HEIGHT });
        await page.evaluate(() => {
          window.location.hash = "today";
        });
        await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
        await expect(page.getByRole("heading", { level: 2, name: "Needs you" })).toBeVisible();
        await expectNoViolations(page);
        await shoot(page, `today-${scheme}-${width}`);
      }
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    test(`the setup walkthrough passes the accessibility checks in ${scheme} at every width, with no sideways scrolling`, async ({
      page,
    }) => {
      // Four widths, each loading the walkthrough and running the accessibility checks on four of its screens: the checks walk
      // the whole page, so a busy computer needs more than the default minute.
      test.setTimeout(180_000);
      await page.emulateMedia({ colorScheme: scheme });
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: HEIGHT });
        await signIn(page, "setup");
        await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
        // A fresh start opens on Welcome, which has no step list; it passes the checks too, then Start goes on.
        await expectNoViolations(page);
        await pressStart(page);
        const screens = page.getByRole("navigation", { name: "Setup steps" });
        for (const name of [/^Your AI account/, /^Mail and calendar/, /^(Done|Where things stand)/]) {
          // On a phone the list is behind the Steps button, and closes once a step is chosen.
          await showSteps(page);
          await screens.getByRole("button", { name }).click();
          await expectNoViolations(page);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        }
        await shoot(page, `walkthrough-${scheme}-${width}`);
      }
    });
  }

  test("the style guide's theme toggle switches the whole page", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.setViewportSize({ width: 1440, height: HEIGHT });
    await signIn(page, "styleguide");
    const theme = page.getByRole("radiogroup", { name: "Show the page in" });
    await theme.getByRole("radio", { name: "Night" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("html")).toHaveCSS("color-scheme", "dark");
    await expectNoViolations(page);
    await shoot(page, "styleguide-toggle-dark");
    await theme.getByRole("radio", { name: "Day" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expectNoViolations(page);
    // The toggle shows a theme without changing what this device remembers.
    expect(await page.evaluate(() => window.localStorage.getItem("cockpit:theme"))).toBeNull();
  });

  test("the user menu's theme and density are kept for this device", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: HEIGHT });
    await signIn(page);
    await page.getByRole("button", { name: /^Menu for / }).click();
    await page.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name: "Night" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    // The choice acts at once and the menu stays open for the next one.
    await page.getByRole("radiogroup", { name: "Spacing" }).getByRole("radio", { name: "Compact" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
    await expectNoViolations(page);
    await shoot(page, "today-dark-compact-1440");
  });

  test("the style guide has every shared component in every state", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: HEIGHT });
    await signIn(page, "styleguide");
    for (const section of ["Type scale", "Color roles", "Buttons", "Pills and the status chip", "Rows", "Segmented control", "Empty, loading and failed", "Drawer, dialog, menu and toast", "Form controls", "A record's page", "A setup step's footer", "Evidence", "Icons"]) {
      await expect(page.getByRole("heading", { level: 2, name: section })).toBeVisible();
    }
    // A disabled button says why, and is not shown by opacity alone.
    const disabled = page.getByRole("button", { name: "Primary", disabled: true }).first();
    await expect(disabled).toBeDisabled();
    await expect(disabled).toHaveAccessibleDescription("Pick a person first.");
    await expect(disabled).toHaveCSS("opacity", "1");
    // The drawer asks before it discards typed text, and focus returns to its opener.
    const opener = page.getByRole("button", { name: "Open a drawer" });
    await opener.click();
    const drawer = page.getByRole("dialog", { name: "Add a person" });
    await drawer.getByLabel("Notes").fill("Something typed");
    await page.keyboard.press("Escape");
    await expect(drawer.getByRole("alert")).toContainText("Discard what you typed?");
    await drawer.getByRole("button", { name: "Discard" }).click();
    await expect(drawer).toHaveCount(0);
    await expect(opener).toBeFocused();
    // The dialog closes with Escape and returns focus too.
    const dialogOpener = page.getByRole("button", { name: "Open a dialog" });
    await dialogOpener.click();
    await expect(page.getByRole("dialog", { name: "Delete this draft?" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(dialogOpener).toBeFocused();
    // A toast sits at the bottom center of the window whatever the navigation does, in one line, with an icon.
    await page.getByRole("button", { name: "Show a toast" }).click();
    const notices = page.getByRole("region", { name: "Notifications" });
    const toast = notices.getByText("Marked as sent to Sample Person");
    await expect(toast).toBeVisible();
    const box = (await toast.boundingBox())!;
    const region = (await notices.boundingBox())!;
    expect(Math.abs(region.x + region.width / 2 - 1440 / 2)).toBeLessThan(2);
    expect(region.width).toBeGreaterThanOrEqual(360);
    expect(region.width).toBeLessThanOrEqual(420);
    expect(box.height).toBeLessThan(30);
    expect(box.y).toBeGreaterThan(HEIGHT - 150);
    // On a phone it is above the bottom bar.
    await page.setViewportSize({ width: 390, height: HEIGHT });
    await expect(toast).toBeVisible();
    // The window was just resized: wait for the navigation to have moved to the bottom bar, then read both boxes in one frame.
    const views = page.getByRole("navigation", { name: "Views" });
    // While it moves it may be off the page for a frame: no box yet counts as not there.
    await expect.poll(async () => (await views.boundingBox())?.y ?? -1).toBeGreaterThan(HEIGHT / 2);
    await expect
      .poll(async () => {
        const bar = (await views.boundingBox())!;
        const phone = (await toast.boundingBox())!;
        return { centered: Math.abs(phone.x + phone.width / 2 - 390 / 2) < 100, above: phone.y + phone.height <= bar.y };
      })
      .toEqual({ centered: true, above: true });
  });

  // WCAG 2.4.11 (axe does not check it): with a toast showing (one at a time, the newest replacing the one before), no control the
  // cursor reaches is hidden under it.
  for (const width of [390, 1440]) {
    test(`with a toast showing, Tab never leaves a control under it at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: HEIGHT });
      await signIn(page, "styleguide");
      await page.getByRole("button", { name: "Show three toasts" }).click();
      const notices = page.getByRole("region", { name: "Notifications" });
      // Three were pushed and one shows: the newest replaced the others.
      await expect(notices.getByRole("button", { name: "Dismiss" })).toHaveCount(1);
      // Even with several buttons the words keep a width that reads: the buttons wrap under them.
      expect((await notices.getByText("Added Sample Project").boundingBox())!.width).toBeGreaterThan(150);
      await page.getByRole("heading", { level: 1 }).first().focus();
      const hidden: string[] = [];
      for (let i = 0; i < 400; i++) {
        await page.keyboard.press("Tab");
        const covered = await page.evaluate(() => {
          const active = document.activeElement as HTMLElement | null;
          const region = document.querySelector("[data-toast-region]");
          if (!active || !region || region.contains(active)) return null;
          const r = active.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return null;
          const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return top && region.contains(top) ? (active.getAttribute("aria-label") ?? active.textContent ?? active.tagName).trim().slice(0, 40) : null;
        });
        if (covered) hidden.push(covered);
        if (await page.evaluate(() => document.activeElement === document.body)) break;
      }
      expect(hidden).toEqual([]);
    });
  }
});

test.describe("screen use and the shell", () => {

  // The first-go line is a line of the queue (design 7.8); the walkthrough's last button focuses it, and Go must then be
  // fully on the screen, not clipped.
  for (const [width, height] of [
    [1280, 720],
    [390, 844],
  ]) {
    test(`after the walkthrough's last button, the first-go line's Go button is fully visible at ${width}×${height}`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      // Three runs wait for the first go, one of them with no price: the queue has one line for them.
      await page.route("**/api/today/queue", async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          json: [
            { key: "first_go", group: "decide", kind: "first_go", count: 3, estimate_usd: 0.3, unpriced: 1, untrusted: false, actions: [], questions: [], outcome: {} },
          ],
        });
      });
      await signIn(page, "setup");
      await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
      await pressStart(page);
      await showSteps(page);
      await page.getByRole("navigation", { name: "Setup steps" }).getByRole("button", { name: /^(Done|Where things stand)/ }).click();
      await page.getByRole("main").getByRole("button", { name: "Go to Today" }).click();
      const line = page.locator('[data-queue-line="first_go"]');
      // The cursor goes to the line once Today has drawn it, which a busy computer takes longer over than the default wait.
      await expect(line).toBeFocused(FIRST_SCREEN);
      await expect(line).toBeInViewport({ ratio: 1 });
      await expect(line.getByRole("button", { name: "Start", exact: true })).toBeInViewport({ ratio: 1 });
      await shoot(page, `first-go-${width}`);
    });
  }

  // A toast sits at the bottom of the window; while the walkthrough is open it never covers the screen's own buttons, and
  // it is gone when the walkthrough moves to another screen.
  for (const [width, height] of [
    [1280, 720],
    [390, 844],
  ]) {
    test(`a toast over a walkthrough screen leaves Back and Next clickable at ${width}×${height}, and goes when the screen changes`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });
      await signIn(page, "setup");
      await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
      // The walkthrough resumes at the first screen not done, which depends on what the workspace already has (the AI
      // account's own screen may be the one it opens at, and an opening screen takes the cursor before this test moves it).
      // So the screen under test is always opened by moving to it from another one, which is what puts the cursor in it.
      await pressStart(page);
      const steps = page.getByRole("navigation", { name: "Setup steps" });
      const main = page.getByRole("main");
      await showSteps(page);
      await steps.getByRole("button", { name: /^Mail and calendar/ }).click();
      await expect(main.getByRole("heading", { level: 2, name: "Mail and calendar" })).toBeVisible();
      await showSteps(page);
      await steps.getByRole("button", { name: /^Your AI account/ }).click();
      await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible();
      // The screen's rows come from several requests, and its height changes as each arrives; the buttons are at its end, so
      // it is scrolled there, and the toast made, only once it has its content and has stopped changing height.
      await screenReady(page);
      // The step has its content: the provider choice with no account yet, or the accounts once one exists (the owner's
      // layout, S-0558).
      await expect(main.getByRole("group", { name: /^Which AI should/ }).or(main.getByText(/^AI accounts/)).first()).toBeVisible();
      await expect(main.locator("[data-skeleton]")).toHaveCount(0);
      await layoutSettled(page);
      // At the end of the screen, where its buttons are, pressing the undo key with nothing to undo says so in a toast.
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      // The screen puts the cursor in its first field once its data has loaded, or on itself when it has no field;
      // wait for it to land in the screen, then leave any field, where a shortcut key would type.
      await expect
        .poll(
          () =>
            page.evaluate(() => {
              const screen = document.getElementById("walkthrough-screen-title")?.closest("main");
              return !!screen && !!document.activeElement && screen.contains(document.activeElement);
            }),
          { timeout: 15_000 },
        )
        .toBe(true);
      await main.getByRole("heading", { level: 2, name: "Your AI account" }).click();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("u");
      const notices = page.getByRole("region", { name: "Notifications" });
      await expect(notices.getByText("Nothing to undo.")).toBeVisible();
      // The page makes room for the toast and moves the buttons clear of it; look once that has stopped changing.
      await layoutSettled(page);
      const overlap = async () => {
        const toast = (await notices.getByText("Nothing to undo.").boundingBox())!;
        for (const name of [/^Back$/, /^I'll do this later$/, /^Continue$/]) {
          if ((await main.getByRole("button", { name }).count()) === 0) continue;
          const button = (await main.getByRole("button", { name }).boundingBox())!;
          const apart = button.y + button.height <= toast.y || button.y >= toast.y + toast.height;
          const aside = button.x + button.width <= toast.x || button.x >= toast.x + toast.width;
          if (!apart && !aside) return String(name);
        }
        return null;
      };
      await expect.poll(overlap).toBeNull();
      await shoot(page, `walkthrough-toast-${width}`);
      await main.getByRole("button", { name: "Back" }).click({ trial: true });
      // Continue waits on this screen until an account is chosen (it says what is missing), so it can't be pressed; what
      // matters is that nothing covers it: the topmost thing at its centre is the button itself.
      // Polled like the overlap above: the page may still be making room for the toast when the check first runs.
      const next = main.getByRole("button", { name: /^Continue$/ });
      await expect
        .poll(() =>
          next.evaluate((el) => {
            const box = el.getBoundingClientRect();
            const top = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
            return !!top && el.contains(top);
          }),
        )
        .toBe(true);
      await main.getByRole("button", { name: "Back" }).click();
      // Back from the AI step is the Work step, which comes between You and Your AI account.
      await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible();
      await expect(notices.getByText("Nothing to undo.")).toHaveCount(0);
    });
  }

  // Below 1440px the header is one row (design 7.1): the title, Ask, the status chip and the buttons, with the assistant's state in
  // the chip's popover and "Quick links" in the person's menu; at about 1,000px Ask is an icon. Nothing is clipped by the
  // window, the workspace's name keeps its room before Ask gives any up, and Missed something? is in the Help menu.
  for (const width of [800, 1000, 1100, 1200, 1300]) {
    test(`at ${width}px the header is one row, with every control inside the window and the assistant's state in the status chip`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await signIn(page);
      const header = page.getByRole("banner");
      const box = (await header.boundingBox())!;
      expect(box.height).toBe(56);
      const controls = [
        header.getByRole("link", { name: /^Go to Today/ }),
        header.getByRole("searchbox"),
        header.getByRole("button", { name: /^App status: / }),
        header.getByRole("button", { name: "Hand something in" }),
        header.getByRole("button", { name: "Help" }),
        header.getByRole("button", { name: /^Menu for / }),
      ];
      for (const control of controls) {
        await expect(control).toBeVisible();
        const b = (await control.boundingBox())!;
        // On the one row, and inside the window on both sides.
        expect(b.y + b.height).toBeLessThanOrEqual(box.y + 56 + 1);
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width).toBeLessThanOrEqual(width);
      }
      // No two controls overlap: each can be clicked where it is drawn.
      const boxes = await Promise.all(controls.map(async (c) => (await c.boundingBox())!));
      for (let i = 0; i < boxes.length; i++)
        for (let j = i + 1; j < boxes.length; j++) {
          const [a, b] = [boxes[i], boxes[j]];
          const apart = a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5 || a.y + a.height <= b.y + 0.5 || b.y + b.height <= a.y + 0.5;
          expect(apart, `header controls ${i} and ${j} overlap`).toBe(true);
        }
      // The assistant's line is in the header only where it fits beside a search field at least 320px wide (S-0540), on the
      // one row, inside the window and clear of every other control. No "Quick links", and Missed something? is in the Help
      // menu, not the header.
      const line = header.getByRole("button", { name: new RegExp(`^${await assistantName(page)}`) });
      if ((await line.count()) > 0 && (await line.first().isVisible())) {
        const l = (await line.first().boundingBox())!;
        expect(l.y + l.height).toBeLessThanOrEqual(box.y + 56 + 1);
        expect(l.x).toBeGreaterThanOrEqual(0);
        expect(l.x + l.width).toBeLessThanOrEqual(width);
        for (const b of boxes) {
          const apart = l.x + l.width <= b.x + 0.5 || b.x + b.width <= l.x + 0.5 || l.y + l.height <= b.y + 0.5 || b.y + b.height <= l.y + 0.5;
          expect(apart, "the assistant's line overlaps a header control").toBe(true);
        }
        expect((await header.getByRole("searchbox").boundingBox())!.width, `search field beside the line at ${width}px`).toBeGreaterThanOrEqual(320);
      }
      await expect(header.getByRole("button", { name: "Quick links" })).toHaveCount(0);
      await expect(header.getByRole("button", { name: "Missed something?" })).toHaveCount(0);
      // Where Ask is a field the workspace's name is whole: it gives way only after Ask has.
      if (width >= 1024) {
        const clipped = await header.getByRole("link", { name: /^Go to Today/ }).evaluate((el) => Array.from(el.querySelectorAll("span")).filter((s) => s.scrollWidth > s.clientWidth + 1).length);
        expect(clipped).toBe(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
      expect((await page.getByRole("main").boundingBox())!.y).toBeGreaterThanOrEqual(box.y + 56 - 1);
      // With fonts wider than ours (letter spacing stands in for them) the row still never wraps and the title gives way.
      if (width >= 1024) {
        await header.evaluate((h) => h.querySelectorAll<HTMLElement>("a, button, a *, button *").forEach((e) => { e.style.letterSpacing = "0.15em"; }));
        for (const control of controls) expect(((await control.boundingBox())!).y).toBeLessThan(box.y + 56);
        expect(((await header.getByRole("link", { name: /^Go to Today/ }).boundingBox())!).width).toBeGreaterThanOrEqual(24);
        await header.evaluate((h) => h.querySelectorAll<HTMLElement>("a, button, a *, button *").forEach((e) => { e.style.letterSpacing = ""; }));
      }
      // What is behind the chip: today's runs, what waits and the order the accounts are tried in. The assistant's state is in
      // one place: its line in the header where that fits, otherwise its row in the popover (S-0540), never neither.
      const chip = header.getByRole("button", { name: /^App status: / });
      await chip.click();
      const popover = page.getByRole("dialog", { name: "Status" });
      await expect(popover).toBeVisible();
      await expect(async () => {
        const inHeader = (await line.count()) > 0 && (await line.first().isVisible());
        const inPopover = await popover.locator('[data-state="alive"]').isVisible();
        expect(inHeader || inPopover, "the assistant's state is in the header line or the status popover").toBe(true);
      }).toPass(SAVED);
      await expectNoViolations(page);
      await page.keyboard.press("Escape");
      await expect(popover).toHaveCount(0);
      await expect(chip).toBeFocused();
    });
  }

  test("the sidebar keeps its labels from 1024px and is an icon rail below that, with a name for each icon, and can be pinned open", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 800 });
    await signIn(page);
    expect((await page.getByRole("navigation", { name: "Views" }).boundingBox())!.width).toBeGreaterThan(200);
    await page.setViewportSize({ width: 900, height: 800 });
    const nav = page.getByRole("navigation", { name: "Views" });
    // The window's new width reaches the menu with the next draw, so the width is read until it has.
    await expect.poll(async () => (await nav.boundingBox())!.width).toBeLessThan(80);
    await expect(nav.getByRole("link", { name: "Stages" })).toBeVisible();
    await nav.getByRole("button", { name: "Keep the side menu open" }).click();
    expect((await nav.boundingBox())!.width).toBeGreaterThan(200);
    await page.reload();
    expect((await page.getByRole("navigation", { name: "Views" }).boundingBox())!.width).toBeGreaterThan(200);
    await page.getByRole("navigation", { name: "Views" }).getByRole("button", { name: "Hide the side menu" }).click();
    expect((await page.getByRole("navigation", { name: "Views" }).boundingBox())!.width).toBeLessThan(80);
  });

  // Each view's entry and the screen it opens. Loading an entry is a whole page load, so each is its own test: twelve cold loads
  // in one test's minute fail on a busy computer for want of time, not because a view did not open.
  const VIEW_LINKS: Record<string, string> = {
    "#today": "Today",
    "#work/changed": "What changed",
    "#work/handled": "Handled for you",
    "#work/followups": "Follow-ups",
    "#work/open": "To-dos",
    "#work/stages": "Stages",
    "#records/projects": "Projects",
    "#records/people": "People",
    "#records/files": "Files",
    "#records/notes": "Notes",
    "#records/knowledge": "Knowledge",
    "#settings": "Settings",
  };

  test("views are links: each entry has an address, and the side menu has none for what moved", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // Opened at Today by its address: a bare address lets a walkthrough left partway (the shared workspace, which the setup
    // walkthrough tests beside this one move on) open instead of the app.
    await signIn(page, "today");
    const links = page.getByRole("navigation", { name: "Views" }).getByRole("link");
    // The side menu keeps what it last knew of the sides until they are read, so the work views that depend on them come in with the read.
    await expect(links.filter({ hasText: "Stages" })).toBeVisible();
    const entries = await links.evaluateAll((els) => els.map((a) => ({ href: a.getAttribute("href")!, name: (a.textContent ?? "").trim() })));
    expect(entries.length).toBeGreaterThanOrEqual(10);
    for (const fragment of Object.keys(VIEW_LINKS)) expect(entries.find((e) => e.href.endsWith(fragment)), fragment).toBeDefined();
    // The side menu has no entry for what moved: Waiting to go out is a tab of Follow-ups, and Connections and Add-ons are
    // sections of Settings.
    for (const gone of ["Waiting to go out", "Connections", "Add-ons"]) {
      expect(entries.map((e) => e.name), gone).not.toContain(gone);
    }
    // The old address for a view still opens it, and the guide has its own.
    await page.goto("#stages");
    await expect(page.getByRole("heading", { level: 1, name: "Stages" })).toBeVisible();
    await page.goto("#work/outgoing");
    await expect(page.getByRole("heading", { level: 1, name: "Follow-ups" })).toBeVisible();
    await page.goto("#sources");
    await expect(page.getByRole("heading", { level: 2, name: "Connections" })).toBeVisible();
    await page.goto("#addons");
    await expect(page.getByRole("heading", { level: 2, name: "Add-ons" })).toBeVisible();
    await page.goto("#setup");
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(FIRST_SCREEN);
  });

  for (const [fragment, title] of Object.entries(VIEW_LINKS)) {
    test(`views are links: ${title}'s entry, loaded in a new page, opens the view`, async ({ page, context }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await signIn(page, "today");
      const link = page.getByRole("navigation", { name: "Views" }).locator(`a[href$="${fragment}"]`);
      await expect(link).toBeVisible();
      const href = (await link.getAttribute("href"))!;
      const fresh = await context.newPage();
      await fresh.goto(new URL(href, page.url()).toString());
      await screenReady(fresh);
      // Today's heading is the greeting (design 7.7); the others are their names.
      // The sidebar entry for the to-dos is short; the page keeps its full title.
      const pageTitle = fragment === "#work/open" ? "To-dos and questions" : title;
      await expect(fresh.getByRole("heading", { level: 1, ...(fragment === "#today" ? { name: /^Good (morning|afternoon|evening)/ } : { name: pageTitle, exact: true }) })).toBeVisible();
      await expect(fresh.getByRole("navigation", { name: "Views" }).locator("a[aria-current=page]")).toHaveAttribute("href", href);
      await fresh.close();
    });
  }

  test("changing view moves focus to the new view's heading", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    await page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: /^Stages/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Stages" })).toBeFocused();
    await page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: /^Follow-ups/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Follow-ups" })).toBeFocused();
  });

  // The cursor starts on the heading (design 7.1): a screen opens with it there, never in a field; a form the person opens puts it in
  // its first field, which other tests check.
  // Each main screen is opened from another by its address, as a person does by a link, and the cursor is found where it
  // belongs once the screen has loaded.
  // Today's keyboard also starts on its first queue line, once the queue has arrived (7.7), so there either the heading or
  // that line is where the cursor belongs; which one it is depends on whether the queue was already loaded.
  const SCREENS: Array<{ name: string; hash: string; queue?: boolean }> = [
    { name: "Today", hash: "today", queue: true },
    { name: "What changed", hash: "work/changed" },
    { name: "Since yesterday", hash: "work/since" },
    { name: "Handled for you", hash: "work/handled" },
    { name: "Follow-ups", hash: "work/followups" },
    { name: "Stages", hash: "work/stages" },
    { name: "Projects", hash: "records/projects" },
    { name: "People", hash: "records/people" },
    { name: "Files", hash: "records/files" },
    { name: "Notes", hash: "records/notes" },
    { name: "Knowledge", hash: "records/knowledge" },
    { name: "Rules review", hash: "records/rules-review" },
    { name: "Connections", hash: "settings/connections" },
    { name: "Add-ons", hash: "settings/addons" },
    { name: "Settings", hash: "settings" },
    { name: "What each account can do", hash: "settings/ai-compare" },
    { name: "Quality", hash: "quality" },
    { name: "Handover", hash: "handover" },
  ];
  for (const screen of SCREENS) {
    test(`${screen.name} opens with the cursor on its heading, never in a field`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await signIn(page);
      // Arrive from another screen, so the address changes the way a link does.
      await page.evaluate(() => {
        window.location.hash = "work/stages";
      });
      await expect(page.getByRole("heading", { level: 1, name: "Stages" })).toBeVisible();
      await page.evaluate((h) => {
        window.location.hash = h;
      }, screen.hash);
      await expect(page).toHaveURL(new RegExp(`#${screen.hash}$`));
      await screenReady(page);
      await expect
        .poll(
          () =>
            page.evaluate((queue) => {
              const at = document.activeElement;
              const main = document.querySelector("main");
              if (!at || !main || !main.contains(at)) return false;
              // The queue's first line, on a screen whose keyboard starts there.
              const first = queue ? main.querySelector("[data-row]") : null;
              if (first && first.contains(at)) return true;
              // On the heading (a page of Settings has its own section's heading), never in a field.
              return at.tagName === "H1" || at.tagName === "H2";
            }, !!screen.queue),
        )
        .toBe(true);
    });
  }

  test("going offline shows in the status chip within five seconds, and coming back clears it", async ({ page, context }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    const chip = page.getByRole("button", { name: /^App status: / });
    // Connected: the chip says a state (live, or something to do), not that it is still connecting.
    await expect(chip).not.toContainText("Connecting");
    await expect(chip).not.toContainText("Offline");
    // The chip shows a state to act on before it shows "connecting", so it cannot say that the event stream has said hello. Its
    // list says it ("Updated <time>"); going offline before then would let the stream's first answer, already on its way, arrive
    // after the app had said offline and put it back to live, which is the right thing for an answer that arrived.
    await chip.click();
    await expect(page.locator('[data-state="updates"]')).toContainText("Updated");
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-state="updates"]')).toHaveCount(0);
    await context.setOffline(true);
    await expect(chip).toContainText("Offline", { timeout: 5000 });
    await context.setOffline(false);
    await expect(chip).not.toContainText("Offline", { timeout: 20_000 });
  });

  test("on a phone the bottom bar is visible, the page does not scroll sideways, and the More sheet lists the views", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page);
    const bar = page.getByRole("navigation", { name: "Views" });
    await expect(bar).toBeVisible();
    for (const name of ["Today", "To-dos", "Hand something in", "Schedule", "More"]) {
      await expect(bar.getByRole(["Today", "To-dos", "Schedule"].includes(name) ? "link" : "button", { name })).toBeVisible();
    }
    const box = (await bar.boundingBox())!;
    expect(box.y + box.height).toBeGreaterThanOrEqual(844 - 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await bar.getByRole("button", { name: "More" }).click();
    const sheet = page.getByRole("dialog", { name: "More" });
    await expect(sheet.getByRole("link", { name: "Stages" })).toBeVisible();
    await sheet.getByRole("link", { name: "Stages" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Stages" })).toBeVisible();
    // Content is not hidden under the bar.
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const last = await page.evaluate(() => {
      const main = document.querySelector("main")!.getBoundingClientRect();
      return main.bottom;
    });
    expect(last).toBeGreaterThanOrEqual(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await shoot(page, "phone-stages");
  });
});

// Made-up answers for the screens that need accounts and measurements the demo workspace doesn't have, so the layout and the
// accessibility checks run on what a person with accounts would see. The shapes are the server's own.
// `now` is the server's own moment (`/__e2e/now`), so "answered 2 hours ago" is two hours before the page's clock whatever the run's age.
const account = (now: number, name: string, label: string, over: Record<string, unknown> = {}) => ({
  name,
  label,
  kind: null,
  adapter: "adapter-one",
  base_url: null,
  models: { everyday: "model-a", harder: "model-b" },
  used_for: [],
  backup_for: [],
  has_key: true,
  key_state: "saved",
  key_where: null,
  key_ending: false,
  credential_expires: null,
  answered_at: new Date(now - 2 * 3_600_000).toISOString(),
  spent_today_usd: 1.2,
  checked_for: [],
  check_failed_for: [],
  checked_at: null,
  paused_until: null,
  check_usd: 0.02,
  ...over,
});
const accounts = (now: number) => [
  account(now, "main", "Main account", { used_for: ["routine", "deep"] }),
  account(now, "second", "Second account", { backup_for: ["routine", "deep"], answered_at: null, spent_today_usd: 0, checked_for: ["routine", "deep"], checked_at: "2026-10-14T09:00:00+00:00" }),
  account(now, "trial", "Trial account", { key_state: "missing", answered_at: null, spent_today_usd: 0 }),
];
const skill = (id: string, label: string, over: Record<string, unknown> = {}) => ({
  id,
  label,
  description: "",
  measured: true,
  runs: 18,
  passes: 17,
  pass_rate: 0.94,
  age_days: 2,
  cost_per_pass_usd: 0.03,
  stale: null,
  below_min: false,
  ...over,
});
const unmeasured = (id: string, label: string) => skill(id, label, { measured: false, runs: 0, passes: 0, pass_rate: null, age_days: null, cost_per_pass_usd: null });
const SKILLS = {
  min_score: 0.8,
  stale_days: 60,
  accounts: [
    {
      name: "main",
      models: [
        { model: "everyday", measure: null, measure_why: null, skills: [skill("notes", "Pull actions from meeting notes"), skill("route", "Route a question to who decides", { pass_rate: 0.9, cost_per_pass_usd: 0.02 }), skill("term", "Use a known term", { pass_rate: 0.88, cost_per_pass_usd: 0.02 }), unmeasured("voice", "Write an update in your voice")] },
        { model: "harder", measure: null, measure_why: null, skills: [skill("notes", "Pull actions from meeting notes", { pass_rate: 0.97, cost_per_pass_usd: 0.11 }), skill("route", "Route a question to who decides", { pass_rate: 0.96, cost_per_pass_usd: 0.08 }), skill("term", "Use a known term", { pass_rate: 1, cost_per_pass_usd: 0.07 }), skill("voice", "Write an update in your voice", { pass_rate: 0.91, runs: 6, age_days: 40, cost_per_pass_usd: 0.14, stale: "age" })] },
      ],
    },
    {
      name: "second",
      models: [{ model: "everyday", measure: null, measure_why: null, skills: [skill("notes", "Pull actions from meeting notes", { pass_rate: 0.89, cost_per_pass_usd: 0.04 }), skill("route", "Route a question to who decides", { pass_rate: 0.85, cost_per_pass_usd: 0.01 }), skill("term", "Use a known term", { pass_rate: 0.56, runs: 9, below_min: true, cost_per_pass_usd: 0.05 }), unmeasured("voice", "Write an update in your voice")] }],
    },
  ],
};
const ESTIMATE = { models: ["everyday"], level: "internal", cases: 12, skipped: 0, runs: 3, usd: 0.12, confirm_above_usd: 0.1, per_day_usd: 2, needs_go: false };

async function mockAccounts(page: Page) {
  await page.route("**/api/ai/accounts", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const { now } = (await (await page.request.get("/__e2e/now")).json()) as { now: number };
    return route.fulfill({ json: accounts(now) });
  });
  await page.route("**/api/ai/skills", (route) => route.fulfill({ json: SKILLS }));
  await page.route("**/api/ai/skills/*/estimate", (route) => route.fulfill({ json: ESTIMATE }));
}

test.describe("AI accounts as one place, what each can do, and the follow-ups table", () => {
  test("Settings: the summary line, a row with a role pill, a state line and one next step each, and the add drawer opens in place", async ({ page }) => {
    await mockAccounts(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, "settings/ai");
    const section = page.getByRole("region", { name: /^AI accounts/ });
    await expect(section.getByRole("heading", { name: /^AI accounts/ })).toBeVisible();
    await expect(section.getByRole("group", { name: "Who does the work" })).toContainText("Main account does");
    await expect(section.getByRole("group", { name: "Who does the work" })).toContainText("Second account takes over");
    const rows = section.locator("li[data-row]");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("In use");
    await expect(rows.nth(0)).toContainText("Ready · answered 2 hours ago · $1.20 today");
    await expect(rows.nth(1)).toContainText("Backup");
    await expect(rows.nth(1)).toContainText("Works · checked Oct 14");
    await expect(rows.nth(2)).toContainText("Access key not found on this computer");
    await expect(rows.nth(2).getByRole("button", { name: "Add the access key for Trial account" })).toBeVisible();
    await section.scrollIntoViewIfNeeded();
    await shoot(page, "accounts-1440");
    await expectNoViolations(page);
    // The form opens here, as a drawer, and the address stays the AI accounts section of Settings.
    await section.getByRole("button", { name: "Add an account" }).click();
    const drawer = page.getByRole("dialog", { name: "Add an account" });
    await expect(drawer).toBeVisible();
    await expect(page).toHaveURL(/#settings\/ai$/);
    await expectNoViolations(page);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(section.getByRole("button", { name: "Add an account" })).toBeFocused();
  });

  test("Settings saves each change as it is made, with Changed and Reset, a toast with Undo, and no Save button", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, "settings/you");
    const name = page.getByRole("textbox", { name: "Workspace name" });
    // Settings draws its section once the first read arrives, which the ready mark waits for.
    await expect(page.locator("[data-section-heading]")).toBeFocused();
    await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0);
    const before = await name.inputValue();
    await name.fill("Quay workspace one");
    await name.press("Enter");
    const toasts = page.getByRole("region", { name: "Notifications" });
    await expect(toasts).toContainText("Workspace name: Quay workspace one", SAVED);
    const row = page.locator(".setting", { has: name });
    await expect(row.getByText("Changed", { exact: true })).toBeVisible();
    await toasts.getByRole("button", { name: "Undo" }).first().click();
    // An Undo is done when it says so: it saves, then reloads what every screen shows, which a busy computer takes longer over.
    await expect(toasts).toContainText("Undone.", SAVED);
    // The page is ready again once the re-read after the Undo has answered: the field then holds the value put back.
    await screenReady(page);
    await expect(name).toHaveValue(before);
    // Reset puts it back to its default at once, and says so.
    await name.fill("Quay workspace two");
    await name.press("Enter");
    await expect(toasts).toContainText("Workspace name: Quay workspace two", SAVED);
    await row.getByRole("button", { name: /^Reset/ }).click();
    await expect(row.getByText("Changed", { exact: true })).toHaveCount(0, SAVED);
    await expectNoViolations(page);
  });

  test("an Undo says Undone. as soon as the change is undone, with the screens' reads still on their way, and the next change says so too", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, "settings/you");
    const name = page.getByRole("textbox", { name: "Workspace name" });
    // Settings draws its section once the first read arrives, which the ready mark waits for.
    await expect(page.locator("[data-section-heading]")).toBeFocused();
    const before = await name.inputValue();
    const toasts = page.getByRole("region", { name: "Notifications" });
    // A slow machine's answers to the screens' reads come late: here they are held until the test lets them through.
    let held = false;
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/**", async (route) => {
      if (held && route.request().method() === "GET") await gate;
      await route.continue();
    });
    await name.fill("Quay workspace three");
    await name.press("Enter");
    await expect(toasts).toContainText("Workspace name: Quay workspace three", SAVED);
    held = true;
    await toasts.getByRole("button", { name: "Undo" }).first().click();
    // The change is undone on the server when its answer comes; what the screens read afterwards is not what "Undone." waits for.
    // The reads stay held until after this check, so "Undone." showing at all proves it did not wait for them; how long the
    // server takes to answer the undo (a busy shared server in CI) is not the point, so the wait is the save's.
    await expect(toasts).toContainText("Undone.", SAVED);
    held = false;
    release();
    await expect(name).toHaveValue(before, SAVED);
    // The next change, straight after, says what it did: nothing replaces it or leaves it unsaid.
    await name.fill("Quay workspace four");
    await name.press("Enter");
    await expect(toasts).toContainText("Workspace name: Quay workspace four", SAVED);
    await toasts.getByRole("button", { name: "Undo" }).first().click();
    await expect(toasts).toContainText("Undone.", SAVED);
    await expect(name).toHaveValue(before, SAVED);
  });

  test("Settings: the help sits beside each setting on a wide screen and under it on a phone, and the section list stacks above", async ({ page }) => {
    await signIn(page, "settings/backups");
    const row = page.locator(".setting").filter({ hasText: "Back up automatically" }).first();
    await expect(row).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    const wide = { field: (await row.locator("[data-main]").boundingBox())!, help: (await row.locator("[data-help]").boundingBox())! };
    expect(wide.help.x).toBeGreaterThan(wide.field.x + wide.field.width - 1);
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    const list = (await nav.boundingBox())!;
    expect(list.x + list.width).toBeLessThan(wide.field.x + 1);
    await page.setViewportSize({ width: 390, height: 844 });
    // Measured once the narrow layout has settled: the help under its field, the section list above them.
    const stacked = async () => {
      const field = (await row.locator("[data-main]").boundingBox())!;
      const help = (await row.locator("[data-help]").boundingBox())!;
      const sections = (await nav.boundingBox())!;
      return help.y > field.y + field.height - 1 && sections.y + sections.height < field.y + 1;
    };
    await expect.poll(stacked).toBe(true);
    // The window width settles with the layout (a scroll bar or a late reflow can show for a frame after the resize).
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("Settings on a phone: no sideways scroll, and the rows keep their one button", async ({ page }) => {
    await mockAccounts(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, "settings/ai");
    const section = page.getByRole("region", { name: /^AI accounts/ });
    await section.scrollIntoViewIfNeeded();
    await expect(section.locator("li[data-row]").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await shoot(page, "accounts-phone");
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`Settings: which model does what has named lists, saves a choice with Undo, and has no violations in ${scheme}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1024, height: 900 });
      await signIn(page, "settings/ai");
      // Which model does what sits behind a closed disclosure on the AI page.
      await page.getByText("Choose which account does each kind of work", { exact: true }).click();
      const part = page.getByRole("region", { name: "Which model does what" });
      await expect(part).toBeVisible();
      await expect(part.getByRole("group", { name: "Each kind of work" }).getByRole("combobox").first()).toBeVisible();
      await expect(part.getByRole("group", { name: "Send hard work to a stronger model first" })).toContainText("the first one that fits decides");
      await expect(part).toContainText("follows your spending limits");
      await part.scrollIntoViewIfNeeded();
      await expectNoViolations(page);
      // A choice is saved as it is made and can be undone.
      const first = part.getByRole("group", { name: "Each kind of work" }).getByRole("combobox").first();
      const before = (await first.getAttribute("value")) ?? "";
      const options = (await choicesOf(first)).map((c) => c.value);
      const other = options.find((o) => o !== before)!;
      await choose(first, other);
      await expect(page.getByRole("button", { name: "Undo" }).first()).toBeVisible(SAVED);
      await expect(first).toHaveAttribute("value", other);
      await page.getByRole("button", { name: "Undo" }).first().click();
      // The Undo is done when it says so (it saves, then reloads what the screens show); the list then shows what it had.
      await expect(page.getByRole("region", { name: "Notifications" })).toContainText("Undone.", SAVED);
      await expect(first).toHaveAttribute("value", before);
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    test(`the grid of what each account can do, in ${scheme}: pass rate first, the cheapest passing marked, and no violations`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await mockAccounts(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await signIn(page, "settings/ai");
      await page.getByRole("button", { name: "Compare what they can do" }).click();
      await expect(page.getByRole("heading", { level: 2, name: "Compare what accounts can do" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Views" }).locator("a[aria-current=page]")).toHaveAttribute("href", /#settings$/);
      const table = page.getByRole("table");
      await expect(table.getByRole("columnheader")).toHaveText(["Kind of work", "Main account · everyday", "Main account · harder", "Second account · everyday"]);
      await expect(table).toContainText("Cheapest that passes");
      await expect(table).toContainText("Below 80%");
      await expect(table).toContainText("(old)");
      await expect(table.getByRole("button", { name: "Check skills of Main account · everyday" })).toContainText("Check skills (about $0.12)");
      if (scheme === "light") await shoot(page, "grid-1440");
      await expectNoViolations(page);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForFunction(() => document.documentElement.hasAttribute("data-narrow"));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await expectNoViolations(page);
    });
  }

  test("Follow-ups: the menu's Show as a table shows the table before anything is copied, and it passes the accessibility checks", async ({ page }) => {
    const book = `${"https" + "://"}example.com/book`;
    const section = {
      person: "PER-9",
      name: "Robin Sample",
      is_pm: false,
      questions: [
        { id: "Q-1", title: "Do we have written permission for the epigraph?", text: "", links: [{ label: "Book page", url: book }], kind: "question", status: "open", project_name: "Sample project", sent: "2026-10-10", waiting_days: null, chase_due: false, about: null, options: [] },
        { id: "Q-2", title: "Which author bio goes on the jacket?", text: "", links: [], kind: "question", status: "open", project_name: "Sample project", sent: null, waiting_days: null, chase_due: false, about: null, options: [] },
      ],
      actions: [
        { id: "ACT-1", text: "Agree on the back-cover copy", due: "2020-10-14", project_name: "Sample project", links: [{ label: "Book page", url: book }], told: null, to_send: true, told_days: null, followed_up: null, on_hold: null, chase_due: false },
        { id: "ACT-2", text: "Send the acknowledgments page", due: "2099-10-23", project_name: "Sample project", links: [], told: null, to_send: true, told_days: null, followed_up: null, on_hold: null, chase_due: false },
      ],
      message: "Hi Robin",
      to_send: 4,
    };
    await page.route("**/api/followups", (route) => route.fulfill({ json: [section] }));
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, "work/followups");
    // With one person to write to, their follow-ups show in place: nothing to open first.
    await page.getByRole("button", { name: "More actions for Robin Sample" }).click();
    await page.getByRole("menuitem", { name: "Show as a table" }).click();
    const tables = page.getByRole("table");
    await expect(tables).toHaveCount(2);
    await expect(tables.first().getByRole("columnheader")).toHaveText(["Project", "To-do", "Due", "Link", "Your update"]);
    await expect(tables.nth(1).getByRole("columnheader")).toHaveText(["Project", "Question", "First asked", "Link", "Your answer"]);
    await expect(tables.first()).toContainText("overdue");
    await expect(page.getByRole("button", { name: "Copy as table" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy for a spreadsheet" })).toBeVisible();
    // The fill-in column is the last and the widest.
    const widths = await tables.first().getByRole("columnheader").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().width));
    expect(widths[widths.length - 1]).toBe(Math.max(...widths));
    await shoot(page, "followups-table-1440");
    await expectNoViolations(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.hasAttribute("data-narrow"));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("Today: a backup that needs attention is an At risk line with its button at the end of the row, and no bar", async ({ page }) => {
    await page.route("**/api/today/queue", (route) =>
      route.fulfill({ json: [{ key: "backup", group: "risk", kind: "backup", count: 1, state: "overdue", age_hours: 100, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {} }] }),
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    const line = page.locator('[data-queue-line="backup"]');
    await expect(line).toBeVisible();
    await expect(line).toContainText("The last backup was 4 days ago");
    await expect(page.getByRole("region", { name: "Backup", exact: true })).toHaveCount(0);
    const button = line.getByRole("button", { name: "Back up now" });
    const [lineBox, buttonBox] = await Promise.all([line.boundingBox(), button.boundingBox()]);
    // The button ends one menu slot (kept empty on a row without a menu, so every row's buttons share one edge) before the row's padding
    // does, however long the words are (round 3: one trailing slot).
    const slot = await button.evaluate((el) => {
      const actions = el.closest("[class*='actions']");
      return actions ? parseFloat(getComputedStyle(actions).paddingInlineEnd) : 0;
    });
    expect(slot).toBeGreaterThan(0);
    expect(lineBox!.x + lineBox!.width - (buttonBox!.x + buttonBox!.width) - slot).toBeLessThan(24);
    await shoot(page, "backup-line-1440");
    // The queue route may still be answering a poll as the page closes; that is not a failure of the test.
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  // C47 and C56 (UI/UX re-review of B-7, R3): the lines that ran tallest in the demo (a decision, two held questions from
  // outside with long items, a move, a failed backup and an overdue to-do) leave six lines fully visible at 1280x720, and
  // every line's meta is one line, cut with an ellipsis. "Outside" sits in the pill column, never in the meta.
  // C54 (UI/UX re-review of B-7, R1): no line on Today, no inspector heading and no title in What changed holds an id of the
  // app's own, whatever the demo's history held before titles were named by the item.
  test("no Today line, inspector heading or What changed title holds an internal id", async ({ page }) => {
    const ID = /\b[A-Z]{2,5}-\d+\b/;
    await page.setViewportSize({ width: 1920, height: 1080 });
    await signIn(page);
    const rows = page.locator("[data-queue-line]");
    await expect(rows.first()).toBeVisible();
    await layoutSettled(page);
    for (const text of await rows.evaluateAll((els) => els.map((e) => e.textContent ?? ""))) expect(text).not.toMatch(ID);
    // Each line in turn is in the inspector, and its heading says no id either.
    const count = await rows.count();
    for (let i = 0; i < Math.min(count, 12); i++) {
      await rows.nth(i).click({ position: { x: 4, y: 4 } });
      const heading = await page.locator("[data-queue-inspector] h2, [data-queue-inspector] h3").first().textContent();
      expect(heading ?? "").not.toMatch(ID);
    }
    await signIn(page, "#work/changed");
    await expect(page.getByRole("heading", { level: 1, name: "What changed" })).toBeVisible();
    // The changes load after the heading; read the titles once the first row is there.
    await expect(page.locator("[data-row]").first()).toBeVisible();
    const titles = await page.locator("[data-row] strong, [data-row] .title, [data-row] .what").allTextContents();
    expect(titles.length).toBeGreaterThan(0);
    for (const text of titles) expect(text).not.toMatch(ID);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("What changed titles follow Today's title rule, never From: and a person", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, "#work/changed");
    await expect(page.getByRole("heading", { level: 1, name: "What changed" })).toBeVisible();
    await expect(page.locator('[data-row] [id^="t-"]').first()).toBeVisible();
    const titles = await page.locator('[data-row] [id^="t-"]').allTextContents();
    expect(titles.length).toBeGreaterThan(0);
    for (const text of titles) expect(text).not.toMatch(/^From:/);
    // The demo's mail-borne changes read as Today's lines do: the subject leads, and the kind and the sender are the first of its meta.
    const rows = await page.locator("[data-row]").allTextContents();
    expect(rows.some((text) => /Email from .+ · /.test(text))).toBe(true);
    expect(titles.some((text) => /^Email from /.test(text))).toBe(false);
  });
});

test("a browser with no sign-in is told the way back on the app's own screen, never a bare error", async ({ browser }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL as string;
  // Nothing of the harness's own is sent: this browser has no sign-in.
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: {} });
  try {
    const page = await context.newPage();
    await page.goto("");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Open the app again to sign in");
    await expect(page.getByText("from its icon or launcher")).toBeVisible();
    // No terminal command is named on screen (the wording guard); the command line has its own `cockpit open`.
    await expect(page.getByText("cockpit open")).toHaveCount(0);
    await expectNoViolations(page);
  } finally {
    await context.close();
  }
});

test.describe("signing in", () => {
  // A fresh context sends nothing of its own (no harness header), so this is the page's own sign-in.
  test("the link's token is traded for a session kept in the page's storage, never a cookie, and the address is clean", async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL, extraHTTPHeaders: {} });
    const page = await context.newPage();
    await openScreen(page);
    expect(page.url()).not.toContain("token=");
    expect(await context.cookies()).toEqual([]);
    const session = await page.evaluate(() => window.localStorage.getItem("cockpit.session"));
    expect(session).toBeTruthy();
    expect(session).not.toBe("e2e-token");
    // The page stays signed in on a reload that carries no token.
    await page.reload();
    await screenReady(page);
    // Another page's storage (another address or port has its own) holds no session, so the data is refused to it.
    const other = await browser.newContext({ baseURL, extraHTTPHeaders: {} });
    const stranger = await other.newPage();
    await stranger.goto("");
    expect((await stranger.request.get("api/runtime-config")).status()).toBe(401);
    await context.close();
    await other.close();
  });
});
