// A fresh install of the built app, read as a person reads it (S-0459). The app is the installed one, already running on
// its own computer-only address (FRESH_INSTALL_URL, with the sign-in link's token in FRESH_INSTALL_TOKEN); the script
// that drives the install (deploy/desktop/build_support/fresh_install_check.py) runs this once per visit:
//   first: the walkthrough opens by itself, and skipping every step (never typing) reaches Today;
//   again: after the app was closed and opened again, and after the new version was put over the old one, the walkthrough
//          is not asked again and Today opens straight away, so the work was kept.
import { expect, test, type Page, type Request } from "@playwright/test";
import { writeFileSync } from "node:fs";

const visit = process.env.FRESH_INSTALL_VISIT ?? "first";
const token = process.env.FRESH_INSTALL_TOKEN ?? "";
const today = (page: Page) => page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ });

const slowOrFailed: string[] = [];
// Written after every visit, passed or failed, beside the pictures.
test.afterEach(({}, info) => {
  writeFileSync(info.outputPath("slow-or-failed-requests.txt"), slowOrFailed.length ? slowOrFailed.join("\n") + "\n" : "none\n");
});

test("a fresh install opens on the walkthrough and skipping it reaches Today, and later visits open on Today", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));
  // Every request that failed, was refused (status 400 or over) or took over two seconds, kept beside the pictures, so a
  // slow or failing install shows which request it was and how long it took. The file is written passed or failed.
  const noted = (request: Request, how: string) => {
    const timing = request.timing();
    const took = timing.responseEnd > 0 ? Math.round(timing.responseEnd) : -1;
    slowOrFailed.push(`${new Date().toISOString()} ${request.method()} ${new URL(request.url()).pathname} ${how} took ${took} ms`);
  };
  // The page's own event stream stays open for the whole visit and is cut when the visit ends, so it is not a failure.
  const stream = (request: Request) => new URL(request.url()).pathname.endsWith("/api/events");
  page.on("requestfailed", (request) => {
    if (!stream(request)) noted(request, `failed: ${request.failure()?.errorText ?? "unknown"}`);
  });
  page.on("requestfinished", (request) => {
    void request.response().then((response) => {
      if (stream(request)) return;
      if ((response && response.status() >= 400) || request.timing().responseEnd > 2000) noted(request, `status ${response?.status() ?? "none"}`);
    });
  });
  await page.goto(`./?token=${token}`);
  if (visit === "again") {
    await expect(today(page)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toHaveCount(0);
  } else {
    await expect(page.getByRole("heading", { level: 1, name: "Getting started" })).toBeVisible({ timeout: 60_000 });
    const main = page.getByRole("main");
    const start = main.getByRole("button", { name: "Start", exact: true });
    if (await start.isVisible()) await start.click();
    // The first step needs a name. Continue saves it before the screen moves on, so the walk waits for the step to
    // change before it reads the next one; reading it sooner presses the next step's button a step late.
    const heading = () => main.getByRole("heading", { level: 2 }).first().textContent();
    const name = main.getByLabel("Your full name");
    if (await name.isVisible()) {
      const before = await heading();
      await name.fill("Sam Example");
      await main.getByRole("button", { name: "Continue" }).click();
      await expect.poll(heading, { timeout: 60_000 }).not.toBe(before);
    }
    // Each step's own way on: "I'll do this later" where a step offers it, else its Continue, and on the last step
    // "Go to Today". Never the header's "Finish later", which leaves setup unfinished. A button is pressed only once it is
    // enabled and the step is still the one it was found on, and each press waits for the next step's heading rather than
    // a fixed time, so a slow computer takes longer and presses nothing early.
    for (let step = 0; step < 30 && !(await today(page).isVisible()); step++) {
      const here = await heading();
      const skip = main.getByRole("button", { name: "I'll do this later", exact: true }).first();
      const next = main.getByRole("button", { name: /^(Continue|Go to Today)$/ }).first();
      const button = (await skip.isVisible()) ? skip : next;
      await expect(button).toBeEnabled({ timeout: 60_000 });
      if ((await today(page).isVisible()) || (await heading()) !== here) continue;
      await button.click({ timeout: 30_000 });
      await expect.poll(async () => (await today(page).isVisible()) || (await heading()) !== here, { timeout: 60_000 }).toBe(true);
    }
    await expect(today(page)).toBeVisible({ timeout: 30_000 });
  }
  // What only an install can get wrong: the add-ons bundled with the app (S-0533) are on in the first workspace, and the
  // Add-ons screen opens and lists them.
  // The screen is opened by its own address in the page, so the signed-in page is not loaded again.
  await page.evaluate(() => {
    window.location.hash = "#settings/addons";
  });
  await expect(page.getByRole("heading", { level: 2, name: "Add-ons" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Installed" }).click();
  const row = page.getByRole("tabpanel").locator("[id$='-row']").filter({ hasText: /parcels/i });
  await expect(row, "the bundled parcels add-on is listed as installed").toHaveCount(1, { timeout: 30_000 });
  await expect(row.getByText("On", { exact: true }), "and it is on in the first workspace").toBeVisible();
  await page.evaluate(() => {
    window.location.hash = "#today";
  });
  await expect(today(page)).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: info.outputPath(`today-${visit}.png`), fullPage: false });
  expect(problems).toEqual([]);
});
