// The Schedule as the UI/UX review of the fb08fa7a build used it (batch R1): each test follows the reviewer's own steps through the
// screen they named, at their width, and reads what the person sees (never the data), with every other place that shows the same
// thing beside it. Layout is measured here in a browser: a Vitest file cannot see widths, clipping or overflow.
//
// It has a server of its own (a fresh demo, so no clash the other scenarios add is counted) and runs in order: the first test counts
// clashes before the later ones add more, and each later test uses hours of its own on the same day.
import { expect, type Page } from "@playwright/test";
import { followServer, test } from "./test";
import { openScreen, screenReady } from "./open-screen";

const LOAD = { timeout: 15_000 };

/** The first weekday after today (a weekday, so the Work week shows it), as 2026-11-11. */
async function aWeekday(page: Page): Promise<string> {
  await page.goto("?token=e2e-token");
  const today = ((await (await page.request.get("api/schedule")).json()) as { today: string }).today;
  const at = new Date(`${today}T12:00:00Z`);
  do at.setUTCDate(at.getUTCDate() + 1);
  while ([0, 6].includes(at.getUTCDay()));
  return at.toISOString().slice(0, 10);
}

async function add(page: Page, what: string, day: string, time: string, until: string, extra: Record<string, string> = {}) {
  const made = await page.request.post("api/calendar/meetings", { data: { what, day, time, until, ...extra } });
  expect(made.ok()).toBe(true);
}

/** The Schedule in a view (1 Day, 2 Work week, 3 Week, 4 Month, 5 Timeline) on the week of `day`. */
async function openView(page: Page, key: "1" | "2" | "3" | "4" | "5", day: string) {
  await page.goto("?token=e2e-token");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOAD);
  await page.evaluate(() => {
    window.location.hash = "schedule";
  });
  await screenReady(page);
  await expect(page.getByRole("main").getByRole("heading", { level: 1, name: "Schedule" })).toBeVisible();
  await expect(page.locator("main [data-skeleton]")).toHaveCount(0, LOAD);
  await page.locator("body").press(key);
  const here = key === "5" ? "main [data-timeline]" : key === "4" ? "main [data-month]" : "main [data-grid]";
  // A week with nothing in it (the current one, on a day off) shows the list, not the grid: the grid is waited for on the week of the day.
  if (key === "4" || key === "5") await expect(page.locator(here).first()).toBeVisible(LOAD);
  // Forward by the view's unit until the day is on the screen (Day shows one day: go by day).
  for (let n = 0; n < 40 && key !== "5" && (await page.locator(`main [data-day="${day}"]`).count()) === 0; n += 1) {
    await page.locator("body").press("ArrowRight");
    await expect(page.locator("main [data-skeleton]")).toHaveCount(0, LOAD);
  }
  if (key !== "5") await expect(page.locator(`main [data-day="${day}"]`).first()).toBeAttached(LOAD);
  if (key === "1" || key === "2" || key === "3") await expect(page.locator("main [data-grid]")).toBeVisible(LOAD);
}

/** What the clashes on a day look like on the screen: each clash's drawing, the width of its day's column, and what its meetings say. */
async function clashes(page: Page, day: string) {
  return page.evaluate((date) => {
    const lane = document.querySelector<HTMLElement>(`main ul[data-day="${date}"]`);
    if (!lane) return null;
    const laneBox = lane.getBoundingClientRect();
    return {
      column: Math.round(laneBox.width),
      clashes: Array.from(lane.querySelectorAll<HTMLElement>(":scope > li[data-clash]")).map((li) => {
        const box = li.getBoundingClientRect();
        const card = li.querySelector<HTMLElement>("[data-group-card]");
        const cardBox = card?.getBoundingClientRect();
        const members = Array.from(li.querySelectorAll<HTMLElement>("li[class*='clashMember']"));
        // A title shows whole when its own box holds all of its text (no word cut off at the box's edge, none past its bottom).
        const whole = (el: HTMLElement | null) => !!el && el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1;
        const allRows = Array.from(li.querySelectorAll<HTMLElement>("[data-group-card] ul > li"));
        // A row the card has no room for is not drawn; it is counted in the card's "+N more", which opens the list of all of them.
        const rows = allRows.filter((r) => !r.hidden);
        return {
          side: li.hasAttribute("data-side"),
          label: li.querySelector('[role="group"]')?.getAttribute("aria-label") ?? "",
          text: (li.textContent ?? "").replace(/\s+/g, " "),
          top: box.top,
          height: box.height,
          cardHeight: cardBox?.height ?? 0,
          cardBottom: cardBox?.bottom ?? 0,
          cardTop: cardBox?.top ?? 0,
          cardInside: !!cardBox && cardBox.left >= laneBox.left - 1 && cardBox.right <= laneBox.right + 1,
          // The heading as drawn: its whole sentence, or the short one when the card has no room for a meeting under the whole one.
          head: (card?.querySelector("p > span:not([hidden])")?.textContent ?? "").replace(/\s+/g, " ").trim(),
          hiddenRows: allRows.length - rows.length,
          rows: rows.map((r) => {
            const rb = r.getBoundingClientRect();
            const name = r.querySelector<HTMLElement>("[class*='name']");
            return { text: (r.textContent ?? "").replace(/\s+/g, " ").trim(), top: rb.top, bottom: rb.bottom, whole: whole(name), perLine: rb.height < 80 };
          }),
          moreButtons: Array.from(li.querySelectorAll<HTMLElement>("[data-group-more]")).map((b) => {
            const bb = b.getBoundingClientRect();
            return { inside: !!cardBox && bb.top >= cardBox.top - 1 && bb.bottom <= cardBox.bottom + 1 };
          }),
          members: members.map((m) => {
            const mb = m.getBoundingClientRect();
            const name = m.querySelector<HTMLElement>("[class*='name']");
            // The place under the time wraps by words in a lane; it is never cut sideways ("Ro...").
            const place = m.querySelector<HTMLElement>("[class*='linePlace']");
            return { left: mb.left, right: mb.right, top: mb.top, height: mb.height, whole: whole(name), placeWhole: !place || place.scrollWidth <= place.clientWidth + 1, text: (m.textContent ?? "").replace(/\s+/g, " ").trim() };
          }),
          tag: (li.querySelector("[data-clash-tag]")?.textContent ?? "").trim(),
          lane: { left: laneBox.left, right: laneBox.right },
        };
      }),
    };
  }, day);
}

/** A move form's four boxes as the person sees them: a day and a time for the start, a day and a time for the end. */
function moveBoxes(form: ReturnType<Page["locator"]>) {
  const times = form.getByRole("combobox", { name: "Time of day" });
  return { startDay: form.getByRole("textbox", { name: "Starts" }), startTime: times.nth(0), endDay: form.getByRole("textbox", { name: "Ends" }), endTime: times.nth(1) };
}
/** What the person sees in a day's column: every box drawn (a card, a lane of a side-by-side clash or an ordinary meeting), which of them
 * overlap, which time labels are cut or outside their box, and the block holding `titles` when they are one. */
async function drawnIn(page: Page, date: string, titles: string[] = []) {
  return page.evaluate(
    ({ date, titles }) => {
      const lane = document.querySelector<HTMLElement>(`main ul[data-day="${date}"]`)!;
      const column = lane.getBoundingClientRect().width;
      const rect = (el: Element) => {
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
      };
      // Every box the person sees in the day's column: a card, a lane of a side-by-side clash, or an ordinary meeting.
      const drawn: Array<{ name: string; box: ReturnType<typeof rect>; labels: Array<{ whole: boolean; inside: boolean }>; clipped: boolean; why: string }> = [];
      for (const li of Array.from(lane.querySelectorAll<HTMLElement>(":scope > li:not([data-now])"))) {
        const parts = li.querySelector("[data-group-card]") ? [li.querySelector<HTMLElement>("[data-group-card]")!] : Array.from(li.querySelectorAll<HTMLElement>("li[class*='clashMember']"));
        for (const part of parts.length > 0 ? parts : [li.querySelector<HTMLElement>("button") ?? li]) {
          const box = rect(part);
          // The time of a meeting is whole when the line that holds it shows all of it (the place after it may be cut to an ellipsis, and
          // shows whole on hover); a card's start time stands alone in its own box.
          // A row the card leaves out (counted in its "+N more") is not drawn, so it has no label to be whole.
          const labels = Array.from(part.querySelectorAll<HTMLElement>("[data-entry-line], [class*='when']")).filter((el) => !el.closest("[hidden]")).map((el) => {
            const r = rect(el);
            let whole = el.scrollWidth <= el.clientWidth + 1;
            const clock = el.querySelector<HTMLElement>("[data-entry-time]");
            if (el.hasAttribute("data-entry-line") && clock) whole = clock.scrollWidth <= clock.clientWidth + 1 && rect(clock).right <= r.right + 1;
            return { whole, inside: r.left >= box.left - 1 && r.right <= box.right + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1 };
          });
          // A meeting's box holds its title and its time whole: nothing of either is cut by the box's edge (a lane's title may end in an
          // ellipsis after two lines, which is its own rule, so the line count is what is checked, not the clamp).
          const cut = Array.from(part.querySelectorAll<HTMLElement>("button[data-entry-key]:not([class*='clashRow'])")).filter((b) => b.scrollHeight > b.clientHeight + 1);
          const clipped = cut.length > 0;
          const why = cut.map((b) => `scroll ${b.scrollHeight} > client ${b.clientHeight}, box ${Math.round(box.bottom - box.top)}px, short ${b.hasAttribute("data-short")}`).join("; ");
          drawn.push({ name: (part.textContent ?? "").replace(/\s+/g, " ").trim(), box, labels, clipped, why });
        }
      }
      const overlaps: string[] = [];
      for (const [i, a] of drawn.entries())
        for (const b of drawn.slice(i + 1)) {
          const across = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
          const down = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
          if (across > 1 && down > 1) overlaps.push(`"${a.name.slice(0, 40)}" over "${b.name.slice(0, 40)}" by ${Math.round(across)}x${Math.round(down)}px`);
        }
      const block = Array.from(lane.querySelectorAll<HTMLElement>(":scope > li[data-clash]")).find((li) => titles.every((t) => (li.textContent ?? "").includes(t)));
      return {
        column,
        overlaps,
        unwhole: drawn.flatMap((d) => (d.clipped || d.labels.some((l) => !l.whole || !l.inside) ? [`${d.name.slice(0, 40)} (${d.clipped ? `title or time cut by the box: ${d.why}` : "a time label not whole or outside the box"})`] : [])),
        block: block ? { side: block.hasAttribute("data-side"), lanes: block.querySelectorAll("li[class*='clashMember']").length, card: !!block.querySelector("[data-group-card]") } : null,
        ordinaryTitles: Array.from(lane.querySelectorAll<HTMLElement>(":scope > li:not([data-clash]):not([data-overlap]):not([data-now]) button")).map((b) => b.textContent ?? ""),
      };
    },
    { date, titles },
  );
}

/** The same time of day as the box may write it: 24 hours ("20:15") or 12 hours ("8:15 PM"). */
const clock = (h: number, m: number) => new RegExp(`^(${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}|${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")}\\s?${h >= 12 ? "PM" : "AM"})$`, "i");
const countOf = (text: string | null) => Number(/(\d+)/.exec(text ?? "")?.[1] ?? NaN);

test.describe("the Schedule, as the review used it", () => {
  test.describe.configure({ mode: "serial" });
  let day = "";
  // A later weekday, for the tests that need a day of their own.
  let later = "";

  test.beforeAll(async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL });
    await followServer(context, baseURL);
    const page = await context.newPage();
    day = await aWeekday(page);
    const at = new Date(`${day}T12:00:00Z`);
    do at.setUTCDate(at.getUTCDate() + 1);
    while ([0, 6].includes(at.getUTCDay()));
    later = at.toISOString().slice(0, 10);
    await page.close();
  });

  test("S-0343: four meetings that overlap are one clash on Today, the Schedule, the Timeline and the menu's count", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("?token=e2e-token");
    const badge = async () => {
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOAD);
      const text = await page.locator('nav a[href$="#today"], nav a[href="#today"]').first().innerText();
      return countOf(text.replace(/^Today/i, ""));
    };
    // The count appears once Today has been read.
    await expect.poll(badge, LOAD).not.toBeNaN();
    const before = await badge();
    const lineKeys = async () => ((await (await page.request.get("api/today/queue")).json()) as { key: string }[]).map((l) => l.key);
    const keysBefore = await lineKeys();
    // The reviewer's four: one meeting runs into three others, two of which overlap each other (four pairs, one group).
    for (const [what, from, to] of [
      ["Venue walk-through", "09:00", "10:30"],
      ["Catering call", "09:30", "10:00"],
      ["Budget check", "09:45", "10:15"],
      ["Supplier call", "10:15", "11:00"],
    ]) await add(page, what, day, from, to);
    // Today: one clash line, and no fold that counts the other pairs.
    await page.goto("?token=e2e-token");
    await expect(page.locator('[data-queue-line="clash"]')).toHaveCount(1, LOAD);
    await expect.soft(page.locator('[data-queue-line="clash"]')).toContainText(/^4 meetings overlap · \w{3} /);
    await expect.soft(page.locator("[data-clashes-fold]")).toHaveCount(0);
    // Opened, the one line lists every meeting of the group, not only the first two.
    await page.locator('[data-queue-line="clash"]').click();
    for (const title of ["Venue walk-through", "Catering call", "Budget check", "Supplier call"]) await expect.soft(page.getByRole("group", { name: title, exact: true })).toBeVisible(LOAD);
    // The menu's count rose by the lines that are new, one of them the clash, not by the four pairs. (Adding meetings can also
    // make another line due, such as the standing rules' review after the runs they set off; it is counted as the line it is.)
    const added = (await lineKeys()).filter((k) => !keysBefore.includes(k));
    expect.soft(added.filter((k) => k.startsWith("clash:"))).toHaveLength(1);
    await expect.configure({ soft: true }).poll(badge, LOAD).toBe(before + added.length);

    // The Schedule: "1 clash", in every view of the week, and the same on the Timeline.
    for (const key of ["1", "2", "3"] as const) {
      await openView(page, key, day);
      await expect.soft(page.locator("[data-clash-count]")).toContainText("1 clash", LOAD);
    }
    await openView(page, "5", day);
    await expect.soft(page.locator("[data-timeline-clashes]")).toContainText("1 clash: 4 meetings overlap", LOAD);
    // Month shows the clash as a mark on its day, one mark.
    await openView(page, "4", day);
    await expect.soft(page.locator(`main [data-day="${day}"] [data-clash-mark]`)).toHaveCount(1);
    // The data beside the screens: the engine names the four pairs as one line.
    const queue = (await (await page.request.get("api/today/queue")).json()) as Array<{ kind: string }>;
    expect.soft(queue.filter((l) => l.kind === "clash")).toHaveLength(1);
  });

  test("S-0338: at the Weekdays width two clashing meetings stand side by side at their own times, each title whole", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await add(page, "Roof inspection", day, "13:00", "14:00");
    await add(page, "Tile delivery", day, "13:30", "14:30");
    await openView(page, "2", day);
    const found = await clashes(page, day);
    const mine = found?.clashes.find((c) => c.text.includes("Roof inspection"));
    expect(found?.column, "the reviewer's column was 218px").toBeGreaterThanOrEqual(170);
    expect(found!.column / 2, "two lanes of at least 85px").toBeGreaterThanOrEqual(85);
    expect(mine, "the clash is drawn").toBeTruthy();
    expect(mine!.side, "side by side wherever each lane gets at least 85px").toBe(true);
    // Each meeting at its own start and end (an hour is 72px), in its own lane, inside the column.
    expect(mine!.members).toHaveLength(2);
    const [first, second] = mine!.members;
    expect(Math.round(first.height)).toBeGreaterThanOrEqual(70);
    expect(Math.round(second.top - first.top)).toBeGreaterThanOrEqual(34);
    expect(Math.round(second.top - first.top)).toBeLessThanOrEqual(38);
    expect(first.right).toBeLessThanOrEqual(second.left + 1);
    expect(first.left).toBeGreaterThanOrEqual(mine!.lane.left - 1);
    expect(second.right).toBeLessThanOrEqual(mine!.lane.right + 1);
    // Both titles can be read, and the clash is named in words and an icon.
    expect(first.whole && second.whole, `titles whole: ${first.text} | ${second.text}`).toBe(true);
    expect(first.placeWhole && second.placeWhole, `places whole: ${first.text} | ${second.text}`).toBe(true);
    expect(mine!.tag).toBe("Clash");
  });

  test("S-0338: a clash in a narrow column is one card, each title whole on its own line, and its controls never cut by its edge", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // The reviewer's weekday clash: back-to-back meetings in different places, with too little time to travel between them.
    await add(page, "Dentist visit", day, "15:00", "15:30", { where: "Harbor Road" });
    await add(page, "School pickup", day, "15:30", "16:00", { where: "Oak Street" });
    await add(page, "Library return", day, "16:00", "16:30", { where: "Mill Lane" });
    // Week at 1440 has columns of about 156px: two lanes would be 78px, under 85px, so the pair of the last test is one card there.
    await openView(page, "3", day);
    const found = await clashes(page, day);
    expect(found!.column / 2, "two lanes would each get under 85px").toBeLessThan(85);
    for (const c of found!.clashes.filter((x) => /Roof inspection|Dentist visit/.test(x.text))) {
      expect(c.side).toBe(false);
      // The reason is on the card in words, not only in a tooltip.
      expect(c.head, "the card names its reason in words").toMatch(c.text.includes("Dentist") ? /^Clash · \d+ min short( to get there)?$/ : /^Clash · (\d+ at once(, they overlap by \d+ min)?|they overlap by \d+ min|\d+ min overlap)$/);
      const titles = ["Roof inspection", "Tile delivery", "Dentist visit", "School pickup", "Library return"].filter((n) => c.text.includes(n));
      for (const title of titles) expect(c.rows.filter((r) => r.text.includes(title)).length, `${title} has no more than a row of its own`).toBeLessThanOrEqual(1);
      expect(c.rows.length + c.hiddenRows, "every meeting is a row or counted in +N more").toBe(titles.length);
      expect(c.moreButtons.length, "+N more is there when rows are left out").toBe(c.hiddenRows > 0 ? 1 : 0);
      for (const r of c.rows) {
        expect(r.whole, `${r.text}: its title is whole`).toBe(true);
        expect(r.top, `${r.text}: inside the card`).toBeGreaterThanOrEqual(c.cardTop - 1);
        expect(r.bottom, `${r.text}: inside the card`).toBeLessThanOrEqual(c.cardBottom + 1);
      }
      // Every row on a line of its own, one under the other.
      for (let n = 1; n < c.rows.length; n += 1) expect(c.rows[n].top).toBeGreaterThanOrEqual(c.rows[n - 1].bottom - 1);
      for (const m of c.moreButtons) expect(m.inside, "a +N more control is whole inside its card").toBe(true);
      expect(c.cardInside).toBe(true);
      // It covers the clash's real time span: at least from the first start to the last end (an hour is 72px).
      expect(c.cardHeight).toBeGreaterThanOrEqual(c.text.includes("Dentist") ? 36 * 3 - 2 : 72 + 36 - 2);
    }
  });

  test("S-0338: a three-meeting clash is the card at the Weekdays width (lanes of about 73px), naming its reason and every title whole", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await add(page, "Garden visit", day, "11:30", "12:30");
    await add(page, "Boiler service", day, "11:45", "12:15");
    await add(page, "Paint pickup", day, "12:00", "13:00");
    await openView(page, "2", day);
    const found = await clashes(page, day);
    const three = found!.clashes.find((c) => c.text.includes("Garden visit"))!;
    expect(found!.column / 3, "three lanes would each get under 85px").toBeLessThan(85);
    expect(three.side, "one card, not three narrow lanes").toBe(false);
    expect(three.head).toMatch(/^Clash · 3 at once(, they overlap by \d+ min)?$/);
    // Every meeting is a row, in order, or counted in the card's "+N more" (the card takes only the room nothing else has).
    expect(three.rows.length + three.hiddenRows).toBe(3);
    expect(three.rows[0].text).toContain("Garden visit");
    expect(three.rows.every((r) => r.whole && r.perLine)).toBe(true);
    expect(three.cardInside).toBe(true);
    // Each title opens its own meeting.
    const lane = page.locator(`main ul[data-day="${day}"]`);
    // A meeting the card has no room to draw is in its "+N more", which lists every one of them.
    if (three.hiddenRows > 0) await lane.locator("li[data-clash]", { hasText: "Garden visit" }).locator("[data-group-more]").click();
    await page.getByRole("button", { name: /Boiler service/ }).first().click();
    await expect(page.getByRole("button", { name: /More actions for Boiler service/ })).toBeVisible(LOAD);
  });

  test("S-0338: side by side a long title takes two lines then an ellipsis, shows whole on hover and on focus, and no control is clipped", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const long = "Quarterly supplier contract renewal and pricing review with finance";
    await add(page, long, day, "19:00", "20:30");
    await add(page, "Stock count", day, "19:30", "20:30");
    // A one-hour pair whose second title wraps to two lines beside a time and a place: the title and the line under it never overlap.
    await add(page, "Supplier call", day, "05:00", "06:00", { where: "Room 1" });
    await add(page, "Fitting appointment", day, "05:30", "06:30", { where: "Room 1" });
    await openView(page, "2", day);
    const member = page.locator(`main ul[data-day="${day}"] li[data-clash][data-side] li[class*='clashMember']`).filter({ hasText: "Quarterly supplier" });
    await expect(member).toBeVisible(LOAD);
    const measured = await member.evaluate((li) => {
      const name = li.querySelector<HTMLElement>("[class*='name']")!;
      const style = getComputedStyle(name);
      const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
      const box = li.getBoundingClientRect();
      const button = li.querySelector("button")!.getBoundingClientRect();
      const line = li.querySelector<HTMLElement>("[data-entry-line]");
      const text = document.createRange();
      text.selectNodeContents(name);
      const lastLine = Array.from(text.getClientRects()).reduce((low, r) => Math.max(low, r.bottom), 0);
      return { overlap: line ? Math.max(0, Math.max(name.getBoundingClientRect().bottom, Math.min(lastLine, name.getBoundingClientRect().bottom + 1)) - line.getBoundingClientRect().top) : 0, nameBox: name.getBoundingClientRect().height, lineHeight, lines: Math.round(name.clientHeight / lineHeight), cut: name.scrollHeight > name.clientHeight + 1, ellipsis: style.textOverflow, clamp: style.webkitLineClamp, insideBox: button.left >= box.left - 1 && button.right <= box.right + 1 && button.top >= box.top - 1 && button.bottom <= box.bottom + 1 };
    });
    const crowded = await page.evaluate((date) =>
      Array.from(document.querySelectorAll<HTMLElement>(`main ul[data-day="${date}"] li[data-side] li[class*='clashMember']`)).map((li) => {
        const name = li.querySelector<HTMLElement>("[class*='name']")!;
        const line = li.querySelector<HTMLElement>("[data-entry-line]");
        const range = document.createRange();
        range.selectNodeContents(name);
        const textBottom = Math.min(name.getBoundingClientRect().bottom, Array.from(range.getClientRects()).reduce((low, r) => Math.max(low, r.bottom), 0));
        return { title: name.textContent, over: line ? textBottom - line.getBoundingClientRect().top : 0 };
      }),
    day);
    for (const c of crowded) expect(c.over, `${c.title}: the time line starts under the title`).toBeLessThanOrEqual(1);
    expect(measured.overlap, `the time line starts under the title (name ${measured.nameBox}px)`).toBeLessThanOrEqual(1);
    expect(measured.lines, "at most two lines").toBeLessThanOrEqual(2);
    expect(measured.cut, "the long title is cut, with an ellipsis").toBe(true);
    expect(measured.ellipsis).toBe("ellipsis");
    expect(measured.clamp).toBe("2");
    expect(measured.insideBox, "the control is inside its lane").toBe(true);
    // The whole title and its time show on keyboard focus, and on hover.
    const button = member.getByRole("button");
    // Scrolled into view first: a scroll of the grid closes an open tooltip, and focusing a button below the frame scrolls it.
    await member.scrollIntoViewIfNeeded();
    await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
    await page.keyboard.press("Tab");
    await button.focus();
    await expect(page.getByRole("tooltip")).toContainText(long, { timeout: 3_000 });
    await button.blur();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    const at = (await button.boundingBox())!;
    await page.mouse.move(at.x + at.width / 2, at.y + at.height / 2, { steps: 8 });
    await expect(page.getByRole("tooltip")).toContainText(long, { timeout: 3_000 });
  });

  // One test for each width: a test that opens the Schedule three times (a page load each) for four widths in a row ran past the
  // test's own 60 s on a loaded machine though every wait in it was answered; each width is its own test with its own limit.
  for (const [width, height] of [
    [1024, 900],
    [1280, 900],
    [1440, 900],
    [2000, 1100],
  ]) {
    test(`S-0338: where else: the rule is the same in Day, Work week and Week at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      for (const key of ["1", "2", "3"] as const) {
        await openView(page, key, day);
        const found = await clashes(page, day);
        expect(found, `${width} view ${key}`).toBeTruthy();
        const pair = found!.clashes.find((c) => c.text.includes("Roof inspection"))!;
        // Side by side exactly where each of its two lanes gets at least 85px; one card with every title whole below it.
        // A card that has had to grow into the next one (a long title in a narrow lane) is one block with it, so then the pair stands beside
        // others and each lane needs its 85px among all of them.
        const joined = pair.text.includes("Garden visit");
        if (joined) expect(!pair.side || found!.column / 3 >= 85, `${width}px view ${key}, column ${found!.column}px: joined to the clash before it`).toBe(true);
        else expect(pair.side, `${width}px view ${key}, column ${found!.column}px`).toBe(found!.column / 2 >= 85);
        // A clash always says "Clash" in words, whatever its width, and its accessible name starts with the word (the reviewer's answer 3).
        expect(pair.label, `${width}px view ${key}: the clash's name`).toMatch(/^Clash: /);
        if (pair.side) {
          expect(pair.members.every((m) => m.whole)).toBe(true);
          expect(pair.tag).toBe("Clash");
        } else {
          expect(pair.head, `${width}px view ${key}: the card says Clash`).toMatch(/^Clash/);
          expect(pair.rows.every((r) => r.whole), `${width}px view ${key}: titles whole`).toBe(true);
          expect(pair.moreButtons.every((m) => m.inside)).toBe(true);
          expect(pair.cardInside).toBe(true);
          expect(pair.head, `${width}px view ${key}: the reason is on the card`).toMatch(/^Clash · (\d+ at once, )?(they overlap by \d+ min|\d+ min overlap)$/);
        }
        const trio = found!.clashes.find((c) => c.text.includes("Dentist visit"))!;
        // Every meeting is a row or counted in the card's "+N more".
        expect(trio.rows.length + trio.hiddenRows, `${width} view ${key}: three meetings`).toBe(3);
        expect(trio.rows.map((r) => r.text).join(" ")).toMatch(/^15:00Dentist visit|^3:00 PM ?Dentist visit/);
        expect(trio.rows.every((r) => r.whole)).toBe(true);
        expect(trio.moreButtons.every((m) => m.inside)).toBe(true);
      }
    });
  }

  test("S-0338: where else: the phone's list names each meeting", async ({ page }) => {
    // The phone: a list by day, the clash a heading that says Clash and each meeting a row with its whole title.
    await page.setViewportSize({ width: 390, height: 844 });
    await openScreen(page, "schedule");
    // The meetings are on the next weekday, which on a Friday is next week: move to its week first (an empty week is the empty list).
    await expect(page.locator("main [data-schedule-list]").first()).toBeVisible(LOAD);
    // Next weekday is at most one week on; the page is given the time to draw the week it moved to.
    if ((await page.locator(`main section[data-day="${day}"]`).count()) === 0) await page.locator("body").press("ArrowRight");
    await expect(page.locator(`main section[data-day="${day}"]`)).toBeVisible(LOAD);
    await expect(page.locator("main [data-schedule-list]")).toBeVisible();
    const list = page.locator(`main section[data-day="${day}"] li[data-clash]`).filter({ hasText: "Dentist visit" });
    await expect(list.locator("p").first()).toContainText("Clash");
    for (const title of ["Dentist visit", "School pickup", "Library return"]) await expect(list.getByRole("button", { name: new RegExp(title) })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  // One test for each width, as the width tests of S-0338: all twelve page loads in one test ran past its 60 s on a loaded machine. The
  // meetings are added by the first (the file runs in order).
  const lone = "Lantern walk-through";
  const group = ["Budget sync", "Vendor call", "Fitting slot"];
  for (const [width, height] of [
    [1024, 900],
    [1280, 900],
    [1440, 900],
    [2000, 1100],
  ]) {
    test(`S-0416: a meeting that overlaps the start of a clash, beside a chain of overlapping clashing meetings, is never drawn over them, in every view at ${width}px`, async ({ page }) => {
      // The picture's layout: one meeting from 21:08 that the engine's pairs do not link to the others, which start at 21:30 and overlap in a chain.
      if (width === 1024) {
        await add(page, lone, day, "21:08", "22:30");
        await add(page, group[0], day, "21:30", "22:15");
        await add(page, group[1], day, "21:45", "22:30");
        await add(page, group[2], day, "22:00", "22:40");
      }
      // The engine pairs everything that overlaps; the pairs naming the lone meeting are taken out of what the screen is given, so it is
      // an ordinary entry that overlaps a clash (as it is for one the person is not attending, or a pair marked fine).
      await page.route(/\/api\/schedule\?/, async (route) => {
        // A request still in flight when the test moves on or ends fails because the page is gone; that is no failure of the screen.
        const response = await route.fetch().catch(() => null);
        if (!response) return;
        const body = (await response.json()) as { days: Array<{ timed: Array<{ title: string; snapshot: string; start: string }> }>; clashes: Array<{ first: { snapshot: string; start: string }; second: { snapshot: string; start: string } }> };
        const ids = new Set(body.days.flatMap((d) => d.timed.filter((e) => e.title === lone).map((e) => `${e.snapshot}#${e.start}`)));
        body.clashes = body.clashes.filter((c) => !ids.has(`${c.first.snapshot}#${c.first.start}`) && !ids.has(`${c.second.snapshot}#${c.second.start}`));
        await route.fulfill({ response, json: body }).catch(() => undefined);
      });
      await page.setViewportSize({ width, height });
      for (const key of ["1", "2", "3"] as const) {
        await openView(page, key, day);
        const at = `${width}px view ${key}`;
        const found = await drawnIn(page, day, [lone, ...group]);
        expect(found.overlaps, `${at}: nothing is drawn over anything else`).toEqual([]);
        expect(found.unwhole, `${at}: every time label whole inside its box`).toEqual([]);
        // The meeting is laid out with the group, never as an ordinary entry beside it; the 85px rule decides side by side or the one card.
        expect(found.block, `${at}: the four are one block`).toBeTruthy();
        expect(found.ordinaryTitles.filter((t) => t.includes(lone)), at).toEqual([]);
        expect(found.block!.side, `${at}, column ${Math.round(found.column)}px`).toBe(found.column / 4 >= 85);
        if (found.block!.side) expect(found.block!.lanes, at).toBeGreaterThanOrEqual(4);
        else expect(found.block!.lanes, at).toBe(0);
      }
      await page.unrouteAll({ behavior: "ignoreErrors" });
    });
  }

  const WIDTHS = [
    [1024, 900],
    [1280, 900],
    [1440, 900],
    [2000, 1100],
  ];
  const nextWeekday = (from: string) => {
    const at = new Date(`${from}T12:00:00Z`);
    do at.setUTCDate(at.getUTCDate() + 1);
    while ([0, 6].includes(at.getUTCDay()));
    return at.toISOString().slice(0, 10);
  };

  // The designer's evening (6:13 for half an hour, 6:43, 7:00, 7:30: places apart so the engine pairs them) with three small meetings after
  // it that overlap nothing, and two that only touch in the morning.
  const evening = async (page: Page) => {
    for (const [what, from, to, where] of [
      ["Morning alpha", "08:00", "08:30", "Room 9"],
      ["Morning beta", "08:30", "09:00", "Room 8"],
      ["Venue walk-through", "18:13", "18:43", "Room 4"],
      ["Budget check-in", "18:43", "19:13", "Room 2"],
      ["Supplier call", "19:00", "19:45", "Room 1"],
      ["Fitting appointment", "19:30", "19:50", "Room 3"],
      ["Plan review", "20:00", "20:15", ""],
      ["Supplier call", "20:15", "20:30", ""],
      ["Venue check", "20:30", "20:45", ""],
    ])
      await add(page, what, later, from, to, where ? { where } : {});
  };

  // One test for each width (twelve page loads in one test ran past its 60 s on a loaded machine); the first adds the evening's meetings.
  for (const [width, height] of WIDTHS)
  test(`S2-1: meetings that only touch, and the designer's evening, are never drawn over one another, and every title and time is whole, in every view at ${width}px`, async ({ page }) => {
    {
      if (width === WIDTHS[0][0]) await evening(page);
      await page.setViewportSize({ width, height });
      for (const key of ["1", "2", "3"] as const) {
        await openView(page, key, later);
        const found = await drawnIn(page, later);
        const at = `${width}px view ${key}`;
        expect(found.overlaps, `${at}: no box is over another`).toEqual([]);
        expect(found.unwhole, `${at}: every title and time whole inside its box`).toEqual([]);
      }
    }
  });

  for (const [width, height] of WIDTHS)
  test(`S2-2: a clash card holds only the meetings it overlaps, each once, and takes room only where nothing is, with the rest in its +N more, at ${width}px`, async ({ page }) => {
    {
      await page.setViewportSize({ width, height });
      for (const key of ["1", "2", "3"] as const) {
        await openView(page, key, later);
        const at = `${width}px view ${key}`;
        const found = await page.evaluate((date) => {
          const lane = document.querySelector<HTMLElement>(`main ul[data-day="${date}"]`)!;
          return Array.from(lane.querySelectorAll<HTMLElement>(":scope > li[data-clash]")).map((li) => {
            const card = li.querySelector<HTMLElement>("[data-group-card]");
            const cardBox = card?.getBoundingClientRect();
            const keys = Array.from(li.querySelectorAll<HTMLElement>("[data-entry-key]")).map((b) => b.dataset.entryKey ?? "");
            const hidden = Array.from(card?.querySelectorAll<HTMLElement>("ul > li") ?? []).filter((r) => r.hidden).length;
            const rows = Array.from(card?.querySelectorAll<HTMLElement>("ul > li") ?? []).filter((r) => !r.hidden);
            const head = card?.querySelector<HTMLElement>("p");
            let headOneLine = true;
            let headText = "";
            const text = head?.querySelector("span:last-child")?.firstChild;
            if (text?.textContent) {
              const found = /\d+\smin/.exec(text.textContent);
              if (found) {
                const range = document.createRange();
                range.setStart(text, found.index);
                range.setEnd(text, found.index + found[0].length);
                headOneLine = new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top))).size <= 1;
                headText = `${text.textContent} / ${Array.from(range.getClientRects()).map((r) => Math.round(r.top)).join(",")}`;
              }
            }
            return {
              text: (li.textContent ?? "").replace(/\s+/g, " "),
              keys,
              duplicates: keys.length - new Set(keys).size,
              hidden,
              more: li.querySelectorAll("[data-group-more]").length,
              rowsInside: !cardBox || rows.every((r) => r.getBoundingClientRect().bottom <= cardBox.bottom + 1),
              headOneLine,
              headText,
            };
          });
        }, later);
        const block = found.find((b) => b.text.includes("Venue walk-through"));
        expect(block, `${at}: the evening's clash is one block`).toBeTruthy();
        for (const b of found) {
          expect(b.text, `${at}: nothing that overlaps no meeting of the clash is in it`).not.toMatch(/Plan review|Venue check/);
          expect(b.duplicates, `${at}: each meeting once`).toBe(0);
          if (b === block) expect(b.keys, `${at}: the block has the clash's four meetings and no other`).toHaveLength(4);
          expect(b.rowsInside, `${at}: no row is partly out of its card`).toBe(true);
          expect(b.headOneLine, `${at}: "45 min" stays on one line: ${b.headText}`).toBe(true);
          if (b.hidden > 0) expect(b.more, `${at}: rows left out are counted in a +N more`).toBe(1);
        }
        const plain = await page.locator(`main ul[data-day="${later}"] > li:not([data-clash]):not([data-now])`).allTextContents();
        expect(plain.join(" | "), `${at}: the three small meetings are drawn on their own`).toMatch(/Plan review[\s\S]*Venue check/);
      }
    }
  });

  test("S2-3: the hours shown are the working day, grown to hold the last entry (round 3, r3-c1), until all hours are asked for", async ({ page }) => {
    const third = nextWeekday(later);
    await add(page, "Evening class", third, "18:13", "18:43");
    await add(page, "Lock-up", third, "18:50", "19:10");
    await page.setViewportSize({ width: 1440, height: 900 });
    await openView(page, "1", third);
    const labels = () => page.locator("main [data-hour]").allTextContents();
    // The working day starts at 8 AM; the last entry ends at 7:10 PM, so the last hour shown is 7 PM (the hour it ends in).
    expect((await labels())[0]).toMatch(/^(8 AM|08)$/);
    expect((await labels()).at(-1)).toMatch(/^(7 PM|19)$/);
    await page.getByRole("button", { name: "Show all hours" }).click();
    expect((await labels())[0]).toMatch(/^(12\s?AM|00|0)$/);
  });

  // One test for each width (five page loads, each reaching its day by key, ran past the test's 60 s on a loaded machine); the first adds the meetings.
  for (const [width, height] of [
    [1700, 1000],
    [1800, 1000],
    [1900, 1000],
    [2000, 1100],
    [2200, 1100],
  ])
    test(`S2-4: a lane of 85 px or more shows its title and its start time unclipped, with only the place shortened, at ${width}px`, async ({ page }) => {
      const fourth = nextWeekday(nextWeekday(later));
      if (width === 1700)
        for (const [what, where] of [
          ["Quarterly planning review", "Conference Room Number Seven"],
          ["Supplier negotiation", "Harbor Street Annex"],
          ["Venue walk-through", "Main Hall Foyer"],
          ["Budget check-in", "Studio Two"],
        ])
          await add(page, what, fourth, "14:00", "14:30", { where });
      await page.setViewportSize({ width, height });
      await openView(page, "2", fourth);
      const found = await drawnIn(page, fourth, ["Quarterly planning review", "Supplier negotiation", "Venue walk-through", "Budget check-in"]);
      const lane = found.block?.side ? found.column / 4 : 0;
      const seen = `${width}px: column ${Math.round(found.column)}, lane ${Math.round(lane)}, ${found.block?.side ? "side by side" : "card"}, clipped: ${found.unwhole.length}`;
      expect(found.unwhole, seen).toEqual([]);
    });

  test("S-0344: Month with an entry's details open keeps every day wide enough to read its chips", async ({ page }) => {
    const title = "Get a catering quote for the autumn venue walk";
    await add(page, title, day, "08:00", "08:30");
    for (const [width, height] of [
      [1440, 900],
      [1280, 900],
      [1920, 1000],
    ]) {
      await page.setViewportSize({ width, height });
      await openView(page, "4", day);
      // A day lists `ui.schedule.month_entries` (2) entries, so the chip read is the first one the day lists.
      await page.locator(`main [data-month] section[data-day="${day}"] ul button`).first().click();
      await expect(page.locator("[data-detail-pane], [data-pane]").first().or(page.getByRole("button", { name: "Open the event" }))).toBeVisible(LOAD);
      const measured = await page.evaluate((date) => {
        const cell = document.querySelector<HTMLElement>(`main [data-month] section[data-day="${date}"]`)!;
        const chip = Array.from(cell.querySelectorAll<HTMLElement>("ul button")).find((b) => b.querySelector("[class*='name']"))!;
        const name = chip.querySelector<HTMLElement>("[class*='name']")!;
        // A title wraps at its words: no line of it is cut inside a word, so no word is taller than one line's worth of letters.
        const line = parseFloat(getComputedStyle(name).lineHeight);
        const words = (name.textContent ?? "").split(/\s+/).length;
        return {
          month: Math.round(document.querySelector("main [data-month]")!.getBoundingClientRect().width),
          cell: Math.round(cell.getBoundingClientRect().width),
          lines: Math.round(name.getBoundingClientRect().height / line),
          words,
          page: document.documentElement.scrollWidth <= window.innerWidth,
        };
      }, day);
      expect(measured.cell, `${width}px: a day is at least 128px`).toBeGreaterThanOrEqual(128);
      // A title of nine words fills at most about as many lines as it has words, never one line for every few letters.
      expect(measured.lines, `${width}px: the chip's title is ${measured.lines} lines`).toBeLessThanOrEqual(Math.ceil(measured.words * 0.75));
      expect(measured.page).toBe(true);
    }
  });

  test("S-0367: Move this date keeps the meeting's length, in the pane, on its own page and for a called-off meeting", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // A meeting that repeats weekly, 10:30 to 11:45 (an hour and a quarter), so its end is not a round number from the start.
    await add(page, "Planning round", day, "17:00", "18:15", { repeat: "week" });
    await openView(page, "3", day);
    await page.locator(`main ul[data-day="${day}"]`).getByRole("button", { name: /Planning round/ }).first().click();
    await page.getByRole("button", { name: /More actions for Planning round/ }).click();
    await page.getByRole("menuitem", { name: "Move this date…" }).click();
    const form = page.locator('[data-act-form="move-event"]');
    const box = moveBoxes(form);
    await expect(box.startTime).toHaveValue(clock(17, 0));
    await expect(box.endTime).toHaveValue(clock(18, 15));
    // The reviewer's step: change the start, leave the end alone, and say Move it.
    await box.startTime.fill("19:00");
    await box.startTime.press("Tab");
    await expect(box.endTime, "the end moves with the start and the length stays").toHaveValue(clock(20, 15));
    await form.getByRole("button", { name: "Move it" }).click();
    await expect(page.getByText("Type a start and an end that comes after it.")).toHaveCount(0);
    await expect(page.getByText("Moved that date.")).toBeVisible(LOAD);
    // At 19:00 it is one of a clash: its row in the card says the new start in its hover text (round 3: one line a meeting; "+N more" only
    // when the card cannot hold them all).
    const card = page.locator(`main ul[data-day="${day}"] > li[data-clash]`, { hasText: "Planning round" });
    await expect(card.getByRole("button", { name: /Planning round/ }).first()).toHaveAttribute("title", /19:00|7:00 PM/);

    // Where else the same form is used: Move to another time on a meeting that does not repeat, from its own page.
    // On a day of its own: the evening of the shared day is full of clashes whose cards draw only the rows that fit.
    const quiet = nextWeekday(nextWeekday(nextWeekday(later)));
    await add(page, "Stock take", quiet, "20:00", "20:45");
    await openView(page, "3", quiet);
    await page.locator(`main ul[data-day="${quiet}"]`).getByRole("button", { name: /Stock take/ }).first().click();
    await page.getByRole("link", { name: /Open the event/ }).click();
    await page.getByRole("button", { name: /More actions for Change this event/ }).first().click();
    await page.getByRole("menuitem", { name: "Move to another time…" }).click();
    const own = moveBoxes(page.locator('[data-act-form="move-event"]'));
    await own.startTime.fill("21:30");
    await own.startTime.press("Tab");
    await expect(own.endTime).toHaveValue(clock(22, 15));
    await page.locator('[data-act-form="move-event"]').getByRole("button", { name: "Move it" }).click();
    await expect(page.getByText("Type a start and an end that comes after it.")).toHaveCount(0);
    await expect(page.getByText("Moved.", { exact: true })).toBeVisible(LOAD);

    // And a called-off meeting given a new date: the same form, the same length.
    await page.getByRole("button", { name: /More actions for Change this event/ }).first().click();
    await page.getByRole("menuitem", { name: "Call it off" }).click();
    await expect(page.getByText(/Called off Stock take/)).toBeVisible(LOAD);
    // It comes back on Today as a line that asks for its new date.
    await page.goto("?token=e2e-token");
    const line = page.locator('[data-queue-line="called_off"]').filter({ hasText: "Stock take" });
    await expect(line).toBeVisible(LOAD);
    await line.getByRole("button", { name: "New date", exact: true }).click();
    const again = moveBoxes(page.locator('[data-act-form="move-event"]'));
    await again.startTime.fill("22:00");
    await again.startTime.press("Tab");
    await expect(again.endTime).toHaveValue(clock(22, 45));
  });

  test("S-0368: calling a meeting off is one way, the pane says so at once, and the app's own calendar is named in the key", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await add(page, "Shed clear-out", day, "07:00", "07:45");
    await openView(page, "3", day);
    await page.locator(`main ul[data-day="${day}"]`).getByRole("button", { name: /Shed clear-out/ }).first().click();
    await page.getByRole("button", { name: /More actions for Shed clear-out/ }).click();
    const items = await page.getByRole("menuitem").allTextContents();
    // The reviewer saw both "Call it off" and "Cancel this event" (two ways to do one thing).
    expect(items).toContain("Call it off");
    expect(items.filter((i) => /cancel|call it off|call off/i.test(i))).toEqual(["Call it off"]);
    await page.getByRole("menuitem", { name: "Call it off" }).click();
    // The pane changes at once, with no reload: it says the meeting is paused, and no longer offers to call it off.
    await expect(page.getByText("Paused: called off").first()).toBeVisible({ timeout: 3_000 });
    await page.getByRole("button", { name: /More actions for Shed clear-out/ }).click();
    await expect(page.getByRole("menuitem", { name: "Call it off" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    // The Timeline's key names the app's own calendar, as the pane does, and not only "Calendar entry".
    await openView(page, "5", day);
    await expect(page.locator('main [aria-label="Key"]')).toContainText("The app's own calendar", LOAD);
  });
  test("S-0368: the reviewer's steps: a one-time meeting already past today, on a business side, opened from the Weekdays view and called off from its pane", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("?token=e2e-token");
    const today = ((await (await page.request.get("api/schedule")).json()) as { today: string }).today;
    // The reviewer's meeting was on a business side: add one the way setup does, and read its id.
    expect((await page.request.post("api/setup/business", { data: { name: "Harbor Studio", kind: "business" } })).ok()).toBe(true);
    const sides = ((await (await page.request.get("api/setup/business")).json()) as { sides?: { project: string; kind: string }[] }).sides ?? [];
    expect(sides.filter((x) => x.kind === "business").length, "a business side to put it on").toBeGreaterThan(0);
    // A one-time meeting added with "Add to schedule" (the app's own calendar), on a side when the workspace has one, early in the
    // day so it is already past; the reviewer's was 1:30 to 2:30 in the morning with the clock at about 4 in the afternoon.
    await add(page, "Planning chat", today, "00:30", "00:45", { side: sides.find((x) => x.kind === "business")!.project });
    await openView(page, "2", today);
    const lane = page.locator(`main ul[data-day="${today}"]`);
    await lane.getByRole("button", { name: /Planning chat/ }).first().click();
    await expect(page.getByRole("button", { name: /More actions for Planning chat/ })).toBeVisible(LOAD);
    await page.getByRole("button", { name: /More actions for Planning chat/ }).click();
    await page.getByRole("menuitem", { name: "Call it off" }).click();
    // The pane shows the paused state, the card its strikethrough and "Paused: called off", at once and with no reload.
    // A called-off meeting before the hours the day's other meetings set is not drawn (it does not stretch the hours): the pane says it at once.
    const pane = page.locator('aside[aria-label="Planning chat"]').locator("[data-pill]", { hasText: "Paused: called off" });
    await expect(pane, "the pane's, at once").toHaveCount(1, { timeout: 3_000 });
    await expect(lane.getByRole("button", { name: /Planning chat/ }), "none on the grid, where its hour is out of the hours shown").toHaveCount(0);
    // With every hour shown its card is there, struck through and saying so, with no reload.
    await page.locator("[data-all-hours]").dispatchEvent("click");
    await expect(pane, "the pane's, still").toHaveCount(1);
    const card = lane.getByRole("button", { name: /Planning chat/ }).first();
    await expect(card).toContainText("Paused: called off", { timeout: 3_000 });
    await expect(card.locator("[class*='struck']")).toHaveCSS("text-decoration-line", "line-through", { timeout: 3_000 });
    await expect(page.getByRole("button", { name: /More actions for Planning chat/ })).toBeVisible();
  });

  /** The first weekday after `from`. */
  const after = (from: string) => {
    const at = new Date(`${from}T12:00:00Z`);
    do at.setUTCDate(at.getUTCDate() + 1);
    while ([0, 6].includes(at.getUTCDay()));
    return at.toISOString().slice(0, 10);
  };

  test("S3-1 (Q6): a grid entry has a 3px edge in its side's color, the key is the side chips, and no address is on the page", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("?token=e2e-token");
    // Two sides: Personal and a business (the one the earlier steps added, or one added the way setup does).
    let state = (await (
      await page.request.get("api/setup/business")
    ).json()) as {
      personal?: string;
      sides?: { project: string; name: string; kind: string }[];
    };
    if (!(state.sides ?? []).some((x) => x.kind === "business")) {
      expect(
        (
          await page.request.post("api/setup/business", {
            data: { name: "Harbor Studio", kind: "business" },
          })
        ).ok(),
      ).toBe(true);
      state = (await (
        await page.request.get("api/setup/business")
      ).json()) as typeof state;
    }
    const business = state.sides!.find((x) => x.kind === "business")!;
    const fresh = after(after(after(after(after(later)))));
    await add(page, "Edge business", fresh, "09:00", "10:00", {
      side: business.project,
    });
    await add(page, "Edge personal", fresh, "11:00", "12:00", {
      side: state.personal!,
    });
    await openView(page, "1", fresh);
    const found = await page.evaluate(
      ({ date }) => {
        const dot = (slot: string) => {
          const el = document.querySelector<HTMLElement>(
            `main [aria-label="Show"] [data-mark="side"][data-color="${slot}"]`,
          );
          return el ? getComputedStyle(el).backgroundColor : null;
        };
        const edge = (title: string) => {
          const el = Array.from(
            document.querySelectorAll<HTMLElement>(
              `main ul[data-day="${date}"] button[data-entry-key]`,
            ),
          ).find((b) => (b.textContent ?? "").includes(title));
          return el
            ? {
                width: getComputedStyle(el).borderLeftWidth,
                color: getComputedStyle(el).borderLeftColor,
                slot: el.getAttribute("data-side-slot"),
                name: el.textContent ?? "",
              }
            : null;
        };
        const business = edge("Edge business");
        const personal = edge("Edge personal");
        return {
          business,
          personal,
          businessDot: business?.slot ? dot(business.slot) : null,
          personalDot: personal?.slot ? dot(personal.slot) : null,
          text: document.querySelector("main")?.textContent ?? "",
        };
      },
      { date: fresh },
    );
    expect(found.business?.width).toBe("3px");
    expect(found.personal?.width).toBe("3px");
    // The edge is the color of the side's dot in the chip row, and the two sides' colors differ.
    expect(found.business?.color).toBe(found.businessDot);
    expect(found.personal?.color).toBe(found.personalDot);
    expect(found.business?.color).not.toBe(found.personal?.color);
    // The side's name is in the entry's name, so the color is never the only sign.
    await expect(
      page
        .locator(`main ul[data-day="${fresh}"]`)
        .getByRole("button", {
          name: new RegExp(`Edge business.*on ${business.name}`),
        }),
    ).toBeVisible();
    expect(found.text, "no address on the Schedule").not.toMatch(/\S@\S+\.\w+/);
    // The pane says the side with its dot and name.
    await page
      .locator(`main ul[data-day="${fresh}"]`)
      .getByRole("button", { name: /Edge business/ })
      .click();
    await expect(
      page.locator('aside[aria-label="Edge business"] [data-side-mark]'),
    ).toContainText(business.name.slice(0, 20));
  });

  // The clashes drawn on the day `fresh` days ahead (the day the S3-2 tests add three meetings to), as the screen draws them.
  const freshS32 = () => after(after(after(after(after(after(later))))));
  const readClashes = (page: Page) =>
    page.evaluate((date) => {
        const lane = document.querySelector<HTMLElement>(
          `main ul[data-day="${date}"]`,
        );
        return Array.from(
          lane?.querySelectorAll<HTMLElement>(":scope > li[data-clash]") ?? [],
        ).map((li) => ({
          card: !!li.querySelector("[data-group-card]"),
          side: li.hasAttribute("data-side"),
          times: Array.from(li.querySelectorAll<HTMLElement>("[class*='when']"))
            .filter((el) => !el.closest("[hidden]"))
            .map((el) => ({
              whole: el.scrollWidth <= el.clientWidth + 1,
              text: el.textContent,
            })),
        }));
      }, freshS32());

  // Two tests (the 1024 views, then the phone's Day): a test that reaches a day this far ahead by key, in four views, ran past its
  // 60 s on a loaded machine though every wait in it was answered. The first adds the meetings (the file runs in order).
  test("S3-2 (Q1): at 1024 a clash is the one card, with each start time whole", async ({ page }) => {
    const fresh = freshS32();
    await add(page, "Narrow one", fresh, "09:00", "10:00");
    await add(page, "Narrow two", fresh, "09:30", "10:30");
    await add(page, "Narrow three", fresh, "09:45", "10:45");
    const read = () => readClashes(page);
    // 1024: the Weekdays view and the Week (which is the working days here), and the Day.
    await page.setViewportSize({ width: 1024, height: 900 });
    for (const key of ["1", "2", "3"] as const) {
      await openView(page, key, fresh);
      const clashesAt = await read();
      expect(clashesAt.length, `1024, view ${key}`).toBeGreaterThan(0);
      if (key !== "1")
        for (const c of clashesAt)
          expect(c, `1024, view ${key}: the one card`).toMatchObject({
            card: true,
            side: false,
          });
      for (const c of clashesAt)
        for (const t of c.times)
          expect(t.whole, `1024, view ${key}: ${t.text} whole`).toBe(true);
    }
  });

  test("S3-2 (Q1): at 390 a clash is the one card, with each start time whole", async ({ page }) => {
    const fresh = freshS32();
    const read = () => readClashes(page);
    // 390: the Day is the one card, and the Week is a list by day whose clash names every meeting.
    await page.setViewportSize({ width: 390, height: 844 });
    await openView(page, "1", fresh);
    const phone = await read();
    expect(phone.length).toBeGreaterThan(0);
    for (const c of phone) {
      expect(c, "390: the one card").toMatchObject({ card: true, side: false });
      for (const t of c.times)
        expect(t.whole, `390: ${t.text} whole`).toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });

  test("S3-3 (Q2): +N more opens the clash in the side pane, every meeting listed, each opening its own details", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const fresh = after(after(after(after(after(after(after(later)))))));
    const titles = [
      "Quarterly planning",
      "Supplier negotiation",
      "Venue walk-through",
      "Budget check-in",
      "Catering tasting",
      "Insurance renewal",
      "Fire drill briefing",
      "Parking permits",
      "Signage proofs",
      "Photographer call",
      "Translation review",
      "Badge printing",
      "Shuttle booking",
      "Volunteer briefing",
    ];
    // Fourteen meetings that start within the hour: a card that cannot draw them all in the room it has.
    for (const [n, title] of titles.entries())
      await add(
        page,
        title,
        fresh,
        `10:${String(n * 3).padStart(2, "0")}`,
        "11:00",
      );
    await openView(page, "1", fresh);
    const more = page
      .locator(`main ul[data-day="${fresh}"] [data-group-more]`)
      .first();
    await expect(more).toBeVisible(LOAD);
    const hidden = countOf(await more.textContent());
    await more.click();
    const pane = page.getByRole("complementary", {
      name: /The \d+ meetings at/,
    });
    await expect(pane).toBeVisible(LOAD);
    const rows = pane
      .getByRole("list", { name: "Meetings in this clash" })
      .getByRole("button");
    // The card's name says how many meetings overlap ("Clash: 4 meetings overlap, 4:11 PM to 6:00 PM"); the pane lists each by its title.
    const label =
      (await page
        .locator(`main ul[data-day="${fresh}"] [data-group-card]`)
        .first()
        .getAttribute("aria-label")) ?? "";
    const count = Number(/^Clash: (\d+) meetings overlap/.exec(label)?.[1] ?? 0);
    expect(count, "the card names how many meetings").toBeGreaterThan(2);
    const named = await rows.evaluateAll((els) => els.map((el) => (el.querySelector("[class*='name']")?.textContent ?? "").trim()));
    await expect(rows, "every meeting of the clash is listed").toHaveCount(
      named.length,
    );
    expect(hidden, "+N more counts what the card did not draw").toBeLessThan(
      named.length,
    );
    await expect(page.locator("[data-popover]")).toHaveCount(0);
    await rows.filter({ hasText: named[2] }).click();
    await expect(page.locator(`aside[aria-label="${named[2]}"]`)).toBeVisible(
      LOAD,
    );
    await page
      .locator(`aside[aria-label="${named[2]}"]`)
      .getByRole("button", { name: /Back to the \d+ meetings/ })
      .click();
    await expect(pane).toBeVisible(LOAD);
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(more, "focus goes back to the +N more").toBeFocused();
  });
  test("S3-4 (Q2): a clash card grows down only until the next entry, a meeting that starts where the clash ends is never in it, and no Clash tag overlaps a card", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    let at = later;
    for (let n = 0; n < 8; n += 1) at = after(at);
    const names = [
      "Touch alpha",
      "Touch bravo",
      "Touch charlie",
      "Touch delta",
      "Touch echo",
      "Touch foxtrot",
      "Touch golf",
      "Touch hotel",
    ];
    for (const [n, title] of names.entries())
      await add(
        page,
        title,
        at,
        `10:${String(n * 5).padStart(2, "0")}`,
        "11:00",
      );
    await add(page, "Touch wall", at, "11:00", "12:00");
    // A pair that starts right where a card above ends: its Clash tag sits inside its own block.
    await add(page, "Tag first", at, "13:00", "14:00");
    await add(page, "Tag second", at, "13:30", "14:30");
    for (const key of ["1", "2"] as const) {
      await openView(page, key, at);
      await expect(
        page.locator(`main ul[data-day="${at}"] > li[data-clash]`).first(),
      ).toBeVisible(LOAD);
      const found = await page.evaluate((date) => {
        const lane = document.querySelector<HTMLElement>(
          `main ul[data-day="${date}"]`,
        )!;
        const box = (el: Element) => el.getBoundingClientRect();
        const wall = Array.from(
          lane.querySelectorAll<HTMLElement>("button[data-entry-key]"),
        ).find((b) => (b.textContent ?? "").includes("Touch wall"))!;
        // The block the clash is drawn in: its card, or its lanes side by side.
        const card = Array.from(
          lane.querySelectorAll<HTMLElement>(":scope > li[data-clash]"),
        ).find((c) => (c.textContent ?? "").includes("Touch alpha"))!;
        const tags = Array.from(
          lane.querySelectorAll<HTMLElement>("[data-clash-tag]"),
        );
        const others = Array.from(
          lane.querySelectorAll<HTMLElement>(
            "[data-group-card], button[data-entry-key]",
          ),
        );
        // A tag may sit inside its own block; it overlaps nothing outside it (no other entry, no card).
        const overlapping = tags.flatMap((tag) => {
          const t = box(tag);
          const own = tag.closest("li[data-clash]");
          return others
            .filter((o) => !own?.contains(o))
            .filter((o) => {
              const r = box(o);
              return (
                Math.min(t.right, r.right) - Math.max(t.left, r.left) > 1 &&
                Math.min(t.bottom, r.bottom) - Math.max(t.top, r.top) > 1
              );
            })
            .map((o) => (o.textContent ?? "").slice(0, 30));
        });
        return {
          wallInCard: card.contains(wall),
          cardBottom: box(card).bottom,
          wallTop: box(wall).top,
          tags: tags.length,
          overlapping,
        };
      }, at);
      expect(
        found.wallInCard,
        `view ${key}: the meeting that starts where the clash ends is its own entry`,
      ).toBe(false);
      expect(
        found.cardBottom,
        `view ${key}: the clash stops at the next entry`,
      ).toBeLessThanOrEqual(found.wallTop + 1);
      expect(found.tags, `view ${key}: the pair has its tag`).toBeGreaterThan(0);
      expect(
        found.overlapping,
        `view ${key}: a Clash tag overlaps no other entry or card`,
      ).toEqual([]);
    }
  });
});
