// The calendar page (design 7.7): Day, Work week, Week and Month, never wider than the window at any of them, with a long
// unbroken title in an entry. Week and Work week fall back to Day in a space too narrow for their columns; an entry's details
// open beside the calendar and Escape returns the cursor to the entry. It shares the root server with the acceptance scenario
// and runs after it.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { momentAt } from "./clock";
import { openScreen } from "./open-screen";
import { test } from "./test";

// The work week is the working days, or the whole week when the run's day is a day off (a weekend), so the default view always
// holds today and skips no day. The test workspaces work Monday to Friday, on UTC.
const WORK = [0, 6].includes(new Date(momentAt).getUTCDay()) ? 7 : 5;

// The days shown after pressing 2 and then 3. Below 1100px the Week view is the working days; on a phone the week is a list by
// day (a section for each day, not a lane).
const SIZES = [
  // On a phone a day with entries is a section and the days with nothing are one line: the seeded day and that line.
  { width: 390, height: 844, lanes: { work_week: 2, week: 2 }, list: true },
  { width: 768, height: 900, lanes: { work_week: WORK, week: WORK } },
  { width: 1024, height: 900, lanes: { work_week: WORK, week: WORK } },
  { width: 1440, height: 900, lanes: { work_week: WORK, week: 7 } },
  { width: 2000, height: 1100, lanes: { work_week: WORK, week: 7 } },
];

/** A screen that loads on its first visit may draw after more than a screen's own wait when other projects' tests run beside this one. */
const LOADED = { timeout: 20_000 };

/** A long title with no break in it, made here so no outside text is written out. */
const LONG = "Quarterly".repeat(12);

async function seed(page: Page): Promise<string> {
  // Signed in first, so the requests below carry the session.
  await page.goto("?token=e2e-token");
  const today = ((await (await page.request.get("api/schedule")).json()) as { today: string }).today;
  for (const [what, time] of [
    [LONG, "09:30"],
    ["Walk through the proofs", "14:00"],
    ["Pick up the print order", null],
  ] as const) {
    const made = await page.request.post("api/calendar/meetings", { data: { what, day: today, time } });
    expect(made.ok()).toBe(true);
  }
  return today;
}

async function open(page: Page) {
  await openScreen(page, "schedule");
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible(LOADED);
  await expect(page.locator("main [data-skeleton]")).toHaveCount(0, { timeout: 15_000 });
  // The calendar's grid, or on a phone its list by day.
  await expect(page.locator("main [data-grid], main [data-month], main [data-schedule-list]").first()).toBeVisible(LOADED);
}

/** Picks a view with its key, which works while the cursor is on no control. */
async function pick(page: Page, key: "1" | "2" | "3" | "4") {
  await page.locator("body").press(key);
  // The view's range is read when it is picked, and a busy computer takes longer than an assertion's own wait for what it draws.
  await expect(page.locator("main [data-skeleton]")).toHaveCount(0, { timeout: 15_000 });
}

/**
 * Waits until what a view draws has stopped moving: in the Work week and Week views the week ahead card arrives after the grid is first
 * drawn and pushes it down, and the grid measures its own boxes again when its frame changes size. Settled is the grid, its lanes and their
 * entries keeping the same boxes for 12 frames in a row (frames, never a time, so a busy computer takes as long as it needs).
 */
async function settled(page: Page, weekCard: boolean) {
  if (weekCard) await expect(page.locator("main [data-week-ahead]")).toBeVisible(LOADED);
  await page.waitForFunction(
    () => {
      const w = window as unknown as { __still?: { sig: string; frames: number } };
      const sig = Array.from(document.querySelectorAll<HTMLElement>("main [data-grid], main [data-grid] ul[data-day], main [data-grid] [data-entry-key], main [data-group-card]"))
        .map((e) => {
          const r = e.getBoundingClientRect();
          return `${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.width)},${Math.round(r.height)}`;
        })
        .join("|");
      const now = w.__still;
      w.__still = { sig, frames: now && now.sig === sig ? now.frames + 1 : 0 };
      return w.__still.frames >= 12;
    },
    undefined,
    { polling: "raf", timeout: 30_000 },
  );
}

/** Waits for the view just picked to be drawn: a new range is read first, and a busy computer takes longer than an assertion's own wait. */
async function drawn(page: Page, anyOf = "main [data-grid], main [data-month], main [data-schedule-list]") {
  await expect(page.locator("main [data-skeleton]")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator(anyOf).first()).toBeVisible(LOADED);
}

/** What the page measures: no sideways scroll, and every day's box inside the window. */
async function measure(page: Page) {
  return page.evaluate(() => ({
    window: window.innerWidth,
    page: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    main: (document.querySelector("main") as HTMLElement).scrollWidth,
    days: Array.from(document.querySelectorAll("main [data-day]")).map((el) => {
      const box = el.getBoundingClientRect();
      return { left: Math.round(box.left), right: Math.round(box.right), top: Math.round(box.top) };
    }),
  }));
}

test.describe("the calendar page", () => {
  for (const size of SIZES) {
    test(`at ${size.width}px every view fits the window; the week has ${size.list ? "a list by day" : size.lanes.week + " days"}`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await seed(page);
      await open(page);
      const days = (key: string) => (size.list && key !== "1" ? page.locator("main [data-schedule-list] section[data-day], main [data-schedule-list] [data-nothing-on]") : page.locator("main ul[data-day]"));
      // The default view is the work week: its days, or a list by day on a phone.
      await expect(days("2")).toHaveCount(size.lanes.work_week, LOADED);
      for (const [key, count] of [
        ["1", 1],
        ["2", size.lanes.work_week],
        ["3", size.lanes.week],
      ] as const) {
        await pick(page, key);
        await expect(days(key)).toHaveCount(count, LOADED); // a new view reads its range first
        const found = await measure(page);
        expect(found.page).toBeLessThanOrEqual(found.window);
        expect(found.body).toBeLessThanOrEqual(found.window);
        for (const d of found.days) {
          expect(d.left).toBeGreaterThanOrEqual(0);
          expect(d.right).toBeLessThanOrEqual(found.window);
        }
        if (count > 1 && !size.list) {
          // Days sit side by side.
          expect(Math.abs(found.days[0].top - found.days[1].top)).toBeLessThanOrEqual(2);
          expect(found.days[1].left).toBeGreaterThan(found.days[0].left);
        }
      }
      await pick(page, "4");
      await expect(page.locator("main section[data-day]")).toHaveCount(42);
      const month = await measure(page);
      expect(month.page).toBeLessThanOrEqual(month.window);
      expect(month.body).toBeLessThanOrEqual(month.window);
      for (const d of month.days) expect(d.right).toBeLessThanOrEqual(month.window);
    });

    test(`at ${size.width}px a long unbroken title in Day view wraps inside its lane`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await seed(page);
      await open(page);
      await pick(page, "1");
      await expect(page.getByText(LONG).first()).toBeVisible();
      const found = await measure(page);
      expect(found.page).toBeLessThanOrEqual(found.window);
      expect(found.main).toBeLessThanOrEqual(found.window);
    });
  }

  test("the week ahead card is at the top of the Week and Work week views, above the calendar, and not in Day or Month", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    for (const key of ["2", "3"] as const) {
      await pick(page, key);
      const card = page.locator("main [data-week-ahead]");
      await expect(card).toBeVisible(LOADED);
      await expect(card.getByRole("heading", { name: "The week ahead" })).toBeVisible();
      const [cardBox, gridBox] = await Promise.all([card.boundingBox(), page.locator("main [data-grid]").first().boundingBox()]);
      expect(cardBox).not.toBeNull();
      expect(gridBox).not.toBeNull();
      expect(cardBox!.y + cardBox!.height).toBeLessThanOrEqual(gridBox!.y + 1); // the card is above the week's days
      const found = await measure(page);
      expect(found.page).toBeLessThanOrEqual(found.window);
    }
    for (const key of ["1", "4"] as const) {
      await pick(page, key);
      await expect(page.locator("main [data-week-ahead]")).toHaveCount(0);
    }
  });

  test("below 1100px the Week view is the working days and says so; at 1100px and over it is the whole week", async ({ page }) => {
    await seed(page);
    await page.setViewportSize({ width: 1024, height: 900 });
    await open(page);
    await pick(page, "3");
    await expect(page.locator("main ul[data-day]")).toHaveCount(WORK);
    await expect(page.locator("main [data-weekdays-only]")).toBeVisible();
    // The tab still says Week; nothing is wider than the window.
    await expect(page.getByRole("tab", { name: "Week", exact: true })).toHaveAttribute("aria-selected", "true");
    const narrow = await measure(page);
    expect(narrow.page).toBeLessThanOrEqual(narrow.window);
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.locator("main ul[data-day]")).toHaveCount(7);
    await expect(page.locator("main [data-weekdays-only]")).toHaveCount(0);
  });

  test("on a phone the week is a list by day, each entry a row that opens its details, and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const today = await seed(page);
    await open(page);
    await pick(page, "3");
    const list = page.locator("main [data-schedule-list]");
    await expect(list).toBeVisible();
    await expect(page.locator("main [data-grid]")).toHaveCount(0);
    await expect(list.locator(`section[data-day="${today}"]`).getByRole("button", { name: /Walk through the proofs/ })).toBeVisible();
    const found = await measure(page);
    expect(found.page).toBeLessThanOrEqual(found.window);
    expect(found.body).toBeLessThanOrEqual(found.window);
    await list.getByRole("button", { name: /Walk through the proofs/ }).click();
    await expect(page.getByRole("dialog").getByRole("heading", { name: "Walk through the proofs" })).toBeFocused();
  });

  for (const width of [1440, 1024, 390]) {
    test(`at ${width}px the Day, Week and Month views never scroll sideways, and pass the accessibility check`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await seed(page);
      await open(page);
      for (const key of ["1", "3", "4"] as const) {
        await pick(page, key);
        await drawn(page);
        const found = await measure(page);
        expect(found.page, `view ${key} at ${width}`).toBeLessThanOrEqual(found.window);
        expect(found.body).toBeLessThanOrEqual(found.window);
        // The Day view opens scrolled to now, which can put the toolbar under the page's sticky header; the check is of
        // the page from its top.
        await page.evaluate(() => window.scrollTo(0, 0));
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
        expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
      }
    });
  }

  test("each view has no accessibility violations, with an entry's details open", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    for (const key of ["1", "2", "3", "4"] as const) {
      await pick(page, key);
      await drawn(page, "main [data-grid], main [data-month]");
      await page.evaluate(() => window.scrollTo(0, 0));
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    }
    await pick(page, "1");
    await page.getByRole("button", { name: /Walk through the proofs/ }).click();
    await expect(page.getByRole("complementary", { name: "Walk through the proofs" })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });

  test("the arrow keys and buttons move by the view's unit and Today returns", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const today = await seed(page);
    await open(page);
    await pick(page, "1");
    // A day with nothing on it is a card, not a lane, so the day being looked at is told by whether today's lane is there.
    const onToday = page.locator(`main ul[data-day="${today}"]`);
    await expect(onToday).toHaveCount(1);
    await page.getByRole("button", { name: "Next day" }).click();
    await expect(onToday).toHaveCount(0);
    await page.getByRole("button", { name: "Today" }).click();
    await expect(onToday).toHaveCount(1);
    await page.locator("body").press("ArrowRight");
    await expect(onToday).toHaveCount(0);
    await page.locator("body").press("Shift+ArrowLeft");
    await expect(onToday).toHaveCount(0);
    await page.getByRole("button", { name: "Today" }).click();
    await expect(onToday).toHaveCount(1);
    await pick(page, "3");
    await expect(page.locator("main ul[data-day]")).toHaveCount(7);
    await page.getByRole("button", { name: "Next week" }).click();
    await expect(page.locator(`main ul[data-day="${today}"]`)).toHaveCount(0);
  });

  test("an entry opens its details beside the calendar, nothing is wider than the window, and Escape returns the cursor to the entry", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const entry = page.getByRole("button", { name: /Walk through the proofs/ });
    await entry.click();
    const pane = page.getByRole("complementary", { name: "Walk through the proofs" });
    await expect(pane).toBeVisible();
    const found = await measure(page);
    expect(found.page).toBeLessThanOrEqual(found.window);
    // With the details open the grid keeps room for each day's heading on one line (the pane covers its edge instead of squeezing it).
    const head = await page.locator("main [data-grid] h3").first().evaluate((el) => el.getBoundingClientRect().height);
    expect(head).toBeLessThanOrEqual(40);
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(entry).toBeFocused();
  });

  test("the now line crosses the day between the meetings it sits between, at the clock's own height, and the pane leaves the day's columns their width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const today = await seed(page);
    // The browser's clock is set to two hours before the 14:00 meeting, read with its own offset (the app tells time in the workspace's zone, not the browser's), so the line is at noon on every run; the other meeting is at 09:30.
    const page_ = (await (await page.request.get("api/schedule")).json()) as { days: Array<{ date: string; timed: Array<{ title: string; begins: string }> }> };
    const proofs = page_.days.find((d) => d.date === today)!.timed.find((e) => e.title === "Walk through the proofs")!;
    await page.clock.setFixedTime(new Date(new Date(proofs.begins).getTime() - 2 * 3600_000));
    await open(page);
    await pick(page, "1");
    const line = page.locator("main ul[data-day] > li[data-now]");
    await expect(line).toHaveCount(1);
    const measured = await page.evaluate(() => {
      const now = document.querySelector<HTMLElement>("main li[data-now]")!;
      const lane = now.parentElement!;
      const laneBox = lane.getBoundingClientRect();
      const nowBox = now.getBoundingClientRect();
      const boxes = Array.from(lane.querySelectorAll<HTMLElement>(":scope > li:not([data-now])")).map((li) => li.getBoundingClientRect());
      const hour = parseFloat(getComputedStyle(lane).getPropertyValue("--hour")) || 0;
      return { now: nowBox.top, laneTop: laneBox.top, boxes: boxes.map((b) => ({ top: b.top, bottom: b.bottom })), hour, lane: laneBox.width };
    });
    // No meeting is crossed: the line is below the 09:30 one and above the 14:00 one.
    const above = measured.boxes.filter((b) => b.bottom <= measured.now + 1);
    const below = measured.boxes.filter((b) => b.top >= measured.now - 1);
    expect(above.length).toBeGreaterThan(0);
    expect(below.length).toBeGreaterThan(0);
    expect(above.length + below.length).toBe(measured.boxes.length);
    // Opening an entry's details leaves each day's column as wide as it was.
    const before = await page.locator("main ul[data-day]").first().evaluate((el) => el.getBoundingClientRect().width);
    await page.getByRole("button", { name: /Walk through the proofs/ }).click();
    await expect(page.getByRole("complementary", { name: "Walk through the proofs" })).toBeVisible();
    const after = await page.locator("main ul[data-day]").first().evaluate((el) => el.getBoundingClientRect().width);
    expect(after).toBeGreaterThan(0);
    expect(Math.abs(after - before)).toBeLessThanOrEqual(1);
  });

  test("the entry's details start level with the chosen card and point at it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "3");
    const card = page.getByRole("button", { name: /Walk through the proofs/ }).first();
    await card.scrollIntoViewIfNeeded();
    await card.click();
    const pane = page.locator("[data-detail-pane][data-anchored]");
    await expect(pane).toBeVisible();
    const found = await page.evaluate(() => {
      const pane = document.querySelector<HTMLElement>("[data-detail-pane]")!;
      const card = document.querySelector<HTMLElement>("[data-entry-key][data-selected]")!;
      const p = pane.getBoundingClientRect();
      const c = card.getBoundingClientRect();
      const pointer = parseFloat(pane.style.getPropertyValue("--pointer-top")) || 0;
      return { paneTop: p.top, pointerY: p.top + pointer, cardTop: c.top, cardBottom: c.bottom };
    });
    // The pointer is level with the card it describes.
    expect(found.pointerY).toBeGreaterThanOrEqual(found.cardTop - 24);
    expect(found.pointerY).toBeLessThanOrEqual(found.cardBottom + 24);
  });

  test("the Add drawer at night is lighter than the page behind it and has an edge", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await page.getByRole("button", { name: "Add to schedule" }).first().click();
    const drawer = page.getByRole("dialog", { name: "Add a meeting" });
    await expect(drawer).toBeVisible();
    const found = await page.evaluate(() => {
      const luminance = (css: string) => {
        const [r, g, b] = (css.match(/[\d.]+/g) ?? ["0", "0", "0"]).slice(0, 3).map(Number);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const dialog = document.querySelector<HTMLElement>("[role=dialog]")!;
      // The surface is the nearest element from the dialog outward that is painted.
      let frame: HTMLElement = dialog;
      while (/rgba\(.*, 0\)|transparent/.test(getComputedStyle(frame).backgroundColor) && frame.parentElement) frame = frame.parentElement;
      return { drawer: luminance(getComputedStyle(frame).backgroundColor), page: luminance(getComputedStyle(document.body).backgroundColor), edge: getComputedStyle(frame).boxShadow };
    });
    expect(found.drawer).toBeGreaterThan(found.page + 10);
    expect(found.edge).not.toBe("none");
  });

  // S-0572: an entry's details are a card beside the entry clicked, never pinned to the right edge over other days. The entries are on
  // the first and the last day shown, ten weeks ahead where nothing else is, so the only entries the card could cover are the other one.
  const cardBesideEntry = async (page: Page, width: number) => {
    {
      await page.setViewportSize({ width, height: 900 });
      await seed(page);
      // A week with no timed meeting is the agenda's list of days, and one with a meeting the grid (S-0743): the days are read from either.
      const dayList = "main [data-grid] ul[data-day], main [data-agenda] li[data-day]";
      const ahead = async (list = dayList) => {
        await open(page);
        await pick(page, "3");
        for (let i = 0; i < 10; i++) {
          await page.locator("body").press("ArrowRight");
          await expect(page.locator("main [data-skeleton]")).toHaveCount(0, { timeout: 15_000 });
        }
        await expect(page.locator(list).first()).toBeVisible(LOADED);
      };
      await ahead();
      const days = await page.locator(dayList).evaluateAll((els) => els.map((el) => el.getAttribute("data-day") as string));
      expect(days.length).toBeGreaterThanOrEqual(5);
      const ends = [days[0], days[days.length - 1]];
      // At different times of day, so a card as wide as three days' columns (a 1024px window) has a place beside each that
      // covers neither: two entries level with each other across the week leave none.
      for (const [day, time] of [[ends[0], "09:00"], [ends[1], "15:00"]]) {
        const made = await page.request.post("api/calendar/meetings", { data: { what: `Meeting on ${day}`, day, time } });
        expect(made.ok()).toBe(true);
      }
      await page.reload();
      await ahead("main [data-grid] ul[data-day]");
      for (const day of ends) {
        const entry = page.getByRole("button", { name: new RegExp(`Meeting on ${day}`) });
        await entry.scrollIntoViewIfNeeded();
        await entry.click();
        const pane = page.locator("[data-detail-pane][data-anchored]");
        await expect(pane).toBeVisible();
        await settled(page, false);
        const found = await page.evaluate(() => {
          const rect = (el: Element) => {
            const r = el.getBoundingClientRect();
            return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
          };
          const card = rect(document.querySelector("[data-detail-pane]")!);
          const own = document.querySelector("[data-entry-key][data-selected]")!;
          const others = Array.from(document.querySelectorAll("main [data-entry-key]")).filter((el) => el !== own && !own.contains(el));
          const hit = others.filter((el) => {
            const o = rect(el);
            return Math.min(card.right, o.right) - Math.max(card.left, o.left) > 0 && Math.min(card.bottom, o.bottom) - Math.max(card.top, o.top) > 0;
          });
          const hits = hit.map((el) => ({ text: (el.textContent ?? "").slice(0, 60), ...rect(el) }));
          return { card, entry: rect(own), hit: hit.length, hits, window: { w: window.innerWidth, h: window.innerHeight }, page: document.documentElement.scrollWidth };
        });
        // Inside the window, beside the entry (to a side of it, level with some of its height), covering no other entry.
        expect(found.card.left).toBeGreaterThanOrEqual(0);
        expect(found.card.right).toBeLessThanOrEqual(found.window.w);
        expect(found.card.top).toBeGreaterThanOrEqual(0);
        expect(found.card.bottom).toBeLessThanOrEqual(found.window.h);
        expect(found.card.left >= found.entry.right - 1 || found.card.right <= found.entry.left + 1).toBe(true);
        expect(found.card.top).toBeLessThan(found.entry.bottom);
        expect(found.card.bottom).toBeGreaterThan(found.entry.top);
        expect(found.hit, `the card covers: ${JSON.stringify({ card: found.card, hits: found.hits })}`).toBe(0);
        expect(found.page).toBeLessThanOrEqual(found.window.w);
        // Escape puts the cursor back on the entry.
        await page.keyboard.press("Escape");
        await expect(pane).toHaveCount(0);
        await expect(entry).toBeFocused();
      }
    }
  };
  test("at 1440px an entry's details open as a card beside it, inside the window, covering no other entry (S-0572)", async ({ page }) => {
    await cardBesideEntry(page, 1440);
  });
  test("at 1024px an entry's details open as a card beside it, inside the window, covering no other entry (S-0572)", async ({ page }) => {
    await cardBesideEntry(page, 1024);
  });

  test("on a narrow window the details take the screen and Close returns", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const entry = page.getByRole("button", { name: /Walk through the proofs/ });
    await entry.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Walk through the proofs" })).toBeFocused();
    const box = await dialog.boundingBox();
    expect(box?.width ?? 0).toBeLessThanOrEqual(390);
    // A bottom sheet (S-0572): it is as wide as the window and rests on its bottom edge.
    const sheet = await page.locator("[data-overlay]").first().evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, bottom: r.bottom, window: window.innerWidth, height: window.innerHeight };
    });
    expect(sheet.left).toBeLessThanOrEqual(1);
    expect(sheet.right).toBeGreaterThanOrEqual(sheet.window - 1);
    expect(sheet.bottom).toBeGreaterThanOrEqual(sheet.height - 1);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(entry).toBeFocused();
  });

  test("at a wide window the calendars are one button on the views' row, so the toolbar is two rows and nothing is cut at the edge", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const views = await page.getByRole("tab", { name: "Day", exact: true }).boundingBox();
    const button = page.getByRole("button", { name: /^Calendars \(\d+\)/ });
    if ((await button.count()) > 0) {
      const box = await button.boundingBox();
      expect(Math.abs(box!.y - views!.y)).toBeLessThanOrEqual(12);
    }
    const found = await measure(page);
    expect(found.page).toBeLessThanOrEqual(found.window);
  });

  test("the day grid never cuts an entry: it has no scroll of its own, so the page scrolls when the hours do not fit, and a late entry shows whole", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 700 });
    const today = await seed(page);
    const late = await page.request.post("api/calendar/meetings", { data: { what: "Evening wrap-up", day: today, time: "18:00" } });
    expect(late.ok()).toBe(true);
    await open(page);
    await pick(page, "1");
    const frame = page.getByRole("region", { name: "Hours of the day" });
    const cut = await frame.evaluate((el) => {
      const grid = el.getBoundingClientRect();
      const buttons = Array.from(el.querySelectorAll<HTMLElement>("ul[data-day] button[data-entry-key]"));
      return {
        scrolls: el.scrollHeight > el.clientHeight + 1 || getComputedStyle(el).overflowY === "auto" || getComputedStyle(el).overflowY === "scroll",
        outside: buttons.filter((b) => b.getBoundingClientRect().bottom > grid.bottom + 1).length,
        entries: buttons.length,
      };
    });
    expect(cut.entries).toBeGreaterThan(0);
    expect(cut.scrolls).toBe(false);
    expect(cut.outside).toBe(0);
    await expect(page.getByRole("button", { name: /Evening wrap-up/ })).toBeVisible();
  });

  test("at 1024px a day's heading in the work week stays on one line, today's included", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "2");
    const heads = page.locator("main [data-grid] h3");
    await expect(heads).toHaveCount(WORK);
    const tall = await heads.evaluateAll((all) => all.map((h) => ({ high: h.getBoundingClientRect().height, line: parseFloat(getComputedStyle(h).lineHeight), cut: h.scrollWidth > h.clientWidth + 1 })));
    for (const h of tall) {
      expect(h.high).toBeLessThan(h.line * 2);
      expect(h.cut).toBe(false);
    }
  });

  test("the day grid opens on the clash or the day's first entry, not on empty hours", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const first = page.locator("main [data-grid] ul[data-day] li").first();
    if ((await first.count()) > 0) await expect(first).toBeInViewport();
    // Hour labels are short and sit clear of the card's edge.
    const label = await page.locator("main [data-grid] [data-hour]").nth(1).evaluate((el) => ({ text: el.textContent, right: el.parentElement!.getBoundingClientRect().right - el.getBoundingClientRect().right }));
    expect(label.text).not.toMatch(/:00/);
    expect(label.right).toBeGreaterThanOrEqual(8);
  });

  test("Show all hours draws the whole day in the same grid, and Show fewer hours goes back", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const hours = page.locator("main [data-grid] [data-hour]");
    // The day's answer may still be on its way (a placeholder stands in the grid's place): count the hours of the grid itself.
    await expect(hours.first()).toBeVisible();
    const some = await hours.count();
    await page.getByRole("button", { name: "Show all hours" }).click();
    await expect(hours).toHaveCount(24);
    // The grid grows to the hours; it does not scroll inside itself.
    expect(await page.getByRole("region", { name: "Hours of the day" }).evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
    const found = await measure(page);
    expect(found.page).toBeLessThanOrEqual(found.window);
    await page.getByRole("button", { name: "Show fewer hours" }).click();
    await expect(hours).toHaveCount(some);
  });

  test("the entry's Open button is a finger's height on a phone and the pane never runs wider than the window", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    await page.getByRole("button", { name: /Walk through the proofs/ }).click();
    const open_ = page.getByRole("dialog").getByRole("link", { name: "Open the event" });
    const box = await open_.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.width).toBeGreaterThan(200);
    const found = await measure(page);
    expect(found.page).toBeLessThanOrEqual(found.window);
  });

  test("an end before the start is the end field's own error, and a very long title in the form stays inside it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await page.getByRole("button", { name: "Add to schedule" }).first().click();
    const drawer = page.getByRole("dialog", { name: "Add a meeting" });
    await drawer.getByRole("textbox", { name: "What", exact: true }).fill(`${LONG} and then some more words that make the title longer than the field`);
    const start = drawer.getByRole("combobox", { name: /^Starts at/ });
    await start.fill("10:00");
    await start.press("Tab");
    const end = drawer.getByRole("combobox", { name: /^Ends at/ });
    await end.fill("9:00");
    await end.press("Tab");
    await expect(drawer.getByRole("alert").filter({ hasText: "It has to end after it starts." })).toBeVisible();
    await expect(end).toHaveAttribute("aria-invalid", "true");
    await expect(drawer.getByRole("button", { name: "Add", exact: true })).toBeDisabled();
    const found = await drawer.evaluate((el) => ({ box: el.scrollWidth, shown: el.clientWidth }));
    expect(found.box).toBeLessThanOrEqual(found.shown);
  });

  // A calendar that shows the wrong time is broken data: every timed entry the server sends for a day is drawn in Day, Work week and Week, at
  // its true start and for its true length (a pixel or two of tolerance), naming its own start, and the person can see it (nothing sits over it).
  test("every entry of the days shown is drawn at its true time, in the Day, Work week and Week views", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "2");
    const weekday = (await page.locator("main ul[data-day]").first().getAttribute("data-day")) as string;
    const today = ((await (await page.request.get("api/schedule")).json()) as { today: string }).today;
    // Four meetings that run into one another, and one before them, on a weekday of the week shown (and on today).
    for (const day of new Set([weekday, today])) {
      for (const [what, time, until] of [
        ["Guard opening", "08:00", "08:45"],
        ["Guard supplier call", "16:10", "17:10"],
        ["Guard fitting", "16:40", "17:40"],
        ["Guard venue walk", "16:10", "17:40"],
        ["Guard budget check", "17:00", "17:30"],
      ] as const) {
        const made = await page.request.post("api/calendar/meetings", { data: { what, day, time, until } });
        expect(made.ok()).toBe(true);
      }
    }
    for (const [key, name] of [
      ["1", "Day"],
      ["2", "Work week"],
      ["3", "Week"],
    ] as const) {
      await open(page);
      await pick(page, key);
      await expect(page.locator("main [data-grid] ul[data-day]").first()).toBeVisible();
      await settled(page, key !== "1");
      const dates = await page.locator("main ul[data-day]").evaluateAll((els) => els.map((e) => e.getAttribute("data-day") as string));
      const first = dates[0];
      const read = (await (await page.request.get(`api/schedule?from=${first}&days=${dates.length}`)).json()) as { days: { date: string; timed: { title: string; begins: string; ends?: string }[] }[] };
      const found = await page.evaluate(
        ({ days }) => {
          const minutes = (iso: string) => Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16));
          // The clock is the person's: 12 hours with AM or PM, or 24 hours. Either names the start.
          const pad = (n: number) => String(n).padStart(2, "0");
          const when = (m: number) => [`${((Math.floor(m / 60) + 11) % 12) + 1}:${pad(m % 60)} ${m >= 720 ? "PM" : "AM"}`, `${pad(Math.floor(m / 60))}:${pad(m % 60)}`];
          const hourLabels = Array.from(document.querySelectorAll<HTMLElement>("main [data-grid] [data-hour]"));
          const firstLabel = (hourLabels[0].textContent ?? "").trim();
          const m = /^(\d{1,2})(?::\d\d)? ?(AM|PM)?$/.exec(firstLabel.replace(/\s/g, " "));
          const from = m ? (m[2] ? (Number(m[1]) % 12) + (m[2] === "PM" ? 12 : 0) : Number(m[1])) * 60 : NaN;
          const problems: string[] = [];
          let checked = 0;
          // Inside a group card each row is whole (its box in the card's, its title not clipped) or not drawn and counted in the "+N more".
          for (const card of document.querySelectorAll<HTMLElement>("main [data-group-card]")) {
            const cardBox = card.getBoundingClientRect();
            const rows = Array.from(card.querySelector("ul")?.children ?? []) as HTMLElement[];
            for (const row of rows.filter((r) => !r.hidden)) {
              const r = row.getBoundingClientRect();
              if (r.top < cardBox.top - 1 || r.bottom > cardBox.bottom + 1) problems.push(`${(row.textContent ?? "").slice(0, 30)}: a row partly outside its card`);
              const name = row.querySelector<HTMLElement>("[class*='name']");
              if (name && name.scrollHeight > name.clientHeight + 1) problems.push(`${(row.textContent ?? "").slice(0, 30)}: its title is clipped in the card`);
            }
            const counted = Number(/\d+/.exec(card.querySelector("[data-group-more]")?.textContent ?? "")?.[0] ?? 0);
            if (counted !== rows.filter((r) => r.hidden).length) problems.push(`a card counts ${counted} more but leaves out ${rows.filter((r) => r.hidden).length}`);
          }
          // As the frame opens, no block is cut across the line under the headings and the all-day strip, with its title out of sight.
          const under = (document.querySelector<HTMLElement>("main [data-strip]") ?? document.querySelector<HTMLElement>("main [data-grid] h3"))!.getBoundingClientRect().bottom;
          for (const b of document.querySelectorAll<HTMLElement>("main ul[data-day] [data-entry-key]")) {
            const r = b.getBoundingClientRect();
            if (r.top < under - 1 && r.bottom > under + 1) problems.push(`${(b.textContent ?? "").slice(0, 30)}: cut across the headings at open`);
          }
          for (const d of days) {
            const lane = document.querySelector<HTMLElement>(`main ul[data-day="${d.date}"]`);
            if (!lane) {
              problems.push(`${d.date}: no lane`);
              continue;
            }
            const hourPxNow = () => hourLabels.length > 2 ? hourLabels[2].getBoundingClientRect().top - hourLabels[1].getBoundingClientRect().top : lane.getBoundingClientRect().height / hourLabels.length;
            const buttons = Array.from(lane.querySelectorAll<HTMLElement>("[data-entry-key]"));
            // No block or card is over another: the boxes of a lane's entries (and cards) never share more than a couple of pixels.
            const boxes = Array.from(lane.querySelectorAll<HTMLElement>(":scope > li:not([data-now])")).map((li) => ({ li, r: li.getBoundingClientRect() }));
            boxes.forEach((a, i) =>
              boxes.slice(i + 1).forEach((b) => {
                const across = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
                const down = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
                if (across > 2 && down > 2) problems.push(`${d.date}: "${(a.li.textContent ?? "").slice(0, 24)}" and "${(b.li.textContent ?? "").slice(0, 24)}" overlap by ${Math.round(down)} px`);
              }),
            );
            for (const e of d.timed) {
              checked += 1;
              // Placed again for each entry: the check below scrolls the frame.
              const laneBox = lane.getBoundingClientRect();
              const hourPx = hourPxNow();
              const start = minutes(e.begins);
              const end = e.ends ? minutes(e.ends) : start + 30;
              const text = (el: HTMLElement) => `${el.textContent} ${el.getAttribute("title") ?? ""}`.replace(/\s/g, " ");
              const candidates = buttons.filter((b) => text(b).includes(e.title) && when(start).some((w) => text(b).includes(w)));
              if (candidates.length === 0) {
                problems.push(`${d.date} ${e.title} ${when(start)[0]}: not drawn, or it names another time`);
                continue;
              }
              const card = (b: HTMLElement) => !!b.closest("li[data-clash]:not([data-side])");
              const exact = candidates.some((b) => {
                if (card(b)) return true;
                const r = b.getBoundingClientRect();
                const top = laneBox.top + ((start - from) / 60) * hourPx;
                const height = Math.max(32, ((Math.max(end, start + 30) - start) / 60) * hourPx);
                return Math.abs(r.top - top) <= 3 && Math.abs(r.height - height) <= 3;
              });
              if (!exact) {
                const r = candidates[0].getBoundingClientRect();
                problems.push(`${d.date} ${e.title} ${when(start)[0]}: not at its start and length (top ${Math.round(r.top - laneBox.top)} want ${Math.round(((start - from) / 60) * hourPx)}, height ${Math.round(r.height)} want ${Math.round(((end - start) / 60) * hourPx)})`);
              }
              // One counted in a card's "+N more" is not drawn; the card says so, and the list has it.
              if (candidates.every((b) => b.closest("li[hidden]"))) continue;
              // Seen: scrolled to the middle of the frame, the point at its middle belongs to it.
              const target = candidates[0];
              target.scrollIntoView({ block: "center" });
              const r = target.getBoundingClientRect();
              const hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(r.height / 2, 14));
              if (!hit || !target.closest("li")?.contains(hit)) problems.push(`${d.date} ${e.title}: something is over it`);
              // And its start time, at its top left, is not under another block.
              const corner = document.elementFromPoint(r.left + 6, r.top + 6);
              if (!corner || !target.closest("li")?.contains(corner)) problems.push(`${d.date} ${e.title}: its start is under something`);
            }
          }
          return { problems, checked };
        },
        { days: read.days },
      );
      expect(found.checked, `${name}: entries read from the server`).toBeGreaterThanOrEqual(5);
      expect(found.problems, name).toEqual([]);
    }
  });

  // Day view at the full width of the content, with no gutter beside it; the empty day is the shared card, centred in the content and capped
  // at 32rem, and neither moves the toolbar.
  test("the Day grid spans the content width, an empty day keeps its place with no notice over it, and the toolbar does not move between them", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "1");
    const content = async () => page.evaluate(() => {
      const edge = document.querySelector<HTMLElement>("main section")!.getBoundingClientRect();
      const tabs = document.querySelector<HTMLElement>("main [role=tablist]")!.getBoundingClientRect();
      return { left: edge.left, right: edge.right, tabsTop: tabs.top };
    });
    const full = await content();
    const grid = (await page.locator("main [data-grid]").boundingBox())!;
    expect(grid.x).toBeLessThanOrEqual(full.left + 2);
    expect(grid.x + grid.width).toBeGreaterThanOrEqual(full.right - 2);
    await page.getByRole("button", { name: "Next day" }).click();
    // A day with nothing on it is the same grid, with no notice over it, and the page keeps its shape (S-0525).
    await expect(page.locator("main [data-schedule-empty]")).toHaveCount(0);
    await expect(page.locator("main [data-grid]")).toBeVisible();
    await expect(page.getByText(/^Nothing on this day/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Look at / })).toHaveCount(0);
    const after = (await page.locator("main [data-grid]").boundingBox())!;
    expect(Math.abs(after.x - grid.x)).toBeLessThanOrEqual(2);
    expect(Math.abs(after.width - grid.width)).toBeLessThanOrEqual(2);
    expect((await content()).tabsTop).toBeCloseTo(full.tabsTop, 0);
  });

  // Back-to-back meetings keep a 1 px gap between their boxes, and each is still drawn at its own start.
  test("meetings that follow one another are 1 px apart, each at its own start", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    const today = ((await (await page.request.get("api/schedule")).json()) as { today: string }).today;
    for (const [what, time, until] of [
      ["Gap first", "11:00", "11:30"],
      ["Gap second", "11:30", "12:00"],
    ] as const) {
      expect((await page.request.post("api/calendar/meetings", { data: { what, day: today, time, until } })).ok()).toBe(true);
    }
    await open(page);
    await pick(page, "1");
    const first = page.locator("main ul[data-day] [data-entry-key]", { hasText: "Gap first" }).first();
    const second = page.locator("main ul[data-day] [data-entry-key]", { hasText: "Gap second" }).first();
    await first.scrollIntoViewIfNeeded();
    const a = (await first.boundingBox())!;
    const b = (await second.boundingBox())!;
    const gap = b.y - (a.y + a.height);
    expect(gap).toBeGreaterThanOrEqual(0.9);
    expect(gap).toBeLessThanOrEqual(2);
    // The second starts half an hour after the first: the gap is taken from the first's end, not added to its start.
    const hour = await page.evaluate(() => document.querySelector<HTMLElement>("main ul[data-day]")!.getBoundingClientRect().height / document.querySelectorAll("main [data-grid] [data-hour]").length);
    expect(Math.abs(b.y - a.y - hour / 2), JSON.stringify({ a, b, hour })).toBeLessThanOrEqual(2);
  });

  // The month: every title is shown whole, a week with nothing in it is no taller than a day needs, and the cells of a week are one height.
  test("the Month shows each title whole, and an empty week is not a tall void", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seed(page);
    await open(page);
    await pick(page, "4");
    const found = await page.evaluate(() => {
      const cells = Array.from(document.querySelectorAll<HTMLElement>("main [data-month] section[data-day]"));
      const cut = Array.from(document.querySelectorAll<HTMLElement>("main [data-month] ul > li [class*='name']")).filter((n) => n.scrollHeight > n.clientHeight + 1).map((n) => n.textContent);
      const rows = new Map<number, { height: number; entries: number }[]>();
      for (const cell of cells) {
        const top = Math.round(cell.getBoundingClientRect().top);
        rows.set(top, [...(rows.get(top) ?? []), { height: Math.round(cell.getBoundingClientRect().height), entries: cell.querySelectorAll("ul > li").length }]);
      }
      const weeks = Array.from(rows.values());
      return {
        cut,
        uneven: weeks.filter((w) => new Set(w.map((c) => c.height)).size > 1).length,
        voids: weeks.filter((w) => w.every((c) => c.entries === 0)).map((w) => w[0].height),
        unit: parseFloat(getComputedStyle(document.documentElement).fontSize),
      };
    });
    expect(found.cut).toEqual([]);
    expect(found.uneven).toBe(0);
    for (const height of found.voids) expect(height).toBeLessThanOrEqual(6.5 * found.unit + 2);
  });
});
