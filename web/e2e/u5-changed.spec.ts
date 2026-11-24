// What changed and the shell (the UI/UX review of build 63, batch U5: S3, S4, S10, M3): at exactly 1024×768 no screen that has a
// detail pane opens one over its list on arrival; the icon rail and the labelled menu show an entry's name, and what its count
// counts, on hover and on focus; a press outside a row's menu on What changed closes it.
import { expect, type Locator, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

const change = (n: number, state: "review" | "done") => ({
  id: `REQ-${n}`,
  version: 1,
  state,
  created_at: "2026-10-30T09:00:00Z",
  dismissed: false,
  first_go: false,
  stage_task: false,
  refused: false,
  waiting: null,
  note: null,
  source: null,
  source_title: `Confirm the seating plan ${n}`,
  changeset: { id: `CS-${n}`, summary: "", status: "applied", reviewed: state === "done", trust: "trusted", ops: [{ index: 0, op: "fact", status: "applied", reason: null, group: "op0", title: `A fact ${n}`, meta: { owners: [] }, evidence: null, record: { kind: "fact", id: `FACT-${n}` }, ask: null }] },
});

/** Moves the pointer onto an element the way a hand does, in a few steps: the tooltip opens on a pointer that moves over it, not on one that appears. */
async function pointAt(page: Page, target: Locator) {
  const box = (await target.boundingBox())!;
  await page.mouse.move(box.x + 2, box.y + box.height + 20);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 6 });
}

async function serveChanges(page: Page) {
  await page.route("**/api/changes", (route) => route.fulfill({ json: [change(1, "review"), change(2, "done"), change(3, "review")] }));
}

test.describe("batch U5: What changed and the shell", () => {
  for (const screen of ["work/changed", "work/open", "work/followups", "records/people"]) {
    test(`at exactly 1024×768 ${screen} opens nothing over its list on arrival`, async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await openScreen(page, screen);
      const split = page.locator("[data-split]").first();
      await expect(split).toBeVisible();
      // Overlay is the one mode that lays a pane over the list: it is never on arrival.
      expect(await split.getAttribute("data-pane")).not.toBe("overlay");
      const list = (await page.locator("[data-split] > [data-region]").first().boundingBox())!;
      const pane = page.locator("aside[data-detail-pane]");
      if ((await pane.count()) > 0) {
        const box = (await pane.boundingBox())!;
        expect(box.x, "a pane on arrival stands beside the list, never over it").toBeGreaterThanOrEqual(list.x + list.width - 1);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  }

  test("at 1024×768 What changed's rows keep their Looks good with no detail over them", async ({ page }) => {
    await serveChanges(page);
    await page.setViewportSize({ width: 1024, height: 768 });
    await openScreen(page, "work/changed");
    await expect(page.locator("aside[data-detail-pane]")).toHaveCount(0);
    const rows = page.locator("[data-row-list]:not([data-detail]) > li[data-row]");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0).getByRole("button", { name: "Looks good" })).toBeVisible();
    await expect(rows.nth(2).getByRole("button", { name: "Looks good" })).toBeVisible();
  });

  for (const width of [1024, 1440]) {
    test(`at ${width}px hovering and focusing a menu entry shows its name, and with a count what it counts`, async ({ page }) => {
      await serveChanges(page);
      await page.setViewportSize({ width, height: 800 });
      await openScreen(page, "today");
      const nav = page.getByRole("navigation", { name: "Views" });
      const people = nav.locator('a[data-view="records/people"]');
      await pointAt(page, people);
      await expect(page.getByRole("tooltip")).toHaveText("People");
      await page.mouse.move(700, 500, { steps: 4 });
      await expect(page.getByRole("tooltip")).toHaveCount(0);
      // An entry that carries a count: the tooltip says what the number counts, in words, the same as its spoken name.
      const counted = nav.locator('a[data-view="work/changed"]');
      const spoken = (await counted.getAttribute("aria-label"))!;
      expect(spoken).toMatch(/^What changed, .+/);
      await pointAt(page, counted);
      await expect(page.getByRole("tooltip")).toHaveText(spoken);
      await page.mouse.move(700, 500, { steps: 4 });
      await expect(page.getByRole("tooltip")).toHaveCount(0);
      // The keyboard gets the same.
      await people.focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      await expect(page.getByRole("tooltip")).toHaveText("People");
    });
  }

  test("a press outside a row's menu on What changed closes it", async ({ page }) => {
    await serveChanges(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openScreen(page, "work/changed");
    const rows = page.locator("[data-row-list]:not([data-detail]) > li[data-row]");
    await rows.nth(1).getByRole("button", { name: /^More actions for/ }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    // A press on another row, then on the heading, each closes it (a real press at the place, as an open menu holds the page's own
    // elements out of the pointer's reach, so the press is made on the page and not on an element).
    const pressAt = async (target: Locator) => {
      const box = (await target.boundingBox())!;
      await page.mouse.click(box.x + 6, box.y + box.height / 2);
    };
    await pressAt(rows.nth(2).locator("[id^='t-']").first());
    await expect(page.getByRole("menu")).toHaveCount(0);
    await rows.nth(1).getByRole("button", { name: /^More actions for/ }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    await pressAt(page.getByRole("heading", { level: 1, name: "What changed" }));
    await expect(page.getByRole("menu")).toHaveCount(0);
  });
});
