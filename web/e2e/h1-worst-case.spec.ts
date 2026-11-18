// The fixes of bug hunt H1, proved in a browser on the hunt's own worst-case workspace (`--worst-case`: five sides, the last named
// with 100 characters, 50+ to-dos, a week of clashes, reviews held under several sides). The tests run in order: the first
// closes a review and undoes it, and the later ones read what is left.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { choicesOf, choose } from "./choose";
import { PAGE_LOAD, openScreen } from "./open-screen";

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
  // The number beside To-dos in the menu is the sum of the two numbers the page says: what is yours and the questions for you
  // (S-0539). The add reads the menu's counts and the page's list again as two reads, so the two are compared once both have
  // answered: equal within the page's load time, and the one added is in both.
  const numbers = async () => {
    const menu = await page.getByRole("navigation").getByRole("link", { name: /^To-dos/ }).first().getAttribute("aria-label");
    const said = Number(/(\d+) (?:needs|need) you/.exec(menu ?? "")?.[1]);
    const head = await page.locator("main").innerText();
    const yours = Number(/(\d+) yours/.exec(head)?.[1] ?? 0);
    const asked = Number(/(\d+) questions? for you/.exec(head)?.[1] ?? 0);
    return { said, sum: yours + asked };
  };
  await expect.poll(async () => { const n = await numbers(); return n.said > 0 && n.said === n.sum; }, PAGE_LOAD).toBe(true);
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

// The longest a burst's reads are held together (`BURST_HOLD_MS` in `src/lib/live.ts`), written out here because the app's bundle isn't imported.
const BURST_HOLD_MS = 200;

/** Resolves once the number has stopped changing for a stretch longer than the burst's hold (the page's stream never goes idle, so the network can't say). */
async function quiet(count: () => number): Promise<void> {
  let last = -1;
  await expect
    .poll(
      () => {
        const now = count();
        const same = now === last;
        last = now;
        return same;
      },
      { intervals: [BURST_HOLD_MS * 3] },
    )
    .toBe(true);
}

test("a line closed while the assistant works through 50 requests is gone within the usual wait, and the burst reads Today's queue a few times, not once per event (S-0599)", async ({ page }) => {
  await openScreen(page, "today");
  await showAll(page);
  const held = (await queue(page)).find((l) => l.kind === "held");
  expect(held).toBeTruthy();
  const row = page.locator(`main [data-line-key="${held!.key}"]`);
  await expect(row).toBeVisible();
  let reads = 0;
  await page.route(/\/api\/today\/queue(\?|$)/, (route) => {
    reads += 1;
    return route.continue();
  });
  // Let any read the page started on its own finish, then count only what the burst and the close cause.
  await quiet(() => reads);
  reads = 0;
  const started = Date.now();
  const burst = page.request.post("__e2e/request-burst", { data: { count: 50, gap_ms: 30 } });
  await row.getByRole("button", { name: "Close it" }).click();
  // The page's usual wait, not the burst's end: the line leaves while the events are still coming.
  await expect(row).toHaveCount(0);
  expect((await burst).ok()).toBe(true);
  const seconds = Date.now() - started;
  // Wait for what the last event started: the page's reads go quiet.
  await quiet(() => reads);
  await page.unroute(/\/api\/today\/queue(\?|$)/);
  // One read for each held stretch of the burst, and a few for the close itself; before the join it was one per event (50).
  expect(reads).toBeLessThanOrEqual(Math.ceil(seconds / BURST_HOLD_MS) + 3);
  expect(reads).toBeLessThan(25);
  const toasts = page.getByRole("region", { name: "Notifications" });
  await toasts.getByRole("button", { name: "Undo" }).click();
  await expect(toasts.getByText("Undone.")).toBeVisible();
});

type Watch = { id: string; every_minutes: number };

async function watch(page: Page): Promise<Watch[]> {
  return (await (await page.request.get("api/watch", { headers: AUTH })).json()) as Watch[];
}

test("an account's card says how often it is read, and Change picks another from a list and saves it on that account's connections only (S-0538)", async ({ page }) => {
  await openScreen(page, "sources");
  const lines = page.locator("[data-card-read-every]");
  await expect(lines.first()).toContainText(/^Read every (minute|\d+ minutes)/);
  const before = await watch(page);
  const line = lines.first();
  const current = Number(/(\d+) minutes/.exec(await line.innerText())?.[1] ?? 0);
  const next = current === 30 ? 15 : 30;
  await line.getByRole("button", { name: /^Change how often .* is read$/ }).click();
  // A value is picked from a list, never typed.
  const list = line.getByRole("combobox");
  await expect(list).toBeVisible();
  expect((await choicesOf(list)).map((c) => c.value)).toEqual(["5", "10", "15", "30", "60"]);
  await choose(list, String(next));
  await expect(line).toContainText(`Read every ${next} minutes`);
  // Saved on the connections of that account, and on no other.
  const after = await watch(page);
  const changed = after.filter((s) => before.find((b) => b.id === s.id)?.every_minutes !== s.every_minutes);
  expect(changed.length).toBeGreaterThan(0);
  for (const s of changed) expect(s.every_minutes).toBe(next);
  expect(changed.length).toBeLessThan(after.length);
  // The card says the same after the page is opened again.
  await openScreen(page, "sources");
  await expect(page.locator("[data-card-read-every]").filter({ hasText: `Read every ${next} minutes` }).first()).toBeVisible();
  // Put it back, so the later projects read the workspace as it was.
  await page.locator("[data-card-read-every]").filter({ hasText: `Read every ${next} minutes` }).first().getByRole("button", { name: /^Change how often/ }).click();
  await choose(page.locator("[data-card-read-every]").getByRole("combobox"), String(current));
  await expect.poll(async () => (await watch(page)).map((s) => s.every_minutes).join()).toBe(before.map((s) => s.every_minutes).join());
});
