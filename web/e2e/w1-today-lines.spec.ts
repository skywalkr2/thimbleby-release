// Today's lines and choices the owner found on their install (S-0568, S-0576, S-0579, S-0574), in a browser at a laptop and a
// phone width: the line for what arrived while the person was away, What changed with set-aside mail, the side question's
// ticks, and the note box. The lists are answered here (the layout server holds none of these states), so the checks are of
// the screens. It runs with the layout project's server.
import { expect, type Page } from "@playwright/test";
import { openScreen, screenReady } from "./open-screen";
import { test } from "./test";

const LOADED = { timeout: 20_000 };
const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];

const line = (over: Record<string, unknown>) => ({ key: "x", group: "decide", kind: "decision", count: 1, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over });
const mail = (snapshot: string, title: string, received: string) => ({ snapshot, source: "src", title, received, version: 1, sides: [], also_in: [], sender: "Sender", unread: true });

async function check1(page: Page, size: { width: number; height: number }) {
    await page.setViewportSize(size);
    await page.route("**/api/today/queue", (route) =>
      route.fulfill({ json: [line({ key: "away", kind: "away", count: 2, at: "2026-11-17T22:30:00+00:00", since: "2026-11-18T08:00:00+00:00" })] }),
    );
    await page.route("**/api/today/arrived", (route) =>
      route.fulfill({
        json: {
          items: [
            mail("S1", "Parcel to collect", "2026-11-17T23:10:00+00:00"),
            mail("S2", "Invoice for May", "2026-11-18T06:00:00+00:00"),
            mail("S3", "Lunch on Friday", "2026-11-18T09:30:00+00:00"),
          ],
          left_out: 0,
          set_aside: 0,
        },
      }),
    );
    await openScreen(page);
    const row = page.getByRole("group", { name: "Look over the 2 things that came in while you were away" });
    await expect(row).toBeVisible(LOADED);
    await expect(row).not.toContainText("While you were away");
    // The neutral tone, never the warning one, and no alarm colour or mark on the line.
    await expect(row.locator("[data-state-mark]").first()).toHaveAttribute("data-tone", "neutral");
    await expect(row.locator('[data-tone="warn"], [data-tone="danger"], [data-tone="need"]')).toHaveCount(0);
    await row.getByRole("button", { name: "Look over" }).click();
    const note = page.locator("[data-came-in-window]");
    await expect(note).toBeVisible(LOADED);
    await expect(note).toContainText("Showing what came in while you were away");
    await expect(page.getByText("Parcel to collect")).toBeVisible();
    await expect(page.getByText("Invoice for May")).toBeVisible();
    await expect(page.getByText("Lunch on Friday")).toHaveCount(0);
    await note.getByRole("button", { name: "Show all" }).click();
    await expect(page.getByText("Lunch on Friday")).toBeVisible();
}

test("the line for what arrived while away is verb first and neutral, and its action opens Came in with only those items, at 1440px", async ({ page }) => {
  await check1(page, WIDTHS[0]);
});

test("the line for what arrived while away is verb first and neutral, and its action opens Came in with only those items, at 390px", async ({ page }) => {
  await check1(page, WIDTHS[1]);
});

const entry = (n: number, act: string) => ({
  ref: `r${n}`,
  act,
  title: act === "set_aside" ? `Sale ${n}` : "Send the floor plan",
  when: "2026-11-17T09:00:00Z",
  because: act === "set_aside" ? "sorting" : "said",
  seen: false,
  undo: null,
  quote: act === "set_aside" ? null : "it went out",
  said_by: null,
  said_by_name: "Ana Cole",
  by_you: false,
  reason: act === "set_aside" ? "it is bulk mail" : null,
  record: null,
  snapshot: act === "set_aside" ? `SNAP-${n}` : null,
  version: 1,
});

async function check2(page: Page, size: { width: number; height: number }) {
    await page.setViewportSize(size);
    await page.route(/\/api\/since-yesterday$/, (route) =>
      route.fulfill({
        json: {
          as_of: "2026-11-17T16:00:00Z",
          since: "2026-11-16T00:00:00Z",
          unseen: 25,
          entries: [entry(0, "closed"), ...Array.from({ length: 24 }, (_, n) => entry(n + 1, "set_aside"))],
          rows_shown: 25,
        },
      }),
    );
    await openScreen(page, "work/since");
    await expect(page.getByRole("heading", { level: 1, name: "Since yesterday" })).toBeVisible(LOADED);
    const list = page.getByRole("group", { name: "What changed since yesterday" });
    await expect(list.getByRole("listitem")).toHaveCount(1);
    const summary = page.locator("[data-since-set-aside]");
    await expect(summary).toContainText("24 messages set aside since yesterday");
    await expect(page.locator("[data-since-count]")).toContainText("1 change");
    await summary.getByRole("link", { name: "Open Handled for you" }).click();
    await expect(page).toHaveURL(/#work\/handled/);
}

test("What changed since yesterday: one change and 24 set-aside messages are one row and one summary row that opens Handled for you, at 1440px", async ({ page }) => {
  await check2(page, WIDTHS[0]);
});

test("What changed since yesterday: one change and 24 set-aside messages are one row and one summary row that opens Handled for you, at 390px", async ({ page }) => {
  await check2(page, WIDTHS[1]);
});

const five = ["Printer prefers PDF/X files.", "Send the proof to the printer", "Which week suits the printer?", "Ask about the paper weight", "The printer closes at five"].map((text, n) => ({
  kind: n === 1 || n === 3 ? "action" : n === 2 ? "question" : "note",
  id: `ITEM-${n}`,
  version: 1,
  text,
}));

async function serveSideQuestion(page: Page, moves: unknown[]) {
  await page.route("**/api/today/queue", (route) =>
    route.fulfill({ json: [line({ key: "unfiled", group: "review", kind: "unfiled", state: "which_side", subject: "Orchard Press", count: 5 })] }),
  );
  await page.route("**/api/unfiled", (route) => route.fulfill({ json: { count: 5, items: five } }));
  await page.route("**/api/filing/questions", (route) =>
    route.fulfill({ json: { questions: moves.length > 0 ? [] : [{ side: "PRJ-first", name: "Orchard Press", sides: [{ side: "PRJ-first", name: "Orchard Press" }], items: five }] } }),
  );
  await page.route("**/api/filing/move", (route) => {
    moves.push(route.request().postDataJSON());
    return route.fulfill({ json: { changeset: "CS-9", count: 3, kept: 2, rule: null } });
  });
  await page.route("**/api/changesets/CS-9/undo", (route) => {
    moves.push("undo");
    return route.fulfill({ json: { restored: [0, 1, 2], skipped: [] } });
  });
}

async function check3(page: Page, size: { width: number; height: number }) {
    await page.setViewportSize(size);
    const moves: unknown[] = [];
    await serveSideQuestion(page, moves);
    await openScreen(page);
    const asked = "These 5 items might be Orchard Press's. Move them there?";
    await page.getByRole("group", { name: asked }).getByRole("button", { name: "Look" }).click();
    const question = page.locator("[data-filing-question]");
    await expect(question).toBeVisible(LOADED);
    await expect(question.getByRole("checkbox")).toHaveCount(5);
    for (const box of await question.getByRole("checkbox").all()) await expect(box).toBeChecked();
    await question.getByRole("checkbox", { name: "Ask about the paper weight" }).uncheck();
    await question.getByRole("checkbox", { name: "The printer closes at five" }).uncheck();
    // It says what Move changes before it is pressed.
    await expect(question).toContainText("These 3 items will be visible with Orchard Press's work. The other 2 stay under Personal.");
    await question.getByRole("button", { name: "Move 3" }).click();
    await expect.poll(() => moves.length, LOADED).toBe(1);
    const body = moves[0] as { side: string; items: Array<{ id: string }>; keep: Array<{ id: string }> };
    expect(body.items.map((i) => i.id)).toEqual(["ITEM-0", "ITEM-1", "ITEM-2"]);
    expect(body.keep.map((i) => i.id)).toEqual(["ITEM-3", "ITEM-4"]);
    await expect(page.getByText(/Moved 3 items to Orchard Press\..*2 items stay under Personal\./)).toBeVisible(LOADED);
    await page.getByRole("button", { name: "Undo" }).click();
    await expect.poll(() => moves.filter((m) => m === "undo").length, LOADED).toBe(1);
    // Not wider than the window.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("the side question: unticking two of five moves three and keeps two, and one Undo covers the step, at 1440px", async ({ page }) => {
  await check3(page, WIDTHS[0]);
});

test("the side question: unticking two of five moves three and keeps two, and one Undo covers the step, at 390px", async ({ page }) => {
  await check3(page, WIDTHS[1]);
});

async function openFirstPerson(page: Page) {
  await openScreen(page);
  const people = (await (await page.request.get("api/people")).json()) as Array<{ id: string }>;
  await page.evaluate((id) => {
    window.location.hash = `records/person/${id}`;
  }, people[0].id);
  await screenReady(page);
}

// The Mac app's web view cannot size a box by its content (S-0574), so the page sizes the note box itself. Here the CSS
// feature is read back as off (the box no longer asks for it), so what is measured is what that web view gets.
async function check4(page: Page, size: { width: number; height: number }) {
    await page.setViewportSize(size);
    await openFirstPerson(page);
    const box = page.locator("[data-composer] textarea");
    await expect(box).toBeVisible(LOADED);
    const measure = () =>
      box.evaluate((el) => {
        const t = el as HTMLTextAreaElement;
        const typed = t.value;
        t.value = t.placeholder;
        const example = t.scrollHeight;
        t.value = typed;
        return {
          sizing: getComputedStyle(t).getPropertyValue("field-sizing") || "fixed",
          client: t.clientHeight,
          scroll: t.scrollHeight,
          example,
          bar: t.offsetWidth - t.clientWidth,
          overflowY: getComputedStyle(t).overflowY,
        };
      });
    const empty = await measure();
    expect(empty.sizing).not.toBe("content");
    expect(empty.client).toBeGreaterThanOrEqual(empty.example);
    expect(empty.bar).toBe(0);
    expect(empty.overflowY).toBe("hidden");
    await box.click();
    await box.fill("one\ntwo\nthree");
    const typed = await measure();
    expect(typed.client).toBeGreaterThan(empty.client - 1);
    expect(typed.scroll).toBeLessThanOrEqual(typed.client);
    await box.fill(Array.from({ length: 30 }, (_, n) => `line ${n}`).join("\n"));
    const long = await measure();
    expect(long.overflowY).toBe("auto");
    expect(long.client).toBeLessThanOrEqual(161);
}

test("the note box opens tall enough for its example with no scroll bar and grows as you type, at 1440px", async ({ page }) => {
  await check4(page, WIDTHS[0]);
});

test("the note box opens tall enough for its example with no scroll bar and grows as you type, at 390px", async ({ page }) => {
  await check4(page, WIDTHS[1]);
});
