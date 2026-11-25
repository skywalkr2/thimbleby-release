// One count model, a project's status beside what the app sees, and one word per state (the UI review's M3, M4 and M5): every count
// is the number of rows it labels, a status that disagrees with the data says why and offers Update status, and the header chip says
// a state in the word Today's line uses. It runs on the layout server.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";

const LOADED = { timeout: 20_000 };

const open = async (page: Page, hash: string) => {
  await page.goto(`?token=e2e-token#${hash}`);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOADED);
};

test.describe("counts, project status and state words", () => {
  test("To-dos: the tab's number is the rows it lists, the line under the title adds up to its open count, and the menu badge says what it counts", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "work/open");
    await expect(page.getByRole("list", { name: "Open to-dos" }).or(page.locator("[data-needs-date]")).first()).toBeVisible(LOADED);
    const tab = await page.getByRole("button", { name: /^To-dos\b/ }).first().innerText();
    const tabCount = Number(/(\d+)/.exec(tab)?.[1]);
    const grouped = (await page.locator("[data-todo-group] [data-group-count]").allInnerTexts()).reduce((n, c) => n + Number(c), 0);
    const dateLine = page.locator("[data-needs-date-line]");
    const undated = (await dateLine.count()) === 0 ? 0 : Number((await dateLine.first().innerText()).match(/\d+/)?.[0] ?? 0);
    // Under the default filters the tab holds every row the list shows, the undated ones included.
    expect(grouped + undated).toBe(tabCount);
    // "11 open: 6 overdue · 1 coming up · 4 need a date": the parts add up to the number before them.
    const rowsOpen = Number(/^(\d+) open/.exec(await page.getByText(/^\d+ open\b/).first().innerText())?.[1]);
    expect(rowsOpen).toBe(tabCount);
    const parts = page.locator("[data-open-parts]");
    if (await parts.count()) {
      const said = (await parts.innerText()).replace(/^:\s*/, "").split(" · ").reduce((n, p) => n + Number(/^(\d+)/.exec(p)?.[1] ?? 0), 0);
      expect(said).toBe(rowsOpen);
    }
    // The menu's badge is a different, named count: its link says in words what it counts.
    const link = page.locator("nav a[data-view='work/open']");
    const name = (await link.getAttribute("aria-label")) ?? "";
    if (name) expect(name).toMatch(/need(s)? you: /);
  });

  test("a project whose status says all is well beside overdue to-dos says why, and its page and row offer Update status", async ({ page }) => {
    await page.route("**/api/projects", async (route) => {
      const found = await (await route.fetch().catch(() => null))?.json();
      if (!found) return;
      const rows = (found as Array<Record<string, unknown>>).map((p, i) =>
        i === 0 && !p.side ? { ...p, status: p.status ?? "On track", status_meaning: "open", status_tone: "ok", completed: false, status_disagrees: true, overdue_actions: 6, quiet_weeks: 6 } : p,
      );
      await route.fulfill({ json: rows });
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "records/projects");
    const mark = page.locator("[data-status-disagrees]").first();
    await expect(mark).toBeVisible(LOADED);
    await expect(mark).toHaveText(/6 overdue · no change in 6 weeks/);
    await expect(page.getByRole("button", { name: /^Update status/ }).first()).toBeVisible();
    await expect(mark.locator("[data-icon]")).toHaveCount(1);
  });

  // U-23: the Status column holds the status and its reasons whole and "Last updated" is not cut.
  test("Projects at 1024, 1280 and 1440 px: a warning row stays a few lines tall, the status keeps its room and Last updated shows whole", async ({ page }) => {
    const weeksAgo = new Date(Date.now() - 43 * 86_400_000).toISOString();
    await page.route("**/api/projects", async (route) => {
      const found = await (await route.fetch().catch(() => null))?.json();
      if (!found) return;
      const rows = (found as Array<Record<string, unknown>>).map((p, i) =>
        i === 0 && !p.side ? { ...p, status: p.status ?? "On track", status_meaning: "open", status_tone: "ok", completed: false, status_disagrees: true, overdue_actions: 6, quiet_weeks: 6, last_change: weeksAgo } : p,
      );
      await route.fulfill({ json: rows });
    });
    for (const width of [1024, 1280, 1440]) {
      await page.setViewportSize({ width, height: 768 });
      await open(page, "records/projects");
      const mark = page.locator("[data-status-disagrees]").first();
      await expect(mark).toBeVisible(LOADED);
      const row = page.locator("tr", { has: mark }).first();
      const cells = await row.locator("td").evaluateAll((tds) =>
        tds.map((td) => {
          const box = td.querySelector<HTMLElement>("div,span") ?? (td as HTMLElement);
          return { w: Math.round(td.getBoundingClientRect().width), text: (td.textContent ?? "").trim().slice(0, 30), cut: box.scrollWidth > box.clientWidth };
        }),
      );
      const height = (await row.boundingBox())!.height;
      // The status keeps room for its reasons, so the row is a few lines and not a tall sliver; a shown "Last updated" is whole.
      expect(height, `row height at ${width}`).toBeLessThan(100);
      expect(cells[1].w, `Status width at ${width}`).toBeGreaterThanOrEqual(150);
      expect(cells[1].cut, `Status cut at ${width}`).toBe(false);
      if (cells[3].w > 0) expect(cells[3].cut, `Last updated cut at ${width}`).toBe(false);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), `sideways scroll at ${width}`).toBe(false);
    }
  });

  test("the chip and Today's line say a backup state in the same word", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "today");
    const chip = page.getByRole("button", { name: /^App status: / });
    await expect(chip).toBeVisible(LOADED);
    const line = page.locator("[data-queue-line='backup']");
    if ((await line.count()) === 0) return;
    const said = await line.first().textContent();
    // The plain nudge to pick a folder is not a warning: the chip stays quiet and carries no backup word.
    if (said?.includes("Pick a folder") || said?.includes("Keep a copy off this computer")) {
      await expect(chip).not.toContainText(/backup/i);
      return;
    }
    const words = ["No backup yet", "Backup failed", "Backup overdue"];
    const word = words.find((w) => said?.includes(w) || false);
    expect(word, said ?? "").toBeTruthy();
    await expect(chip).toContainText(word!);
  });
});
