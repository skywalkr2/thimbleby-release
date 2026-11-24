// Batch R3 (Today, notes and to-dos), the closing tests of the review of fb08fa7a. Each follows the reviewer's own steps through the
// screen they named, at their width, and reads what the person sees there (layout is measured in the browser; nothing here reads the
// data instead of the screen). The workspace is the reviewer's many-sides state with notes, long to-dos, today's entries past and to
// come, four items that share a word, a person with to-dos of theirs, and a message that came in (tests/e2e_review_r3.py).
import { mondayAt } from "./clock";
import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import { test } from "./test";

const LOADED = { timeout: 20_000 };

type Seed = Record<string, string>;
let seed: Seed;

test.beforeAll(async ({ request }) => {
  seed = (await (await request.get("__e2e/review-r3")).json()) as Seed;
  expect(seed.enabled).toBeTruthy();
});

const open = async (page: Page, hash: string, width = 1440) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto(`?token=e2e-token#${hash}`);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOADED);
};

/** How many lines of text an element holds: its height over its line height. */
const linesOf = (el: Locator) =>
  el.evaluate((node) => {
    const style = getComputedStyle(node);
    return Math.round(node.getBoundingClientRect().height / (parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.3));
  });

/** The widest any element reaches past the window, in pixels. */
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

const tip = (page: Page, containing: string | RegExp) => page.getByRole("tooltip").filter({ hasText: containing });

test.describe("S-0336 / S-0359 (X86): a title is two lines and an ellipsis, its whole text on hover and focus, and a body is never a title", () => {
  test("Notes: the reviewer's three-sentence note is a two-line title, with its words in full on hover and when the row has the cursor, a calendar note keeps its mark", async ({ page }) => {
    await open(page, "records/notes");
    const row = page.getByRole("listitem").filter({ hasText: "I spoke to the caterer" });
    await expect(row).toBeVisible(LOADED);
    const title = row.locator("[data-row-title]");
    expect(await linesOf(title), "the row's title is at most two lines").toBeLessThanOrEqual(2);
    // The person handed this note in: it is not marked as from outside; the calendar's own note is.
    await expect(row.getByText("From outside")).toHaveCount(0);
    await expect(page.getByRole("listitem").filter({ hasText: "New in Your calendar" }).getByText("From outside")).toBeVisible();
    // The whole sentence is on hover...
    await title.hover();
    await expect(tip(page, "two children who need a smaller portion")).toBeVisible();
    // ... and on focus: the row is the keyboard's stop.
    await page.mouse.move(0, 0);
    await expect(tip(page, "two children who need a smaller portion")).toBeHidden();
    await row.focus();
    await expect(tip(page, "two children who need a smaller portion")).toBeVisible();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });

  test("a note's own page: the title is two lines, the note's words are the page's body, and the tip says the whole title", async ({ page }) => {
    await open(page, `records/note/${seed.note}`);
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText("I spoke to the caterer");
    expect(await linesOf(heading), "the page title is at most two lines").toBeLessThanOrEqual(2);
    const body = page.locator("[data-note-body]");
    await expect(body).toContainText(seed.three_sentences);
    await heading.hover();
    await expect(tip(page, "two children who need a smaller portion")).toBeVisible();
    // The title takes a stop of its own for the keyboard when it is cut, and says the whole title there too.
    await page.mouse.move(0, 0);
    await heading.locator("[data-clamp]").focus();
    await expect(tip(page, "two children who need a smaller portion")).toBeVisible();
    // A short note's page does not repeat it under itself.
    await open(page, `records/note/${seed.short_note}`);
    await expect(page.locator("[data-note-body]")).toHaveCount(0);
  });

  test("To-dos: a long title (an address, a case number) shows its end inside two lines or on hover, never cut mid-meaning, at 1440", async ({ page }) => {
    await open(page, "work/open");
    for (const [needle, last] of [
      ["Print, sign and mail", "United Kingdom"],
      ["Reconcile the supplier invoices", "purchase orders"],
    ]) {
      const row = page.getByRole("listitem").filter({ hasText: needle }).first();
      await expect(row).toBeVisible(LOADED);
      const title = row.locator("[data-row-title]");
      expect(await linesOf(title), `${needle}: at most two lines`).toBeLessThanOrEqual(2);
      // The words are all in the page (no word dropped by a count), and when cut, the whole is on hover.
      await expect(title).toContainText(last);
      await title.hover();
      if ((await title.locator("> div").first().evaluate((el) => el.scrollHeight > el.clientHeight + 1)) === true) await expect(tip(page, last)).toBeVisible();
      await page.mouse.move(0, 0);
    }
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });

  test("To-dos' filter chips: the chevron stands clear of the chosen words, which are not cut (S2-F14)", async ({ page }) => {
    await open(page, "work/open");
    const chips = page.locator("main label:has(button[role=combobox])");
    await expect(chips.first()).toBeVisible(LOADED);
    const found = await chips.evaluateAll((labels) =>
      labels.map((label) => {
        const value = label.querySelector("button[role=combobox] span")!;
        const chip = label.getBoundingClientRect();
        // The chevron is drawn in the chip's right padding: from its right edge in by the gap and its own size.
        const chevron = parseFloat(getComputedStyle(label, "::after").width) || 0;
        const gap = parseFloat(getComputedStyle(label, "::after").right) || 0;
        return {
          name: (label.textContent ?? "").trim().slice(0, 30),
          overlap: value.getBoundingClientRect().right - (chip.right - gap - chevron),
          cut: value.scrollWidth - value.clientWidth,
        };
      }),
    );
    expect(found.length).toBeGreaterThan(0);
    for (const chip of found) {
      expect(chip.overlap, JSON.stringify(chip)).toBeLessThanOrEqual(0);
      expect(chip.cut, JSON.stringify(chip)).toBeLessThanOrEqual(0);
    }
  });

  test("Follow-ups, a person's group: the same long title is two lines at most, whole on hover, and the page does not scroll sideways", async ({ page }) => {
    await open(page, "work/followups");
    const mine = () => page.locator("main [data-clamp]").filter({ hasText: "Reconcile the supplier invoices" }).first();
    await expect(mine()).toBeVisible(LOADED);
    expect(await linesOf(mine()), "at most two lines").toBeLessThanOrEqual(2);
    expect(await overflow(page)).toBeLessThanOrEqual(0);
    // Where it is longer than two lines it ends in an ellipsis and says the whole title on hover.
    await mine().hover();
    await expect(tip(page, "autumn range").first()).toBeVisible();
    // At 1024 as well, with no sideways scroll.
    await page.setViewportSize({ width: 1024, height: 900 });
    expect(await linesOf(mine())).toBeLessThanOrEqual(2);
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });

  test("Month: the one title as long as a paragraph is two lines in its chip, and the week it is in stays short", async ({ page }) => {
    await open(page, "schedule");
    await page.getByRole("tab", { name: "Month" }).or(page.getByRole("button", { name: "Month" })).first().click();
    const chip = page.locator("main [data-month] button[data-entry-key]").filter({ hasText: "Annual planning offsite" }).first();
    await expect(chip).toBeVisible(LOADED);
    const name = chip.locator("[class*='name']").first();
    expect(await linesOf(name), "the chip's title is at most two lines").toBeLessThanOrEqual(2);
    // The chip says the whole title on hover, and on keyboard focus too (a native title does only the first).
    await chip.hover();
    await expect(tip(page, /Annual planning offsite.*Annual planning offsite/)).toBeVisible();
    await page.mouse.move(0, 0);
    await expect(tip(page, /Annual planning offsite.*Annual planning offsite/)).toBeHidden();
    await chip.focus();
    await expect(tip(page, /Annual planning offsite.*Annual planning offsite/)).toBeVisible();
    const week = await chip.evaluate((el) => el.closest("section[data-day]")!.getBoundingClientRect().height);
    expect(week, "a week is not made tall by one title").toBeLessThan(260);
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });

  test("the side menu at 1440: a long side's name is cut with an ellipsis and says its whole name on hover", async ({ page }) => {
    await open(page, "today");
    const nav = page.getByRole("navigation", { name: "Views" });
    for (const name of ["Willowbrook Handmade Ceramics and Garden Supply Cooperative", "Northfield Mobile Bicycle Repair and Neighborhood Delivery Service"]) {
      const link = nav.getByRole("link", { name });
      await link.focus();
      await expect(tip(page, name)).toBeVisible();
    }
  });

  test("search results and What changed: a long title is two lines and no more", async ({ page }) => {
    await open(page, "today");
    await page.locator("header input").first().fill("Reconcile the supplier");
    const results = page.getByRole("list", { name: "Results" }).or(page.locator("[aria-label='Results']")).first();
    await expect(results).toBeVisible(LOADED);
    const first = results.locator("[class*='main']").first();
    await expect(first).toContainText("Reconcile the supplier invoices");
    expect(await linesOf(first), "a result's title is at most two lines").toBeLessThanOrEqual(2);
  });
});

test.describe("S-0356: Month folds the same entry said more than once, as Week does", () => {
  test("three identical to-dos due one day are one chip with its count on the Month, and the same on the Week's strip", async ({ page }) => {
    await open(page, "schedule");
    await page.getByRole("tab", { name: "Month" }).or(page.getByRole("button", { name: "Month" })).first().click();
    const chips = page.locator("main [data-month] button[data-entry-key]").filter({ hasText: "Send the revised budget" });
    await expect(chips.first()).toBeVisible(LOADED);
    expect(await chips.count(), "one chip, not three").toBe(1);
    await expect(chips.first()).toContainText(/3/);
    await page.getByRole("tab", { name: "Week", exact: true }).or(page.getByRole("button", { name: "Week", exact: true })).first().click();
    const week = page.locator("main button[data-entry-key]").filter({ hasText: "Send the revised budget" });
    await expect(week.first()).toBeVisible(LOADED);
    expect(await week.count(), "the week folds it too").toBe(1);
  });
});

test.describe("S-0348: a quoted title loses its end punctuation", () => {
  test("Today's pattern line reads 'Decide about Send the headcount: you have moved its day 5 times', never 'headcount.:'", async ({ page, request }) => {
    // The to-do is moved to another day five times, as the reviewer's was, through the app's own editor route.
    const days = [4, 5, 6, 7, 8].map((n) => new Date(new Date(mondayAt).getTime() + n * 86_400_000).toISOString().slice(0, 10));
    for (const [n, to] of days.entries()) {
      const version = ((await (await request.get("api/open-items")).json()) as { actions: Array<{ id: string; version: number }> }).actions.find((a) => a.id === seed.stopped)!.version;
      const done = await request.post("api/records/edit", { data: { kind: "action", id: seed.stopped, fields: { due: to }, read_version: version } });
      expect(done.ok(), `move ${n + 1}: ${await done.text()}`).toBe(true);
    }
    await open(page, "today");
    const line = page.getByText(/Decide about Send the headcount/);
    await expect(line.first()).toBeVisible(LOADED);
    const said = (await line.first().innerText()).trim();
    expect(said).toBe("Decide about Send the headcount: you have moved its day 5 times");
    await expect(page.getByText(/headcount\.:/)).toHaveCount(0);
  });
});

test.describe("S-0347: Today never names an area with a chopped word", () => {
  test("four to-dos that share 'swatches' offer 'Start the area Swatches', whole, and its second line is not cut mid-word", async ({ page }) => {
    await open(page, "today");
    const line = page.locator('[data-queue-line="area"]');
    await expect(line).toBeVisible(LOADED);
    await expect(line.locator("[data-row-title]")).toHaveText("Start the area Swatches");
    const meta = line.locator("p").first();
    // The line that names the to-dos ends at a whole to-do or says the rest on hover, never a cut word at its end.
    const shown = (await meta.innerText()).trim();
    expect(shown, "the second line ends at a whole to-do name or a whole 'and more'").not.toMatch(/\b\w{1,3}…$/);
  });
});

test.describe("S-0342: Today's schedule card is in time order and folds away what is past", () => {
  test("a calendar's meeting under way, the person's own entries before and after it: one time order, the past folded before the now line, the next entries not hidden behind '1 more'", async ({ page }) => {
    await open(page, "today");
    const card = page.getByRole("region", { name: "Schedule" });
    const list = card.getByRole("list", { name: "Today" });
    await expect(list).toBeVisible(LOADED);
    const rows = list.getByRole("listitem");
    const names = await rows.evaluateAll((els) => els.map((el) => (el.textContent ?? "").replace(/\s+/g, " ").trim()));
    // What has ended is one line, then the now line, then what is to come, by the time each starts, whoever kept it.
    expect(names[0], names.join(" | ")).toMatch(/1 earlier today/);
    expect(names[1]).toMatch(/^Now · /);
    const coming = names.slice(2).filter((n) => !/more in the schedule/.test(n));
    const order = ["Design review", "Yoga class", "Call the printer"].map((t) => coming.findIndex((n) => n.includes(t)));
    expect(order, names.join(" | ")).toEqual([0, 1, 2]);
    // Nothing that has passed is among them, and the line says how many more there are.
    expect(names.some((n) => n.includes("Take the tablets"))).toBe(false);
    expect(names.some((n) => /2 more in the schedule/.test(n))).toBe(true);
    // The folded line opens on what has passed, before the now line.
    await card.getByRole("button", { name: "1 earlier today" }).click();
    const opened = await rows.evaluateAll((els) => els.map((el) => (el.textContent ?? "").replace(/\s+/g, " ").trim()));
    expect(opened.findIndex((n) => n.includes("Take the tablets"))).toBeLessThan(opened.findIndex((n) => /^Now · /.test(n)));
  });
});

test.describe("S-0350 (X89): Follow-ups by project leaves out what is already sent", () => {
  test("To send > By project > '1 due soon': the item already sent and waiting is not listed, on any tab, the one not yet sent is, where it is not already listed", async ({ page }) => {
    await open(page, "work/followups");
    const tab = (name: RegExp) => page.getByRole("tab", { name }).or(page.getByRole("button", { name })).first();
    // The reviewer's precondition: "Send the swatches" was sent and sits under Waiting on them.
    await tab(/Waiting on them/).click();
    await expect(page.getByText("Send the swatches").first()).toBeVisible(LOADED);
    const bands: Record<string, string> = {};
    for (const name of ["To send", "Waiting on them"]) {
      await tab(new RegExp(name)).click();
      await group(page, "By project");
      // A tab with one project shows its items in place; with several, each project is a line that opens its items.
      const lines = page.locator("[data-project-group], [data-in-place]");
      await expect(lines.first(), "the by-project list shows its project or projects").toBeVisible(LOADED);
      let text = (await page.locator("[data-due-soon]").allInnerTexts()).join("\n");
      for (const line of await page.locator("[data-project-group]").all()) {
        await line.locator("[data-expander]").click();
        text += (await page.locator("[data-due-soon]").allInnerTexts()).join("\n");
      }
      bands[name] = text;
    }
    for (const [name, text] of Object.entries(bands)) expect(text, `${name}: ${text}`).not.toContain("Send the swatches");
    // What waits on the person and is due soon is still said, on the tab that does not list it.
    expect(bands["Waiting on them"]).toContain("Return the signed order form");
  });
});

/** Choose how Follow-ups is grouped (By person or By project), when the screen offers the choice. */
async function group(page: Page, name: string) {
  const choice = page.getByRole("radio", { name }).or(page.getByRole("tab", { name })).or(page.getByRole("button", { name, exact: true }));
  if (await choice.count()) await choice.first().click();
}

test.describe("S-0341: an event's and a note's Edit details are editors like the to-do editor", () => {
  test("an entry's Edit details is a drawer with plain labels and a readable start and end: no ISO text, no 'Dropped', no 'Role: None', no 'Area'", async ({ page }) => {
    await open(page, `records/event/${seed.coming}`);
    await page.getByRole("button", { name: "Edit details" }).click();
    const drawer = page.getByRole("dialog", { name: "Edit entry" });
    await expect(drawer).toBeVisible(LOADED);
    for (const label of ["What", "Day", "Starts at", "Ends at", "Place", "Project", "Your part"]) {
      await expect(drawer.getByText(label, { exact: true }).first()).toBeVisible();
    }
    const text = await drawer.innerText();
    expect(text, text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
    expect(text).not.toMatch(/Dropped|Role: None|\bArea\b|PRJ-\d|Exceptions/);
    // Changing where it is and saving says so, with Undo, and the page shows the new place.
    await drawer.getByLabel("Place").fill("The studio, second floor");
    await drawer.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(/Changed Yoga class/)).toBeVisible(LOADED);
    await expect(page.getByText("The studio, second floor").first()).toBeVisible(LOADED);
  });

  test("a note's Edit details is a drawer with the note's words and where it belongs, and saving changes the page", async ({ page }) => {
    await open(page, `records/note/${seed.short_note}`);
    await page.getByRole("button", { name: "Edit details" }).click();
    const drawer = page.getByRole("dialog", { name: "Edit note" });
    await expect(drawer).toBeVisible(LOADED);
    const text = await drawer.innerText();
    expect(text).not.toMatch(/Wording|Area = |PRJ-\d|Trust|Filed by/);
    const words = drawer.getByLabel("The note");
    await expect(words).toBeFocused();
    await words.fill("Ring the printer about the proofs and the invoice");
    await drawer.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("and the invoice", LOADED);
  });
});

test.describe("S-0361: empty and edge states say what to do next", () => {
  test("a message that came in shows the message, and says Received once when it was received as it was sent", async ({ page }) => {
    await open(page, `records/source/${seed.source}`);
    await expect(page.locator("[data-source-body]")).toContainText("The swatches for the curtains are ready to collect");
    await expect(page.getByText("Excerpts")).toBeVisible();
  });

  test("a team's page lists its people, or says no one is in it and where people are", async ({ page }) => {
    await open(page, `records/team/${seed.team}`);
    const members = page.locator("[data-team-members]");
    await expect(members).toContainText("No one is in this team yet");
    await expect(members.getByRole("link", { name: /people/i })).toBeVisible();
  });

  test("Handover with nothing to choose is not titled 'Which copy to keep', and says how to keep a second copy", async ({ page }) => {
    await open(page, "handover");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Where your work is kept");
    await expect(page.locator("[data-handover-next]")).toContainText("synced folder");
    await expect(page.locator("[data-handover-next] a")).toHaveAttribute("href", /#settings\/backups/);
  });

  test("Quality before it has anything to count says what to do while it learns", async ({ page }) => {
    await open(page, "quality");
    await expect(page.locator("[data-quality-next]")).toContainText("count the promises on your own list");
  });

  test("a page that is not there is one design: the same title, one sentence and one filled way back, whatever the address", async ({ page }) => {
    const shapes: string[] = [];
    for (const hash of ["nowhere-at-all", "records/person/PER-9999", "records/note/NOTE-9999"]) {
      await open(page, hash);
      const main = page.locator("main");
      await expect(main.getByRole("heading", { level: 1 })).toHaveText("This page has gone missing");
      const primary = main.locator('[data-variant="primary"]');
      expect(await primary.count(), `${hash}: one filled button`).toBe(1);
      shapes.push(`${await primary.count()}`);
    }
    // A Settings page that is not there does not print a raw id.
    await open(page, "settings/nope");
    await expect(page.getByText(/Nope/)).toHaveCount(0);
  });

  test("Projects: a side with no projects says so beside its name", async ({ page }) => {
    await open(page, "records/projects");
    await expect(page.locator("[data-group-empty]").first()).toContainText("No projects yet");
  });
});

test.describe("S-0591: the Monday goals are the assistant's offer, never the soonest-due to-dos", () => {
  type Goals = { proposed: string[]; offer: string; can_offer: boolean; confirmed: boolean; most: number };
  const goalsOf = async (request: APIRequestContext) => ((await (await request.get("api/brief?form=monday")).json()) as { goals: Goals }).goals;

  test("with to-dos due this week the briefing proposes none by a rule, and asking has the assistant's run make the offer the briefing shows", async ({ request }) => {
    const before = await goalsOf(request);
    expect(before.confirmed).toBe(false);
    // The seeded to-dos are due, yet no rule offers them: until the assistant's run has answered, nothing is proposed.
    if (["none", "working", "needs_go"].includes(before.offer)) expect(before.proposed).toEqual([]);
    // The app may already have asked for this week's reading by itself (something is due); only when it hasn't, and
    // nothing is under way, does the person ask.
    if (before.offer === "none") {
      expect(before.can_offer, "something is due this week, so the person may ask for an offer").toBe(true);
      const asked = await request.post("api/brief/goals/offer");
      expect(asked.ok(), await asked.text()).toBe(true);
    } else {
      expect(["working", "needs_go", "offered", "empty"]).toContain(before.offer);
    }
    // The run is estimated first: it is under way, held for the go, or done with the assistant's goals.
    await expect.poll(async () => (await goalsOf(request)).offer, LOADED).not.toBe("none");
    const after = await goalsOf(request);
    expect(["working", "needs_go", "offered", "empty"]).toContain(after.offer);
    if (after.offer === "offered") {
      const open = (await (await request.get("api/open-items")).json()) as { actions: Array<{ text: string }> };
      const texts = open.actions.map((a) => a.text);
      expect(after.proposed.length).toBeGreaterThan(0);
      expect(after.proposed.length).toBeLessThanOrEqual(after.most);
      // The stand-in assistant words each goal from the to-do it comes from; the goals are its answer, kept on the week's record.
      for (const goal of after.proposed) expect(texts.some((t) => t.includes(goal) || goal.includes(t))).toBe(true);
    } else {
      expect(after.proposed).toEqual([]);
    }
    if (after.offer === "working" || after.offer === "needs_go") {
      expect((await request.post("api/brief/goals/offer")).status(), "one offer in hand at a time").toBe(409);
    }
  });
});
