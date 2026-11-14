// Batch R4 (trust, mail, sides and counts), the closing tests of the review of fb08fa7a that need no mail service. Each follows the
// reviewer's own steps through the screen they named and reads what the person sees there. The workspace is the reviewer's many-sides
// state with a business's called-off meeting, overdue to-dos on two sides and on none, and two repeating entries of the person's own
// (tests/e2e_review_r4.py).
import { daytimeAt } from "./clock";
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { pickSide } from "./side-pick";

const LOADED = { timeout: 30_000 };
type Seed = Record<string, string | number | string[]>;
let seed: Seed;
const names = { first: "Harborview Community Support Partnership Incorporated", last: "Lantern Row Studio", other: "Willowbrook Handmade Ceramics and Garden Supply Cooperative" };

test.beforeAll(async ({ request }) => {
  seed = (await (await request.get("__e2e/review-r4")).json()) as Seed;
  expect(seed.enabled).toBeTruthy();
});

const today = async (page: Page, width = 1440) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("?token=e2e-token#today");
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
};
const lines = (page: Page, kind: string) => page.locator(`[data-queue-line="${kind}"]`);

test.describe("S-0355 / S-0357 (X80): Today under one side's filter", () => {
  test("a business's called-off meeting and its overdue to-dos show only under their own side, and a side with nothing of its own says so", async ({ page }) => {
    await today(page);
    // All: the meeting, and an overdue line for each side that has some and one for what is on no side.
    await expect(lines(page, "called_off")).toHaveCount(1, LOADED);
    await expect(lines(page, "overdue")).toHaveCount(3);
    // The side that owns the meeting sees it, with its own one overdue to-do and not the others' three.
    await pickSide(page, names.last);
    await expect(lines(page, "called_off")).toHaveCount(1, LOADED);
    await expect(lines(page, "called_off")).toContainText("Planning chat");
    await expect(page.locator("[data-queue-empty='side']")).toHaveCount(0);
    expect(await page.locator("main").innerText()).not.toMatch(/Send the board minutes|Pay the venue deposit/);
    // Another business: neither the meeting nor the first side's overdue to-dos; the to-do that is on no side stays, said to be for every side.
    await pickSide(page, names.first);
    await expect(lines(page, "called_off")).toHaveCount(0, LOADED);
    await expect(lines(page, "overdue")).toHaveCount(2);
    await expect(lines(page, "overdue").filter({ hasText: /^.*Finish 2 overdue/ })).toHaveCount(1);
    // A side with nothing of its own: the one line says so, and the lines left are not marked "Every side" row by row (the card says it once).
    await pickSide(page, names.other);
    await expect(lines(page, "called_off")).toHaveCount(0, LOADED);
    await expect(page.locator("[data-queue-empty='side']")).toHaveCount(1);
    await expect(page.locator("[data-queue-line] [data-every-side]")).toHaveCount(0);
    await pickSide(page, "All");
  });
});

test.describe("S-0369: Today offers preparation only for an entry the person chose a part for, or one with other people", () => {
  test("a repeating class with no part has no Prepare for, one they attend has", async ({ page }) => {
    await today(page);
    await expect(page.getByText(/Team sync/).first()).toBeVisible(LOADED);
    await expect(page.locator("[data-queue-line='meeting_prep']").filter({ hasText: "Team sync" })).toHaveCount(1, LOADED);
    await expect(page.locator("[data-queue-line='meeting_prep']").filter({ hasText: "Yoga class" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Prepare for Yoga class/ })).toHaveCount(0);
  });

  test("the add form starts with no part chosen, and the entry it makes has no Prepare for until a part is picked", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("?token=e2e-token#schedule");
    await expect(page.getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible(LOADED);
    // Forty minutes after the pinned moment, on the workspace's clock (UTC).
    const soon = new Date(new Date(daytimeAt).getTime() + 40 * 60_000);
    const clock = `${String(soon.getUTCHours()).padStart(2, "0")}:${String(soon.getUTCMinutes()).padStart(2, "0")}`;
    const add = async (title: string, part?: string) => {
      await page.getByRole("button", { name: /^Add (to schedule|an event|a meeting)$|^Add$/ }).first().click();
      const drawer = page.getByRole("dialog", { name: /^Add (a meeting|an event)$/ });
      await expect(drawer).toBeVisible(LOADED);
      const role = drawer.getByRole("combobox", { name: "Your part" });
      // Nobody else is on a form entry, so no part is chosen until the person picks one.
      await expect(role).toHaveText("Not chosen");
      await drawer.getByRole("textbox", { name: "What" }).fill(title);
      const start = drawer.getByRole("combobox", { name: /^Starts at/ });
      await start.fill(clock);
      await start.press("Tab");
      if (part) {
        await role.click();
        await page.getByRole("option", { name: part, exact: true }).click();
      }
      await drawer.getByRole("button", { name: "Add", exact: true }).click();
      await expect(drawer).toHaveCount(0, LOADED);
    };
    await add("Walk by the river");
    await add("Piano lesson", "I attend it");
    await page.goto("?token=e2e-token#today");
    await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible(LOADED);
    await expect(lines(page, "meeting_prep").filter({ hasText: "Piano lesson" })).toHaveCount(1, LOADED);
    await expect(lines(page, "meeting_prep").filter({ hasText: "Walk by the river" })).toHaveCount(0);
  });
});

test.describe("S-0346 (S3-B2): Handled for you, Undo after Bring it in", () => {
  test("the message goes back under its own group and with its own reason", async ({ page }) => {
    test.setTimeout(120_000);
    const handled = seed.handled as unknown as Array<{ title: string; reason: string }>;
    const [sale] = handled;
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("?token=e2e-token#work/handled");
    const folder = page.locator("[data-handled]");
    await expect(folder.getByRole("heading", { level: 1, name: "Handled for you" })).toBeVisible(LOADED);
    await expect(folder.locator("[data-group]").first()).toBeVisible(LOADED);
    const openAll = async () => {
      const closed = folder.locator("[data-group] > h2 button[aria-expanded=false]");
      for (let n = await closed.count(); n > 0; n = await closed.count()) await closed.first().click();
    };
    await openAll();
    const rowOf = (title: string) => folder.locator("[data-row-list] > li", { hasText: title });
    const groupOf = (title: string) => folder.locator("[data-group]").filter({ hasText: title });
    const before = {
      group: ((await groupOf(sale.title).locator("> h2").innerText()) ?? "").replace(/\s+/g, " ").trim(),
      row: ((await rowOf(sale.title).innerText()) ?? "").replace(/\s+/g, " ").trim(),
    };
    expect(before.row).toContain(sale.reason);
    await rowOf(sale.title).getByRole("button", { name: `Bring it in: ${sale.title}` }).click();
    // This person has sides, so it asks which one to bring it in as.
    await rowOf(sale.title).getByRole("button", { name: `Bring it in as Personal: ${sale.title}` }).click();
    await expect(rowOf(sale.title)).toHaveCount(0, LOADED);
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await openAll();
    await expect(rowOf(sale.title)).toHaveCount(1, LOADED);
    const after = {
      group: ((await groupOf(sale.title).locator("> h2").innerText()) ?? "").replace(/\s+/g, " ").trim(),
      row: ((await rowOf(sale.title).innerText()) ?? "").replace(/\s+/g, " ").trim(),
    };
    expect(after.group, "the message is back under its own group").toBe(before.group);
    expect(after.row, "and says why it was set aside as before").toBe(before.row);
  });
});

test.describe("S-0345 (S3-B1): one unknown name asked about by two inputs", () => {
  test("Today has one line for it, and the person's page counts what the Questions tab counts", async ({ page, request }) => {
    test.setTimeout(120_000);
    await today(page);
    // The decision question and the name are in Decide; the name once, though two inputs asked about it.
    await expect(page.locator('[data-queue-line="who_is"]').filter({ hasText: String(seed.unknown_name) })).toHaveCount(1, LOADED);
    // The Questions tab and the person's own page list the same questions, and neither lists the name twice.
    const tab = (await (await request.get("api/open-items", { headers: { Authorization: "Bearer e2e-token" } })).json()) as { questions: Array<{ id: string; title: string }> };
    await page.goto(`?token=e2e-token#records/person/${seed.me}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible(LOADED);
    const onPage = page.getByText(/Who is .?Someone New/);
    await expect(onPage).toHaveCount(0);
    expect(tab.questions.filter((q) => /^Who is/.test(q.title))).toHaveLength(0);
    await expect(page.getByText("Which paper for the program?").first()).toBeVisible(LOADED);
    expect(tab.questions.filter((q) => q.title === "Which paper for the program?")).toHaveLength(1);
  });
});
