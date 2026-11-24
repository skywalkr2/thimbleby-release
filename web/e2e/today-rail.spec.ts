// Today's rail and a line's items (design 7.7, 7.13; the UI/UX review of build 62, M1 and S2, S10): the rail sits beside the queue
// and stays in view while the page scrolls, as long as all of it fits; from 1280px a line the person opens shows in the rail's
// column, the queue holds still, one filled button is in view and Esc closes it; under 1280px the line opens under itself and Esc
// closes it there too; no width scrolls sideways. The queue is served by the test, so the checks are of the screen and not of the
// demo's data; it shares the server of Today's capacity, which no other scenario has added lines to.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

const base = { untrusted: false, unpriced: 0, actions: [] as string[], questions: [] as string[], outcome: {}, count: 1 };
const todo = (n: number, text: string) => ({ ...base, key: `item:CS-1:${n}`, group: "review", kind: "batch_item", what: "action", text, request: "REQ-1", changeset: "CS-1", op: n });
const review = {
  ...base,
  key: "review:REQ-1",
  group: "review",
  kind: "review",
  count: 2,
  request: "REQ-1",
  changeset: "CS-1",
  changesets: ["CS-1"],
  outcome: { actions_added: 2 },
  title: { kind: "email", person_name: "Robin Sample", topic: "spine options" },
  items: [todo(0, "Send two spine options"), todo(1, "Book the proof run")],
};
const stale = (n: number) => ({ ...base, key: `stale:A-${n}`, group: "review", kind: "stale", actions: [`A-${n}`], waiting_days: 30 + n, subject: `Tidy the proofs, round ${n}`, choices: ["keep", "drop", "snooze"] });
const lines = [
  { ...base, key: "decision:Q-1", group: "decide", kind: "decision", text: "Cover finish for the hardcover: matte or soft-touch?", question: "Q-1" },
  review,
  ...Array.from({ length: 14 }, (_, n) => stale(n + 1)),
];

async function serve(page: Page) {
  await page.route("**/api/today/queue", (route) => route.fulfill({ json: lines }));
  // No briefing and no calendar entries, so the rail is the schedule's one line and the setup card: short enough to stay in view.
  await page.route("**/api/brief*", (route) => route.fulfill({ json: { form: null, day: "2026-10-12", forms: [], quiet: true, afternoon_from_hour: 12, on_today: 0, sections: [], goals: null, message: null } }));
  await page.route("**/api/today/agenda", (route) => route.fulfill({ json: [] }));
}

const railOf = (page: Page) => page.getByRole("group", { name: "Briefing, schedule and mail" });
const tops = (page: Page) => page.locator("[data-queue-line]").evaluateAll((rows) => rows.map((row) => Math.round(row.getBoundingClientRect().top + window.scrollY)));
const filled = (page: Page) => page.locator('[data-weight="filled"]:visible').count();

test.describe("Today's rail", () => {
  for (const width of [1440, 1280]) {
    test(`at ${width}px the rail is beside the queue and stays in view while the page scrolls`, async ({ page }) => {
      await serve(page);
      await page.setViewportSize({ width, height: 900 });
      await openScreen(page, "today");
      const rail = railOf(page);
      await expect(rail.getByRole("region", { name: "Schedule" })).toBeVisible();
      // The schedule with nothing today or tomorrow is one line, not a panel.
      await expect(rail.getByText("No meetings today or tomorrow")).toBeVisible();
      const first = (await rail.boundingBox())!;
      const queue = (await page.locator("[data-queue-line]").first().boundingBox())!;
      expect(first.x).toBeGreaterThan(queue.x + queue.width);
      await expect(rail).toHaveAttribute("data-sticky", "");
      await page.evaluate(() => window.scrollTo(0, 700));
      await expect(async () => {
        const moved = (await rail.boundingBox())!;
        // Held under the header and the gutter, however far the queue has scrolled.
        expect(moved.y).toBeGreaterThan(40);
        expect(moved.y).toBeLessThan(120);
      }).toPass();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  }

  test("a rail taller than the window moves with the page and is never a scroll area of its own", async ({ page }) => {
    await serve(page);
    await page.setViewportSize({ width: 1440, height: 180 });
    await openScreen(page, "today");
    const rail = railOf(page);
    await expect(rail).toBeVisible();
    await expect(rail).not.toHaveAttribute("data-sticky", "");
    expect(await rail.evaluate((el) => getComputedStyle(el).overflowY)).not.toMatch(/auto|scroll/);
  });

  test("from 1280px a line opens in the rail's column: the queue holds still, one button is filled, and Esc closes it", async ({ page }) => {
    await serve(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await openScreen(page, "today");
    const row = page.locator('[data-queue-line="review"]');
    await expect(row).toBeVisible();
    const before = await tops(page);
    await row.getByRole("button", { name: "Look over", exact: true }).click();
    const pane = railOf(page).locator("[data-queue-inspector]");
    await expect(pane.getByText("Send two spine options")).toBeVisible();
    await expect(row.getByText("Send two spine options")).toHaveCount(0);
    expect(await tops(page)).toEqual(before);
    expect(await filled(page)).toBe(1);
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    expect(await tops(page)).toEqual(before);
    // The cursor is back on the line, so the keyboard carries on from there.
    await expect(row).toContainText("Look over");
    expect(await row.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  });

  test("under 1280px a line opens under itself, and Esc closes it there too", async ({ page }) => {
    await serve(page);
    await page.setViewportSize({ width: 1200, height: 900 });
    await openScreen(page, "today");
    const row = page.locator('[data-queue-line="review"]');
    await row.getByRole("button", { name: "Look over", exact: true }).click();
    await expect(row.getByText("Send two spine options")).toBeVisible();
    await expect(page.locator("[data-queue-inspector]")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(row.getByText("Send two spine options")).toHaveCount(0);
  });

  for (const width of [1440, 1280, 1100, 1024, 768]) {
    test(`at ${width}px nothing scrolls sideways, with a line open`, async ({ page }) => {
      await serve(page);
      await page.setViewportSize({ width, height: 900 });
      await openScreen(page, "today");
      await page.locator('[data-queue-line="review"]').getByRole("button", { name: "Look over", exact: true }).click();
      await expect(page.getByText("Send two spine options").first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme} mode Today passes the accessibility checks with a line open in the rail`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await serve(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openScreen(page, "today");
      await page.locator('[data-queue-line="review"]').getByRole("button", { name: "Look over", exact: true }).click();
      await expect(railOf(page).locator("[data-queue-inspector]").getByText("Send two spine options")).toBeVisible();
      await page.evaluate(() => window.scrollTo(0, 0));
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
});
