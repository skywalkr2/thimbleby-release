// One click on Today reads only what it changed: from the click to the screen being ready again, the page saves once and
// reads again only the screens that show what was written, fewer than 7 reads (the review's bar was fewer than 8 requests,
// the save included). The time the review took is recorded as its own small write, which may fall in the window or not;
// it is not a read and is left out of the count. The requests are printed.
import { expect } from "@playwright/test";
import { test } from "./test";
import { openScreen, screenReady } from "./open-screen";

const MOST_READS = 7;
const REVIEW_TIME = "POST /api/quality/review-time";

test("Keeping a reviewed change on Today makes fewer than 8 requests", async ({ page }) => {
  await openScreen(page, "today");
  const row = page.locator('[data-queue-line="review"]').first();
  await expect(row).toBeVisible();
  const keep = row.getByRole("button", { name: /^Keep (it|all \d+)$/ });
  if ((await keep.count()) === 0) await row.getByRole("button", { name: "Look over", exact: true }).click();
  const made: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.includes("/api/")) made.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  const before = await page.locator('[data-queue-line="review"]').count();
  await keep.click();
  await expect(page.locator('[data-queue-line="review"]')).toHaveCount(before - 1);
  await screenReady(page);
  console.log(`requests after one click on Today: ${made.length}\n  ${made.join("\n  ")}`);
  expect(made.filter((r) => r.startsWith("POST") && r !== REVIEW_TIME)).toEqual(["POST /api/changesets/confirm"]);
  expect(made.filter((r) => r.startsWith("GET")).length).toBeLessThan(MOST_READS);
});
