// Batch R2, S-0362: the screens that need the demo data (follow-ups and to-dos), on the layout server. One filled action per
// place: a list's rows draw their action as an outline, so the page keeps one filled button at most, on every tab.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";

const LOADED = { timeout: 20_000 };

const open = async (page: Page, hash: string) => {
  await page.goto(`?token=e2e-token#${hash}`);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOADED);
};

/** The filled buttons in the main content, by name. */
const filled = (page: Page) => page.locator('main [data-weight="filled"]');

test.describe("one filled action per place (S-0362)", () => {
  test("Follow-ups: every tab has at most one filled button, and a row's own action is an outline (S3-C1)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "work/followups");
    await expect(page.getByRole("heading", { name: "Follow-ups", level: 1 })).toBeVisible(LOADED);
    let rows = 0;
    for (const tab of ["To send", "Waiting on them", "Later"]) {
      const button = page.getByRole("button", { name: tab, exact: false }).first();
      if (await button.count()) await button.click();
      // The tab's rows are drawn before they are counted.
      if (tab === "Waiting on them") await expect(page.locator("main [data-item]").first()).toBeVisible(LOADED);
      const names = await filled(page).evaluateAll((els) => els.map((el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40)));
      expect(names.length, `${tab}: ${names.join(" | ")}`).toBeLessThanOrEqual(1);
      // The row buttons that mark work done or followed up are never filled.
      const rowButtons = page.locator('main [data-item] button', { hasText: /Mark their work done|Followed up|Mark done/ });
      rows += await rowButtons.count();
      for (const one of await rowButtons.all()) await expect(one).toHaveAttribute("data-weight", "outline");
    }
    expect(rows, "the demo data has follow-ups waiting").toBeGreaterThanOrEqual(1);
  });

  test("the to-dos and questions screen has at most one filled button, on each of its tabs", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "work/open");
    await expect(page.getByRole("heading", { name: "To-dos and questions", level: 1 })).toBeVisible(LOADED);
    for (const tab of await page.getByRole("tab").all()) {
      await tab.click();
      const names = await filled(page).evaluateAll((els) => els.map((el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40)));
      expect(names.length, `${await tab.innerText()}: ${names.join(" | ")}`).toBeLessThanOrEqual(1);
    }
  });
});
