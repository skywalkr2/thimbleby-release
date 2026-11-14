// The fixes of bug hunt H1, proved in a browser on the hunt's own worst-case workspace (`--worst-case`: five sides, the last named
// with 100 characters, 50+ to-dos, a week of clashes, reviews held under several sides). The tests run in order: the first
// closes a review and undoes it, and the later ones read what is left.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choose } from "./choose";
import { openScreen } from "./open-screen";

test.describe.configure({ mode: "serial" });

const AUTH = { Authorization: "Bearer e2e-token" };

type Line = { key: string; kind: string; side: string | null; sides: string[]; held?: { record?: string } | null };

async function queue(page: Page): Promise<Line[]> {
  return (await (await page.request.get("api/today/queue", { headers: AUTH })).json()) as Line[];
}

/** Opens every group's "Show N more", so every line Today holds is drawn. */
async function showAll(page: Page): Promise<void> {
  const more = page.locator("main").getByRole("button", { name: /^Show \d+ more/ });
  while ((await more.count()) > 0) await more.first().click();
}

/** The lines Today draws, by their keys. */
async function drawn(page: Page): Promise<string[]> {
  await showAll(page);
  return page.locator("main [data-line-key]").evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.lineKey ?? ""));
}

test("a double press on Close it closes once, says nothing odd, and Undo brings the review and the count back (H1-01, H1-02)", async ({ page }) => {
  await openScreen(page, "today");
  await showAll(page);
  const first = (await queue(page)).find((l) => l.kind === "held");
  expect(first).toBeTruthy();
  const row = page.locator(`main [data-line-key="${first!.key}"]`);
  await expect(row).toBeVisible();
  const before = (await queue(page)).length;
  let releases = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/ops\/\d+\/release$/.test(request.url())) releases += 1;
  });
  await row.getByRole("button", { name: "Close it" }).dblclick();
  await expect(row).toHaveCount(0);
  const toasts = page.getByRole("region", { name: "Notifications" });
  await expect(toasts.getByText(/^Done:/)).toBeVisible();
  expect(releases).toBe(1);
  await expect(toasts.getByText(/didn't work|changeset|ops/)).toHaveCount(0);
  await toasts.getByRole("button", { name: "Undo" }).click();
  await expect(toasts.getByText("Undone.")).toBeVisible();
  await showAll(page);
  await expect(page.locator(`main [data-line-key="${first!.key}"]`)).toBeVisible();
  expect((await queue(page)).length).toBe(before);
});

test("under a side's filter Today draws only that side's lines and the lines about every side (H1-03)", async ({ page }) => {
  const lines = await (async () => {
    await openScreen(page, "today");
    return queue(page);
  })();
  const sides = [...new Set(lines.map((l) => l.side).filter((s): s is string => !!s))];
  expect(sides.length).toBeGreaterThan(1);
  const side = sides[0];
  await page.evaluate((id) => window.localStorage.setItem("cockpit:side-filter", id), side);
  await openScreen(page, "today");
  const shown = await drawn(page);
  const belong = (l: Line) => (l.sides.length ? l.sides.includes(side) : l.side === null || l.side === side);
  const expected = lines.filter(belong).map((l) => l.key);
  for (const key of shown.filter((k) => lines.some((l) => l.key === k))) expect(expected, key).toContain(key);
  // The held reviews of other sides' to-dos are not among them.
  for (const l of lines.filter((l) => l.kind === "held" && l.side !== side)) expect(shown).not.toContain(l.key);
  await page.evaluate(() => window.localStorage.removeItem("cockpit:side-filter"));
});

test("the Schedule's Work week and Week lists fit a 390px window: nothing reaches past its edge (H1-04)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openScreen(page, "schedule");
  for (const name of ["Work week", "Week"]) {
    await page.getByRole("tab", { name }).first().click();
    await expect(page.locator("main [data-schedule-list]")).toBeVisible();
    const over = await page.evaluate(() => {
      const edge = window.innerWidth;
      return [...document.querySelectorAll("main *")]
        .filter((el) => {
          const box = el.getBoundingClientRect();
          return box.width > 0 && box.right > edge + 1;
        })
        .map((el) => `${el.tagName}.${String(el.className).slice(0, 30)}`)
        .slice(0, 5);
    });
    expect(over, name).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
});

test("To-dos: Enter twice fast in the add form makes one to-do, and the menu's number is one the screen says (H1-05, H1-06)", async ({ page }) => {
  await openScreen(page, "work/open");
  const before = (await (await page.request.get("api/open-items", { headers: AUTH })).json()).actions.length as number;
  let adds = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/todos")) adds += 1;
  });
  await page.getByRole("textbox", { name: "Add a to-do" }).fill("Dup test tomorrow");
  await page.keyboard.press("Enter");
  const form = page.getByRole("dialog");
  await expect(form).toBeVisible();
  await choose(form.getByRole("combobox", { name: /Where does it belong/ }), "PRJ-1");
  // Add waits for the day to be read; then two presses, one straight after the other.
  await expect(form.getByText(/^Due [A-Z][a-z]{2}, /)).toBeVisible();
  await form.getByRole("textbox", { name: "What to do" }).focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(/^Added:/)).toBeVisible({ timeout: 20_000 });
  expect(adds).toBe(1);
  const after = (await (await page.request.get("api/open-items", { headers: AUTH })).json()).actions.length as number;
  expect(after).toBe(before + 1);
  // The number beside To-dos in the menu is said on the screen, in the same words.
  const menu = await page.getByRole("navigation").getByRole("link", { name: /^To-dos/ }).first().getAttribute("aria-label");
  const said = Number(/(\d+) (?:needs|need) you/.exec(menu ?? "")?.[1]);
  expect(said).toBeGreaterThan(0);
  const head = await page.locator("main").innerText();
  expect(head.includes(`${said} need you across to-dos and questions`) || head.includes(`${said} are yours`)).toBe(true);
});

test("every to-do with no owner is a Pick an owner line on Today (H1-07)", async ({ page }) => {
  await openScreen(page, "today");
  const owners = (await queue(page)).filter((l) => l.kind === "owner");
  expect(owners).toHaveLength(5);
  await showAll(page);
  await expect(page.locator('main [data-queue-line="owner"]').first()).toBeVisible();
});

test("a day alone in the add row is read as a day: the form opens with it and asks for the words (H1-10)", async ({ page }) => {
  await openScreen(page, "work/open");
  await page.getByRole("textbox", { name: "Add a to-do" }).fill("next Tuesday");
  await expect(page.getByText(/^Due [A-Z][a-z]{2}, /).first()).toBeVisible();
  await page.keyboard.press("Enter");
  const form = page.getByRole("dialog");
  await expect(form.getByRole("textbox", { name: "What to do" })).toHaveValue("");
  await expect(form.getByRole("textbox", { name: "Due (optional)" })).toHaveValue("next Tuesday");
});
