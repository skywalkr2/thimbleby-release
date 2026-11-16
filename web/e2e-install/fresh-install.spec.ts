// A fresh install of the built app, read as a person reads it (S-0459). The app is the installed one, already running on
// its own computer-only address (FRESH_INSTALL_URL, with the sign-in link's token in FRESH_INSTALL_TOKEN); the script
// that drives the install (deploy/desktop/build_support/fresh_install_check.py) runs this once per visit:
//   first: the walkthrough opens by itself, and skipping every step (never typing) reaches Today;
//   again: after the app was closed and opened again, and after the new version was put over the old one, the walkthrough
//          is not asked again and Today opens straight away, so the work was kept.
import { expect, test, type Page } from "@playwright/test";

const visit = process.env.FRESH_INSTALL_VISIT ?? "first";
const token = process.env.FRESH_INSTALL_TOKEN ?? "";
const today = (page: Page) => page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ });

test("a fresh install opens on the walkthrough and skipping it reaches Today, and later visits open on Today", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));
  await page.goto(`./?token=${token}`);
  if (visit === "again") {
    await expect(today(page)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toHaveCount(0);
  } else {
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible({ timeout: 60_000 });
    const main = page.getByRole("main");
    const start = main.getByRole("button", { name: "Start", exact: true });
    if (await start.isVisible()) await start.click();
    // The first step needs a name; every later step is passed with "I'll do this later", until Today is shown.
    const name = main.getByLabel("Your full name");
    if (await name.isVisible()) {
      await name.fill("Sam Example");
      await main.getByRole("button", { name: "Continue" }).click();
    }
    // Each step's own way on: "I'll do this later" where a step offers it, else its Continue, and on the last step
    // "Go to Today". Never the header's "Finish later", which leaves setup unfinished. Each click waits for the next
    // step's heading rather than a fixed time.
    for (let step = 0; step < 30 && !(await today(page).isVisible()); step++) {
      const heading = await main.getByRole("heading", { level: 2 }).first().textContent();
      const skip = main.getByRole("button", { name: "I'll do this later", exact: true }).first();
      const next = main.getByRole("button", { name: /^(Continue|Go to Today)$/ }).first();
      if (await skip.isVisible()) await skip.click();
      else await next.click();
      await expect
        .poll(async () => (await today(page).isVisible()) || (await main.getByRole("heading", { level: 2 }).first().textContent()) !== heading, { timeout: 30_000 })
        .toBe(true);
    }
    await expect(today(page)).toBeVisible({ timeout: 30_000 });
  }
  await page.screenshot({ path: info.outputPath(`today-${visit}.png`), fullPage: false });
  expect(problems).toEqual([]);
});
