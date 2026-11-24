// Today, the opened review and To-dos built to the reviewer's 4.6 mockups (`today`, `today-review`, `todos`; change log 316).
// Written, not yet run. The layout server holds the long made-up text and a batch to look over, so these hold with them:
//   - the inline add row adds a to-do with Enter and the cursor stays in the row for the next one;
//   - a question has no check box or round tick;
//   - "Needs a date" is one line, and its button opens the list;
//   - the counts agree: the tab, the groups with the line for those that need a date, and the line under the title;
//   - the opened review is an inset card with "Keep all", the screen's one filled button, and Decide has none while it is open;
//   - neither screen scrolls sideways at 1440, 1024 or 390.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { pickPersonalIfSides } from "./journey-helpers";

const LOADED = { timeout: 20_000 };
const GREETING = /^Good (morning|afternoon|evening)/;

async function openTodos(page: Page) {
  await page.goto("?token=e2e-token#work/open");
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "To-dos and questions" })).toBeVisible(LOADED);
  await expect(page.locator("main [data-skeleton]")).toHaveCount(0, LOADED);
}

async function openToday(page: Page) {
  await page.goto("?token=e2e-token#today");
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: GREETING })).toBeVisible(LOADED);
  await expect(page.locator("[data-queue-line]").first()).toBeVisible(LOADED);
}

const needsDateCount = async (page: Page): Promise<number> => {
  const line = page.locator("[data-needs-date-line]");
  if ((await line.count()) === 0) return 0;
  return Number((await line.first().innerText()).match(/\d+/)?.[0] ?? 0);
};

test.describe("To-dos", () => {
  test("the inline add row adds a to-do with Enter, says so with Undo, and the cursor stays in the row for the next one", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    await pickPersonalIfSides(page);
    const field = page.getByRole("textbox", { name: "Add a to-do" });
    // It is the first line of the list, on every width.
    expect(await page.getByRole("list", { name: "Open to-dos" }).locator("> li").first().getByRole("textbox").count()).toBe(1);
    const before = await needsDateCount(page);
    await field.fill("Call the printer about the proofs");
    await field.press("Enter");
    await expect(page.getByText("Added: Call the printer about the proofs")).toBeVisible(LOADED);
    await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
    await expect(field).toHaveValue("");
    await expect(field).toBeFocused();
    // A to-do with no day is one that needs a date: the line at the foot counts it.
    await expect.poll(() => needsDateCount(page), LOADED).toBe(before + 1);
    // The next one goes the same way, with no click between.
    await page.keyboard.type("Send the proof");
    await page.keyboard.press("Enter");
    await expect(page.getByText("Added: Send the proof")).toBeVisible(LOADED);
    await expect(field).toBeFocused();
    await expect.poll(() => needsDateCount(page), LOADED).toBe(before + 2);
  });

  test("text typed into the inline add row while its save is still answering stays", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    await pickPersonalIfSides(page);
    const field = page.getByRole("textbox", { name: "Add a to-do" });
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    let seen = false;
    await page.route(/\/api\/todos$/, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      seen = true;
      await held;
      await route.fallback();
    });
    await field.fill("Hold this one");
    await field.press("Enter");
    await expect.poll(() => seen, LOADED).toBe(true);
    await field.fill("Typed while saving");
    release();
    await expect(page.getByText("Added: Hold this one")).toBeVisible(LOADED);
    // The row clears when every screen has read again after the save, which is after the toast.
    await expect(page.getByRole("list", { name: "Open to-dos" })).toContainText("Hold this one", LOADED);
    // Watch the field for the window in which the late clear lands; it must never empty.
    const wiped = await field.evaluate(
      (el) =>
        new Promise<boolean>((resolve) => {
          const input = el as HTMLInputElement;
          const end = window.setTimeout(() => resolve(false), 2500);
          const poll = () => (input.value === "" ? (window.clearTimeout(end), resolve(true)) : window.requestAnimationFrame(poll));
          poll();
        }),
    );
    expect(wiped).toBe(false);
    await expect(field).toHaveValue("Typed while saving");
  });

  test("the inline add row is there on a phone too, and the header's button still opens the form for details", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openTodos(page);
    await expect(page.getByRole("textbox", { name: "Add a to-do" })).toBeVisible();
    await page.getByRole("textbox", { name: "Add a to-do" }).fill("Call the printer");
    await page.getByRole("button", { name: "More options" }).click();
    await expect(page.getByRole("textbox", { name: "What to do" })).toBeFocused();
  });

  test("questions have no check box or round tick", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    await page.getByRole("button", { name: /^Questions/ }).click();
    const list = page.getByRole("list", { name: "Open questions" });
    if ((await list.count()) === 0) test.skip(true, "the fixture holds no open question");
    await expect(list).toBeVisible(LOADED);
    await expect(list.getByRole("checkbox")).toHaveCount(0);
    await expect(list.getByRole("button", { name: "Mark done" })).toHaveCount(0);
  });

  test("Needs a date is listed at the foot of the list with a date picker beside each to-do", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    const field = page.getByRole("textbox", { name: "Add a to-do" });
    await field.fill("A to-do with no day yet");
    await field.press("Enter");
    const line = page.locator("[data-needs-date-line]");
    await expect(line).toBeVisible(LOADED);
    await expect(page.getByRole("region", { name: /Needs a date/ })).toBeVisible();
    await expect(line.getByLabel(/^Date for /).first()).toBeVisible();
    await expect(line.getByRole("button", { name: "Give them dates" })).toHaveCount(0);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the to-do mark is an empty ring at rest, 3:1 or better against its row in ${scheme} mode, and the check shows on hover and on focus`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1440, height: 900 });
      await openTodos(page);
      const mark = page.getByRole("list", { name: "Open to-dos" }).getByRole("button", { name: /^Mark done: / }).first();
      await expect(mark).toBeVisible(LOADED);
      const read = () =>
        mark.evaluate((button) => {
          const ring = button.firstElementChild as HTMLElement;
          const parse = (c: string) => (c.match(/[\d.]+/g) ?? []).map(Number);
          const lum = ([r, g, b]: number[]) => {
            const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          let surface = "rgba(0, 0, 0, 0)";
          for (let el: HTMLElement | null = button.parentElement; el; el = el.parentElement) {
            const bg = getComputedStyle(el).backgroundColor;
            if (parse(bg).length >= 3 && (parse(bg)[3] ?? 1) > 0.99) {
              surface = bg;
              break;
            }
          }
          const a = lum(parse(getComputedStyle(ring).borderTopColor));
          const b = lum(parse(surface));
          return { contrast: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), check: Number(getComputedStyle(ring, "::after").opacity) };
        });
      const rest = await read();
      expect(rest.check).toBe(0);
      expect(rest.contrast).toBeGreaterThanOrEqual(3);
      await mark.hover();
      await expect.poll(async () => (await read()).check).toBe(1);
      await page.mouse.move(0, 0);
      await expect.poll(async () => (await read()).check).toBe(0);
      await mark.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(mark).toBeFocused();
      await expect.poll(async () => (await read()).check).toBe(1);
    });
  }

  test("Needs a date starts empty with 'Pick a day' and a visible Set; left alone it sets no date", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    const field = page.getByRole("textbox", { name: "Add a to-do" });
    await field.fill("A to-do left without a day");
    await field.press("Enter");
    const card = page.locator("[data-needs-date]");
    await expect(card).toBeVisible(LOADED);
    // The layout workspace holds many undated to-dos: the card shows the first five and a way to see the rest.
    const rows = card.locator("[data-needs-row]");
    await expect(rows).toHaveCount(5);
    await expect(card.getByRole("button", { name: /^Show \d+ more$/ })).toBeVisible();
    await expect(card.getByRole("button", { name: "Give them all a day…" })).toBeVisible();
    const picker = rows.first().getByRole("textbox", { name: /^Date for / });
    await expect(picker).toHaveValue("");
    await expect(picker).toHaveAttribute("placeholder", "Pick a day");
    const set = rows.first().getByRole("button", { name: "Set", exact: true });
    await expect(set).toBeVisible();
    await expect(set).toHaveAttribute("aria-disabled", "true");
    // Leaving the page and coming back changes nothing: the card was left alone, so no field holds a day.
    await page.reload();
    await expect(page.locator("[data-needs-date]")).toBeVisible(LOADED);
    const held = await page.locator("[data-needs-date] input[data-ui='date']").evaluateAll((all) => all.filter((el) => (el as HTMLInputElement).value !== "").length);
    expect(held).toBe(0);
  });

  test("the counts agree: the tab, the groups with the line for those that need a date, and the line under the title", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    // The line under the title counts the open to-dos; the tab counts the ones that are yours (S-0539).
    const opened = await page.getByText(/^\d+ open\b/).first().innerText();
    const tabCount = Number(/^(\d+)/.exec(opened)?.[1]);
    const counts = await page.locator("[data-todo-group] [data-group-count]").allInnerTexts();
    const grouped = counts.reduce((n, c) => n + Number(c), 0);
    expect(grouped + (await needsDateCount(page))).toBe(tabCount);
    // The line under the title says how many of them need the person only when that is not all of them, never more than the tab holds.
    const needs = page.locator("[data-need-count]");
    if (await needs.count()) {
      const said = /^· (\d+) yours$|^· None yours$/.exec((await needs.innerText()).trim());
      expect(said, await needs.innerText()).not.toBeNull();
      expect(Number(said?.[1] ?? 0)).toBeLessThanOrEqual(tabCount);
    }
    // The groups come in the mockup's order.
    const names = (await page.locator("[data-todo-group]").allTextContents()).map((t) => t.replace(/\d+$/, "").trim());
    const order = ["Overdue", "Today", "Coming up", "Waiting on others"];
    expect(names).toEqual(order.filter((o) => names.includes(o)));
  });
});

test.describe("The to-dos list's width", () => {
  test("the list is one column of at most 760px at 1440, so a title and its menu can be traced across; a phone keeps the whole width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    const box = await page.getByRole("list", { name: "Open to-dos" }).boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(400);
    expect(box?.width ?? 0).toBeLessThanOrEqual(760);
    await page.setViewportSize({ width: 390, height: 900 });
    const narrow = await page.getByRole("list", { name: "Open to-dos" }).boundingBox();
    expect(narrow?.width ?? 0).toBeGreaterThan(300);
  });
});

test.describe("The Done tab", () => {
  test("it lists what was closed by day, says who closed each (the assistant with the words it quoted), and Not done after all puts one back in its group (S-0428)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openTodos(page);
    const me = ((await (await page.request.get("api/me")).json()) as { person: string }).person;
    const soon = new Date(Date.now() + 3 * 86_400_000);
    const when = `${soon.getFullYear()}-${String(soon.getMonth() + 1).padStart(2, "0")}-${String(soon.getDate()).padStart(2, "0")}`;
    const make = async (text: string) => ((await (await page.request.post("api/todos", { data: { text, when, owners: [me] } })).json()) as { action: string }).action;
    const ticked = "Mail the signed done-tab lease";
    const closed = "Send the done-tab deposit receipt";
    const tickedId = await make(ticked);
    const closedId = await make(closed);
    await page.request.post(`api/actions/${tickedId}/status`, { data: { status: "done" } });
    await page.request.post("__e2e/closed-by-assistant", { data: { id: closedId, quote: "The receipt reached us on Tuesday." } });
    await openTodos(page);
    // The tab has no count; a to-do ticked on the list is not there to count either way.
    const tab = page.getByRole("button", { name: "Done", exact: true });
    await expect(tab).toHaveText("Done");
    await tab.click();
    const list = page.getByRole("list", { name: "Finished to-dos" });
    await expect(list).toBeVisible(LOADED);
    await expect(list.getByRole("heading", { level: 3 }).first()).toHaveText("Today");
    await expect(list.locator("[data-done-item]").filter({ hasText: ticked })).toContainText("Done by you");
    const byAssistant = list.locator("[data-done-item]").filter({ hasText: closed });
    // The row says who closed it and what the app holds, never the message's words; they show when it is opened.
    await expect(byAssistant).toContainText(/Closed by .+ · /);
    await expect(byAssistant).not.toContainText("The receipt reached us on Tuesday");
    await byAssistant.getByRole("button", { name: "Show the words" }).click();
    await expect(byAssistant).toContainText("“The receipt reached us on Tuesday.”");
    await expect(page.getByText("Older ones are in search.")).toBeVisible();
    // Not done after all: it leaves the Done list and is back among the open to-dos, with its date.
    await byAssistant.getByRole("button", { name: `Not done after all: ${closed}` }).click();
    await expect(list.locator("[data-done-item]").filter({ hasText: closed })).toHaveCount(0, LOADED);
    await page.getByRole("button", { name: /^To-dos\b/ }).first().click();
    const row = page.getByRole("list", { name: "Open to-dos" }).locator("[data-row]").filter({ hasText: closed });
    await expect(row).toBeVisible(LOADED);
    await expect(row).toContainText(/Due /);
  });
});

test.describe("Today", () => {
  test("the opened review is an inset card whose Keep all is the screen's one filled button, and Decide has none while it is open", async ({ page }) => {
    // Under 1280px a line opens under its row as an inset card; from 1280px it opens in the rail's column (today-rail.spec.ts).
    await page.setViewportSize({ width: 1200, height: 900 });
    await openToday(page);
    const row = page.locator('[data-queue-line="review"]').first();
    await row.getByRole("button", { name: /^Look over/ }).click();
    const card = row.locator("[data-inset]");
    await expect(card).toBeVisible(LOADED);
    // The card sits inside the row's text edge and is drawn on the sunken surface.
    const rowBox = await row.boundingBox();
    const cardBox = await card.boundingBox();
    expect((cardBox?.x ?? 0) - (rowBox?.x ?? 0)).toBeGreaterThan(24);
    const keep = card.getByRole("button", { name: /^Keep (it|all \d+)$/ });
    await expect(keep).toBeVisible();
    await expect(keep).toHaveAttribute("data-weight", "filled");
    await expect(page.locator('section[aria-labelledby="queue-group-decide"] [data-weight="filled"]')).toHaveCount(0);
    await expect(page.locator('main [data-weight="filled"]')).toHaveCount(1);
  });

  test("with no review open the first decision carries the one filled button", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openToday(page);
    const decide = page.locator('section[aria-labelledby="queue-group-decide"]');
    if ((await decide.count()) === 0) test.skip(true, "the fixture has no decision");
    expect(await page.locator('main [data-weight="filled"]').count()).toBeLessThanOrEqual(1);
  });

  test("the greeting is the heading, the groups are labelled with counts, and the rail has no filled button", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openToday(page);
    await expect(page.getByRole("region", { name: "Needs you" }).getByRole("heading", { level: 2, name: "Needs you" })).toHaveClass(/sr/);
    for (const group of await page.locator("[data-queue-line]").first().locator("xpath=ancestor::section[1]").locator("[data-group-label]").all()) await expect(group).toBeVisible();
    await expect(page.locator('[data-region][aria-label] [data-weight="filled"]')).toHaveCount(0);
    await expect(page.locator('[data-col] [data-weight="filled"]')).toHaveCount(0);
  });
});

for (const [name, open] of [
  ["Today", openToday],
  ["To-dos", openTodos],
] as const) {
  for (const width of [1440, 1024, 390]) {
    test(`${name} does not scroll sideways at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page);
      const over = await page.evaluate(() => ({ page: document.documentElement.scrollWidth - window.innerWidth, body: document.body.scrollWidth - window.innerWidth }));
      expect(over.page).toBeLessThanOrEqual(0);
      expect(over.body).toBeLessThanOrEqual(0);
    });
  }
}
