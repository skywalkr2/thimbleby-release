// Projects and People tables (the UI/UX review of build 63, batch U6: M4, S8): the words a person reads in a cell are never cut
// off by an ellipsis (a role, the waiting pill, a status with its reasons), and a row's button stays on one line, at 1440 and
// 1024 wide, with the detail closed and open. Measured in the browser, as the review saw it.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

/** Every cell's inner box that is cut (its text wider than the box), as "column: text". */
async function cutCells(page: Page, only: string[]): Promise<string[]> {
  return page.evaluate((columns) => {
    const table = document.querySelector("table")!;
    const heads = [...table.querySelectorAll("thead th")].map((th) => th.textContent?.trim() ?? "");
    const cut: string[] = [];
    for (const tr of table.querySelectorAll("tbody tr[data-row]")) {
      [...tr.querySelectorAll("td")].forEach((td, i) => {
        const box = td.firstElementChild as HTMLElement | null;
        if (!box || !columns.includes(heads[i])) return;
        // The worst-case row of the demo (one very long word with no space) is cut by design; the test is about ordinary words.
        if (/\S{40,}/.test(box.textContent ?? "")) return;
        // The cell's content is wider than its box, or a child of it is wider than the box.
        const widest = Math.max(box.scrollWidth, ...[...box.querySelectorAll("*")].map((c) => (c as HTMLElement).scrollWidth));
        if (widest > box.clientWidth + 1) cut.push(`${heads[i]}: ${box.textContent}`);
      });
    }
    return cut;
  }, only);
}

const noSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test.describe("batch U6: Projects and People cells", () => {
  for (const width of [1440, 1024]) {
    for (const detail of [false, true]) {
      test(`People: Role and the waiting pill are whole at ${width} with the detail ${detail ? "open" : "closed"}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await openScreen(page, "records/people");
        if (detail) {
          await page.locator("tbody tr[data-row]").nth(1).click();
          await expect(page.locator("[data-detail-pane], [role=dialog]").first()).toBeVisible();
        }
        expect(await cutCells(page, ["Role", "Who they are", "Waiting on them"])).toEqual([]);
        expect(await noSideways(page)).toBe(true);
      });

      test(`Projects: the status and its reasons are whole, and Update status is one line, at ${width} with the detail ${detail ? "open" : "closed"}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await openScreen(page, "records/projects");
        if (detail) {
          await page.locator("tbody tr[data-row]").nth(1).click();
          await expect(page.locator("[data-detail-pane], [role=dialog]").first()).toBeVisible();
        }
        expect(await cutCells(page, ["Status"])).toEqual([]);
        const buttons = page.getByRole("button", { name: /^Update status/ });
        if ((await buttons.count()) > 0) {
          const box = (await buttons.first().boundingBox())!;
          // One line of text in a small button, never two.
          expect(box.height).toBeLessThan(40);
        }
        expect(await noSideways(page)).toBe(true);
      });
    }
  }
});
