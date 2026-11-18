// Batch SH1, the shell holds still: the side menu keeps its place while the add-ons' entries arrive (S-0326), and a new version
// served while a review is open shows "An update is ready" and leaves the page and what is typed in it alone (S-0409). The project is
// `layout`. Routes the test controls stand for the slow or changed server; nothing here waits a fixed time.
import { expect, type Page, type Route } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

const LOADED = { timeout: 20_000 };

const PANEL = { name: "demo/extra", title: "Extra shelf", tab: "work", kind: "demo/thing", view: "list", columns: [], column_labels: {}, primary_action: null, row_actions: [] };

/** Every link of the side menu with where it sits. */
async function places(page: Page): Promise<Record<string, { x: number; y: number }>> {
  return page.locator('nav[aria-label="Views"] a').evaluateAll((links) =>
    Object.fromEntries(links.map((a) => [a.textContent?.trim() ?? "", { x: Math.round(a.getBoundingClientRect().x), y: Math.round(a.getBoundingClientRect().y) }])),
  );
}

test("the side menu keeps every link where it is while the add-ons' entries arrive", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // A first visit reads the add-ons' panels; this browser remembers them for the next one.
  await page.route("**/api/panels", (route: Route) => route.fulfill({ json: [PANEL] }));
  await openScreen(page);
  await expect(page.locator('nav[aria-label="Views"]').getByRole("link", { name: /Extra shelf/ })).toBeVisible(LOADED);
  await page.unroute("**/api/panels");
  // The next visit: the panels' read is held while the page draws, and the pointer rests on a link.
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let delivered: () => void = () => undefined;
  const arrived = new Promise<void>((resolve) => (delivered = resolve));
  await page.route("**/api/panels", async (route: Route) => {
    await gate;
    await route.fulfill({ json: [PANEL] });
    delivered();
  });
  await page.reload();
  const nav = page.locator('nav[aria-label="Views"]');
  await expect(nav.getByRole("link", { name: /Extra shelf/ })).toBeVisible(LOADED);
  const before = await places(page);
  await nav.getByRole("link", { name: "People" }).hover();
  release();
  await arrived;
  // Two frames after the answer, the entries have been drawn from it.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await places(page)).toEqual(before);
});

test("a new version served while a review is open shows An update is ready and leaves the page and what was typed alone", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openScreen(page);
  await page.evaluate(() => {
    (window as unknown as { loadedMarker: string }).loadedMarker = "still this page";
  });
  // The person has a review open and has typed into it.
  await page.getByRole("button", { name: "Hand something in" }).click();
  const dialog = page.getByRole("dialog");
  const field = dialog.getByRole("textbox").first();
  await field.fill("Ask about the proofs on Monday");
  // The server now says it serves another version; a change that names nothing makes the page read everything again, its
  // settings among it, as the stream's hello does when the app has started again.
  await page.route("**/api/runtime-config", async (route: Route) => {
    const real = await route.fetch();
    const body = (await real.json()) as { version: string };
    await route.fulfill({ response: real, json: { ...body, version: `${body.version}-next` } });
  });
  const nudged = await page.request.post("api/restore/dismiss", { headers: { Authorization: "Bearer e2e-token" } });
  expect(nudged.ok()).toBe(true);
  await expect(page.locator("[data-update-ready]")).toHaveCount(1, LOADED);
  await expect(page.locator("[data-update-ready]")).toContainText("An update is ready.");
  // Nothing reloaded: the review is still open with what was typed, and the page is the one that was loaded.
  await expect(dialog).toBeVisible();
  await expect(field).toHaveValue("Ask about the proofs on Monday");
  expect(await page.evaluate(() => (window as unknown as { loadedMarker?: string }).loadedMarker)).toBe("still this page");
});
