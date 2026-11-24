// Today's rail and queue (the UI/UX review of build 63, batch U5: M1, S1, S2): the week's goals are in the rail on any day when the
// week has them (the real routes, a confirmed week), a week with days off has one line under the date where the rail is below the
// queue and none beside it, several stale to-dos are one row that says the fact once, and while a line is open in the rail the rail
// says what comes back. The goals are taken out again after the test, because the server's week is shared with the other scenarios.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

const GOALS = ["Approve the back-cover copy", "Approve the cover proof", "Book the print run"];
const base = { untrusted: false, unpriced: 0, actions: [] as string[], questions: [] as string[], outcome: {}, count: 1 };
const stale = (n: number, days: number) => ({ ...base, key: `stale:A-${n}`, group: "review", kind: "stale", actions: [`A-${n}`], waiting_days: days, subject: `Tidy the proofs, round ${n}`, choices: ["keep", "drop", "snooze"] });
const week = { first: "2026-11-23", last: "2026-11-27", state: "empty", sentence: null, rows: [], read_again: true, days_off: [{ day: "2026-11-26", reason: "Thanksgiving" }, { day: "2026-11-27", reason: "Day After Thanksgiving" }], working_days: 2 };

test.describe("Today's rail and queue, batch U5", () => {
  test("the week's goals are in the rail on an ordinary day, from the real routes", async ({ page, request }) => {
    const kept = await request.put("api/brief/goals", { data: { goals: GOALS } });
    expect(kept.ok()).toBe(true);
    try {
      await page.setViewportSize({ width: 1440, height: 900 });
      await openScreen(page, "today");
      const card = page.getByRole("region", { name: /This week/ });
      await expect(card).toBeVisible();
      for (const goal of GOALS) await expect(card.getByText(goal)).toBeVisible();
    } finally {
      await request.put("api/brief/goals", { data: { goals: [] } });
    }
  });

  for (const width of [1024, 1099]) {
    test(`at ${width}px a week with days off has one line under the date`, async ({ page }) => {
      await page.route("**/api/week-ahead", (route) => route.fulfill({ json: week }));
      await page.setViewportSize({ width, height: 900 });
      await openScreen(page, "today");
      const line = page.locator("[data-week-line]");
      await expect(line).toHaveText("This week: 2 working days (Thu, Fri off)");
      const date = await page.getByRole("heading", { level: 1 }).boundingBox();
      const under = (await line.boundingBox())!;
      expect(under.y, "under the date line").toBeGreaterThan(date!.y);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  }

  test("from 1100px the rail is beside the queue and the line is not drawn", async ({ page }) => {
    await page.route("**/api/week-ahead", (route) => route.fulfill({ json: week }));
    await page.setViewportSize({ width: 1100, height: 900 });
    await openScreen(page, "today");
    await expect(page.getByRole("region", { name: /This week/ })).toBeVisible();
    await expect(page.locator("[data-week-line]")).toHaveCount(0);
  });

  async function serveStale(page: Page, lines: unknown[]) {
    await page.route("**/api/today/queue", (route) => route.fulfill({ json: lines }));
  }

  test("two stale to-dos are one row that says the fact once", async ({ page }) => {
    await serveStale(page, [stale(1, 42), stale(2, 35)]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openScreen(page, "today");
    const rows = page.locator('[data-queue-line="stale"]');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText("2 to-dos untouched, the longest for 42 days");
    await expect(page.getByText(/Decide whether you are still doing/)).toHaveCount(0);
    await expect(page.getByText(/The longest has gone/)).toHaveCount(0);
  });

  test("one stale to-do keeps its own row and choices", async ({ page }) => {
    await serveStale(page, [stale(1, 42)]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openScreen(page, "today");
    const row = page.locator('[data-queue-line="stale"]');
    await expect(row).toContainText("Decide whether you are still doing: Tidy the proofs, round 1");
    await expect(row.getByRole("button", { name: "Keep it" })).toBeVisible();
  });
});
