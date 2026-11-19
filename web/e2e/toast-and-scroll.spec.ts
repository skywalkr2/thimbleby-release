// The page's frame (H5-06, H5-11): a message never covers the page's title or the header's
// controls (or the step's buttons), on a setup step and on Today, at a desktop and a phone width; and the page scrolls only when its
// content is taller than the window, never by the pixel a hidden line used to add. A fresh install, walked as a person does.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { fakeAddress, pressStart, FIRST_SCREEN, toToday, type Info } from "./journey-helpers";

const FAKE = fakeAddress("JOURNEY_FRAME_FAKE_PORT", 8710);
const LOADED = { timeout: 30_000 };

let info: Info;

test.beforeAll(async () => {
  info = await (await fetch(`${FAKE}/__e2e/info`)).json();
});

type Box = [number, number, number, number];

/** The message's box and the boxes it must stay off: the page's title, every control in the header and every button of a step's footer. */
async function boxes(page: Page) {
  return page.evaluate(() => {
    const rect = (el: Element): Box => {
      const r = el.getBoundingClientRect();
      return [r.left, r.top, r.right, r.bottom];
    };
    const region = document.querySelector('[aria-label="Notifications"]')!;
    const toast = region.querySelector('[class*="toast"]');
    const visible = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    return {
      toast: toast ? rect(toast) : null,
      avoid: [
        ...Array.from(document.querySelectorAll("h1")),
        ...Array.from(document.querySelectorAll("header a, header button, header [role=button]")),
        ...Array.from(document.querySelectorAll("[data-step-footer] button")),
      ]
        .filter(visible)
        .map((el) => ({ what: `${el.tagName} ${(el.textContent ?? "").trim().slice(0, 30)}`, box: rect(el) })),
    };
  });
}

const overlaps = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

async function toastClearOfTheFrame(page: Page, label: string) {
  for (const [width, height] of [
    [1440, 900],
    [1280, 800],
    [1024, 768],
    [768, 1024],
    [390, 844],
  ]) {
    await page.setViewportSize({ width, height });
    const seen = await boxes(page);
    expect(seen.toast, `a message shows at ${width} on ${label}`).not.toBeNull();
    expect(seen.avoid.length, `there is a title and controls to avoid at ${width} on ${label}`).toBeGreaterThan(0);
    const covered = seen.avoid.filter((a) => overlaps(seen.toast!, a.box)).map((a) => a.what);
    expect(covered, `the message covers nothing at ${width} on ${label}`).toEqual([]);
  }
}

/** Whether the page scrolls up and down: its height beyond the window's. */
const spare = (page: Page) => page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight);

test("H5-06, H5-11. a message sits clear of the title, the header and the step's buttons, and the page scrolls only when its content is taller than the window", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto(`?token=${info.token}`);
  await expect(page.getByRole("heading", { level: 2, name: "Welcome", exact: true })).toBeVisible(FIRST_SCREEN);
  await pressStart(page);
  const main = page.locator("main#main");
  await expect(main.getByRole("heading", { level: 2, name: "You" })).toBeVisible(LOADED);
  await page.setViewportSize({ width: 1440, height: 1300 });
  expect(await spare(page), "no scroll bar on a setup step whose content fits (You, 1440 x 1300)").toBeLessThanOrEqual(0);
  await main.getByLabel("Your full name").fill(info.people[0]);
  await main.getByRole("button", { name: "Continue" }).click();
  await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
  for (const height of [900, 1300]) {
    await page.setViewportSize({ width: 1440, height });
    expect(await spare(page), `no scroll bar on a setup step whose content fits (1440 x ${height})`).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1440, height: 300 });
  expect(await spare(page), "a window shorter than the step scrolls").toBeGreaterThan(0);
  await page.setViewportSize({ width: 1440, height: 900 });

  // A job is added, then taken back out: the message says so, with Undo, over a step that has its footer.
  await main.getByRole("checkbox", { name: "A job" }).check();
  await main.getByRole("textbox", { name: /employer/i }).fill("Example Employer");
  await main.getByRole("button", { name: "Continue" }).click();
  await expect(main.getByRole("heading", { level: 2, name: "Your AI account" })).toBeVisible(LOADED);
  await main.getByRole("button", { name: "Back" }).click();
  await expect(main.getByRole("heading", { level: 2, name: "What it's for" })).toBeVisible(LOADED);
  await main.getByRole("button", { name: "Remove" }).click();
  const toasts = page.getByRole("region", { name: "Notifications" });
  await expect(toasts.getByRole("button", { name: "Undo" })).toBeVisible(LOADED);
  expect(await page.locator("[data-step-footer]").count(), "the step has its footer").toBe(1);
  await toastClearOfTheFrame(page, "a setup step");

  // Today: a message from putting the setup line away, with Undo.
  await page.setViewportSize({ width: 1440, height: 1300 });
  await toToday(page);
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
  expect(await spare(page), "no scroll bar on Today when its content fits (1440 x 1300)").toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "More actions for setup" }).click();
  await page.getByRole("menuitem", { name: "Hide" }).click();
  // The message about the setup line itself, not the earlier one about the job, which may still be on screen on a fast machine.
  await expect(toasts.getByText("Setup hidden from Today.")).toBeVisible(LOADED);
  await expect(toasts.getByRole("button", { name: "Undo" })).toBeVisible(LOADED);
  await toastClearOfTheFrame(page, "Today");
});
