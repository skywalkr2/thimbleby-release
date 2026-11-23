// People the assistant finds in the person's mail are ongoing, never a setup task (H5-78, H5-79): a fresh install, the People
// step left out on purpose because nothing had been found, every other step settled, then a look's people arrive. They are a line
// of their own on Today (not a list inside the step that was skipped), the walkthrough stays shut, and taking people is one change
// each, folded into one row of What changed that says what the person did and opens to their names.
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { test } from "./test";
import { pressStart, showSteps } from "./journey-helpers";

const LOADED = { timeout: 30_000 };
const AUTH = { Authorization: "Bearer e2e-token" };
const OTHER_STEPS = ["workspace", "work", "ai", "mail", "backup"];

const offerPeople = async (request: APIRequestContext, baseURL: string, count: number) => {
  const made = await request.post(new URL("/__e2e/offer-people", baseURL).toString(), { data: { count } });
  expect(made.ok(), await made.text()).toBe(true);
};

/** A person's path: skip People with nobody found (confirmed), settle every other step, finish the walkthrough's work. */
async function skipPeopleAndSettleTheRest(page: Page, request: APIRequestContext) {
  await page.goto("?token=e2e-token");
  await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible(LOADED);
  await pressStart(page);
  await showSteps(page);
  await page.getByRole("navigation", { name: /steps/i }).locator('button[data-screen="people"]').click();
  await expect(page.getByRole("heading", { level: 2, name: "People" })).toBeVisible(LOADED);
  await page.getByRole("button", { name: "I'll do this later" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Leave it out" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  for (const step of OTHER_STEPS) {
    const done = await request.post(`api/setup/${step}/skip`, { headers: AUTH });
    expect(done.ok(), await done.text()).toBe(true);
  }
  const view = await (await request.get("api/setup", { headers: AUTH })).json();
  expect(view.walkthrough.open).toBe(false);
  expect(view.steps.find((s: { id: string }) => s.id === "people").skipped).toBe(true);
}

test.describe.configure({ mode: "serial" });

test("people found after the step was skipped are a line on Today and the walkthrough stays shut (H5-78)", async ({ page, request, baseURL }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await skipPeopleAndSettleTheRest(page, request);
  await offerPeople(request, baseURL!, 3);
  await page.goto("?token=e2e-token#today");
  const line = page.locator('[data-queue-line="people_offers"]');
  await expect(line).toBeVisible(LOADED);
  await expect(line).toContainText("Pick which of the 3 people found in your mail to add");
  // Not inside what was learned, and the walkthrough did not come back on any screen.
  await expect(page.locator('[data-queue-line="learned"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toHaveCount(0);
  await page.reload();
  await expect(line).toBeVisible(LOADED);
  await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("today-people-offers.png"), fullPage: true });
});

test("a later look's people arrive on Today the same way, and taking three is one row in What changed (H5-78, H5-79)", async ({ page, request, baseURL }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("?token=e2e-token#today");
  const line = page.locator('[data-queue-line="people_offers"]');
  await expect(line).toBeVisible(LOADED);
  // A weekly look finds one more person after setup is over.
  const more = await request.post(new URL("/__e2e/offer-people", baseURL!).toString(), { data: { count: 1, from: 4 } });
  expect(more.ok()).toBe(true);
  await page.reload();
  await expect(line).toContainText("Pick which of the 4 people found in your mail to add", LOADED);
  await line.getByRole("button", { name: "Pick" }).click();
  const drawer = page.getByRole("dialog");
  for (const n of [1, 2, 3]) {
    await drawer.locator("[data-person-offer]").filter({ hasText: `Offered Person ${n}` }).getByRole("button", { name: "Add to People" }).click();
    await expect(drawer.locator("[data-person-offer]").filter({ hasText: `Offered Person ${n}` })).toHaveCount(0, LOADED);
  }
  await page.keyboard.press("Escape");
  await page.evaluate(() => {
    window.location.hash = "work/changed";
  });
  await expect(page.getByRole("heading", { level: 1, name: "What changed" })).toBeVisible(LOADED);
  // One row says what the person did; opening it lists the three, each named for the person, and nothing says "Reginald did".
  const row = page.getByRole("button", { name: "You added 3 people", exact: true });
  await expect(row).toHaveCount(1, LOADED);
  if ((await row.getAttribute("aria-expanded")) !== "true") await row.click();
  for (const n of [1, 2, 3]) await expect(page.getByRole("button", { name: `Your change · Added Offered Person ${n}`, exact: true })).toHaveCount(1, LOADED);
  await expect(page.getByRole("button", { name: /^Added Offered Person|^Your change · Added Offered/ })).toHaveCount(3);
  await expect(page.locator("main")).not.toContainText(/did \d things?/);
  // No row says nothing: there is no bare "Changed on screen" beside them, and the fourth person was not taken.
  await expect(page.getByText("Changed on screen")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("what-changed-people-added.png"), fullPage: true });
  // The one left on Today is the fourth person.
  await page.evaluate(() => {
    window.location.hash = "today";
  });
  await expect(line).toContainText("Pick whether to add the person found in your mail", LOADED);
});
