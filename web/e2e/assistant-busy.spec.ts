// The header says when the assistant is working (S-0526): a moving ring and words while a run is going, with nothing to poll
// (the status arrives over the live stream), and the resting dot again once it ends. The server holds a run that was handed a
// note saying so until the test releases it.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

const LOADED = { timeout: 20_000 };

async function assistantName(page: Page): Promise<string> {
  const response = await page.request.get("api/runtime-config");
  expect(response.ok()).toBe(true);
  return (await response.json()).assistant_name;
}

// A run left holding (a failed test) is let go, so the next try starts from rest.
test.afterEach(async ({ page }) => {
  await page.request.post("__e2e/release");
});

test("a run in hand shows in the header as a moving ring and words, and the header rests when it ends", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openScreen(page);
  const name = await assistantName(page);
  const line = page.getByRole("banner").getByRole("button", { name: new RegExp(`^${name}`) });
  await expect(line).toBeVisible(LOADED);
  await expect(line).not.toHaveAttribute("data-busy", "");
  await expect(line).toHaveAccessibleName(`${name}: Working`);

  const handed = await page.request.post("api/handin", { data: { note: `Hold the assistant while it reads this (${Date.now()}).` } });
  expect(handed.ok()).toBe(true);

  // The server tells the page the work began: the ring, the words and an accessible name that says the state in words.
  await expect(line).toHaveAttribute("data-busy", "", LOADED);
  await expect(line).toHaveAccessibleName(new RegExp(`^${name}: (Reading|Working on something|Sorting|Drafting)`));
  const ring = line.locator("[data-working]");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(ring).toBeVisible();
  await expect(line.locator("[data-indicator]")).toHaveCount(0);
  await expect(line.locator("[data-doing]")).toBeVisible();
  expect(await ring.evaluate((el) => getComputedStyle(el).animationName)).not.toBe("none");

  // The row stays one row and the page never scrolls sideways, whatever the width.
  for (const width of [1440, 1100, 900, 390]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), `at ${width}px`).toBeLessThanOrEqual(0);
    // Where the header has the line (it is left to the status chip on a narrow window), it stays one row.
    // Read in one step: the header may swap the line for the chip while the window changes.
    const heights = await line.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
    for (const height of heights) expect(height, `at ${width}px`).toBeLessThan(56);
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  // With reduced motion the ring stands still: the words still say what is going on.
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await ring.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");

  // The popover says it too, in words.
  await line.click();
  const dialog = page.getByRole("dialog", { name: name });
  await expect(dialog.locator("[data-section='working']")).toBeVisible();
  await page.keyboard.press("Escape");

  const released = await page.request.post("__e2e/release");
  expect(released.ok()).toBe(true);
  await expect(line).not.toHaveAttribute("data-busy", "", LOADED);
  await expect(line.locator("[data-indicator]")).toBeVisible();
  await expect(line).toHaveAccessibleName(`${name}: Working`);
});

// S-0540: the line shows wherever it fits with the search field kept at least 320px wide, not only from 1440, and no word "Live" is on screen.
test("the header shows the assistant's line at 1280, 1366 and 1440 with the search field at least 320px wide, and never says Live", async ({ page }) => {
  for (const width of [1280, 1366, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await openScreen(page);
    const name = await assistantName(page);
    const header = page.getByRole("banner");
    const line = header.getByRole("button", { name: new RegExp(`^${name}`) });
    await expect(line, `the line at ${width}px`).toBeVisible(LOADED);
    const ask = header.locator("[data-header-ask]");
    expect((await ask.boundingBox())!.width, `search field at ${width}px`).toBeGreaterThanOrEqual(320);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), `sideways at ${width}px`).toBeLessThanOrEqual(0);
    // The chip says one of its plain states ("All good", or what needs a look); the word "Live" is nowhere.
    await expect(header.getByRole("button", { name: /^App status: (?!Live)/ })).toBeVisible();
    await expect(page.getByText(/^Live$/)).toHaveCount(0);
  }
});

test("where the search field would be under 320px the line leaves the header and the status chip keeps the word", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await openScreen(page);
  const name = await assistantName(page);
  const header = page.getByRole("banner");
  await expect(header.getByRole("button", { name: /^App status/ })).toBeVisible(LOADED);
  await expect(header.getByRole("button", { name: new RegExp(`^${name}`) })).toHaveCount(0);
});
