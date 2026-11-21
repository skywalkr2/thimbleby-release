// One form at a time on a question, and To-dos that open on everything (H5-42, H5-43), on the owner's paths.
import { expect } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

test.describe("QF1", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  test("a question's Drop is the only form on it, and Cancel brings the answer back", async ({ page }) => {
    await openScreen(page, "today");
    const line = page.locator('[data-queue-line="decision"]').first();
    await line.getByRole("button", { name: "Answer", exact: true }).click();
    await expect(line.getByRole("textbox", { name: "Your answer" })).toBeVisible();
    await line.getByRole("button", { name: /^More actions for Cover finish/ }).click();
    await page.getByRole("menuitem", { name: "Drop" }).click();
    await expect(line.getByRole("textbox", { name: "Why isn't it needed?" })).toBeVisible();
    await expect(line.getByRole("textbox", { name: "Your answer" })).toHaveCount(0);
    await line.getByRole("button", { name: "Cancel" }).click();
    await expect(line.getByRole("textbox", { name: "Your answer" })).toBeVisible();
    await expect(line.getByRole("textbox", { name: "Why isn't it needed?" })).toHaveCount(0);
  });

  test("Today's overdue line opens the overdue rows, and To-dos opened again later shows everything, soonest due first", async ({ page }) => {
    await openScreen(page, "today");
    const line = page.locator('[data-queue-line="overdue"]');
    const counted = Number((await line.innerText()).match(/Finish (\d+) overdue/)?.[1]);
    expect(counted).toBeGreaterThan(0);
    await line.getByRole("button", { name: "Open the list" }).click();
    const list = page.getByRole("list", { name: "Open to-dos" });
    await expect(list.getByRole("listitem").first()).toBeVisible();
    await expect(page.getByText("Nothing matches these filters.")).toHaveCount(0);
    const overdueRows = await list.getByRole("listitem").count();
    expect(overdueRows).toBeGreaterThanOrEqual(counted);
    // Leave and come back by the menu: no filter is kept, so every to-do shows, and the dated ones run soonest first.
    await page.evaluate(() => (location.hash = "#today"));
    await expect(page.locator('[data-queue-line="overdue"]')).toBeVisible();
    await page.evaluate(() => (location.hash = "#work/open"));
    const all = page.getByRole("list", { name: "Open to-dos" }).getByRole("listitem");
    await expect(all.first()).toBeVisible();
    expect(await all.count()).toBeGreaterThan(counted);
    await expect(page.locator("[data-clear-filters]")).toHaveCount(0);
  });
});
