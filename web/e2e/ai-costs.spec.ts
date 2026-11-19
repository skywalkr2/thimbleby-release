// What an AI account's service actually charged, beside the app's own figure (design 6.16, S-0654), in a real browser. The access
// server (`--standin-account`) has an account whose service's report was already read (a settled day well above what the app
// worked out, a day still open, and today not reported yet), so the app never asks any service. Today has one line about the gap,
// Open shows the side-by-side on the account's card and under AI and spending, and Not now is remembered.
import { expect } from "@playwright/test";
import { test } from "./test";

const SEEN = { timeout: 20_000 };

test("a gap is one line on Today, Open shows the real cost beside the app's own, and Not now puts it off", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto("?token=e2e-token");
  const line = page.locator('[data-queue-line="cost_gap"]');
  await expect(line).toBeVisible(SEEN);
  await expect(line).toContainText("Check what Billed account charged");
  await expect(line).toContainText("On 1 day it charged $14.50");
  await expect(line).toContainText("worked out $2.00");

  await line.getByRole("button", { name: "Open what Billed account charged" }).click();
  const card = page.locator('[data-account-costs="billed"]');
  await expect(card).toBeVisible(SEEN);
  const rows = card.getByRole("row");
  // header, then today (not reported yet, never zero), yesterday (still open) and the settled day: newest first
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(1)).toContainText("not reported yet");
  await expect(rows.nth(1)).not.toContainText("$0.00");
  await expect(rows.nth(1)).toContainText("$0.40");
  await expect(rows.nth(2)).toContainText("$3.00, may still change");
  await expect(rows.nth(3)).toContainText("$14.50");
  await expect(rows.nth(3)).toContainText("$2.00");
  await expect(card.getByRole("rowheader").first()).toContainText("(UTC day)");
  await expect(card.getByText("Read ", { exact: false }).first()).toBeVisible();

  // The same side-by-side is under AI and spending.
  const section = page.locator("[data-ai-costs]");
  await expect(section).toBeVisible(SEEN);
  await expect(section.getByRole("table")).toContainText("$14.50");

  // No sideways scroll at a phone's width, with the table stacked.
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(card).toBeVisible();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(wide).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1200, height: 900 });

  // Back on Today, Not now (in the line's menu) puts it off for these days.
  await page.goto("?token=e2e-token");
  await expect(line).toBeVisible(SEEN);
  await line.getByRole("button", { name: "More actions for what an account charged" }).click();
  await page.getByRole("menuitem", { name: "Not now" }).click();
  await expect(line).toHaveCount(0, SEEN);
  await page.reload();
  await expect(page.locator("[data-queue-line]").first()).toBeVisible(SEEN);
  await expect(line).toHaveCount(0);
});
