// The review of what the assistant learned reads in plain words (S-0580, S-0581), at a wide window and a phone's: every
// card says what changes, where it applies, where it came from and, when it ends, when and why; the person's own typed
// words are marked as theirs; none of the old internal words are on screen; and nothing scrolls sideways. The queue and
// the proposals are served by the test, so the check is of the screen and not of the demo's data.
import { expect, type Page } from "@playwright/test";
import { openScreen } from "./open-screen";
import { test } from "./test";

const AUTH = { Authorization: "Bearer e2e-token" };
const INTERNAL = /Keep for|Filing notes|filing notes|selected kinds|incoming material|not instructions|Expires |task_kinds|applies_to/;

const entry = (over: Record<string, unknown>) => ({
  id: "LES-1",
  kind: "lesson",
  version: 3,
  text: "Alerts like this about the website are work: make each one a to-do.",
  status: "proposed",
  learned_from: "assistant",
  trust: "trusted",
  learned_at: "2026-10-09T14:00:00Z",
  applies_to: { scope: "workspace", task_kinds: [], projects: [], except: [], people: [], records: [] },
  evidence: null,
  came_from: "correction",
  batch: "daily",
  just_this_time_before: 0,
  more_evidence: [],
  used: 0,
  given: 0,
  ...over,
});

async function projectId(page: Page): Promise<string> {
  const projects = (await (await page.request.get("api/projects", { headers: AUTH })).json()) as { id: string; side: boolean }[];
  return projects.find((p) => !p.side)!.id;
}

for (const size of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`every card of the review is in plain words at ${size.width}px, and nothing scrolls sideways`, async ({ page }) => {
    await page.setViewportSize(size);
    const project = await projectId(page);
    const proposals = [
      entry({
        id: "LES-1",
        applies_to: { scope: "projects", projects: [project], task_kinds: ["sort-mail"], except: [], people: [], records: [] },
        evidence: { quote: "12 pages now return an error when a search service visits them", source: "SRC-1" },
        came_from: "input",
        learned_from: "input",
        trust: "untrusted",
        expires_at: "2026-10-23T14:00:00Z",
      }),
      entry({
        id: "LES-2",
        text: "Make each website alert a to-do for a fix.",
        learned_from: "person",
        evidence: { quote: "should be created as to-dos for fixes" },
      }),
      entry({
        id: "ROU-1",
        kind: "routing_entry",
        text: "Photos go to the designer.",
        applies_to: { scope: "workspace", task_kinds: ["notes"], projects: [], except: [], people: [], records: [] },
      }),
    ];
    await page.route("**/api/today/queue", (route) =>
      route.fulfill({
        json: [
          { key: "learned", group: "review", kind: "learned", count: 3, origins: { input: 1, correction: 2 }, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {} },
        ],
      }),
    );
    await page.route("**/api/knowledge/proposals", (route) => route.fulfill({ json: { proposals, origins: { input: 1, correction: 2 }, expired: 0 } }));
    // The lists are answered here before the page first loads, so Today reads them on its first look.
    await openScreen(page, "today");
    await page.locator('[data-queue-line="learned"]').getByRole("button", { name: "Review", exact: true }).click();
    const drawer = page.getByRole("dialog");
    const rows = drawer.getByRole("listitem");
    await expect(rows).toHaveCount(3);
    const texts = await rows.allTextContents();
    for (const text of texts) expect(text).not.toMatch(INTERNAL);
    expect(texts[0]).toContain("Applies to: your mail for");
    expect(texts[0]).toContain("because it came from a message and not from you");
    // "From outside · not instructions" is said once for the list, not on every row.
    expect(texts[0]).not.toContain("From the message, not from you");
    await expect(drawer.getByText("From outside · not instructions")).toHaveCount(1);
    expect(texts[1]).toContain("Your own words");
    expect(texts[1]).toContain("You said:");
    expect(texts[2]).toContain("Applies to: all things that come in");
    // The reason a card ends is on screen whole, never cut: its text is not wider than its row.
    const cut = await drawer.getByRole("listitem").first().evaluate((li) => [...li.querySelectorAll("*")].filter((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "visible").length);
    expect(cut).toBe(0);
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(sideways).toBeLessThanOrEqual(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });
}

// A person the assistant offered is a row on the review card: it says how they would be added, Keep adds them in one
// change that Undo takes back, and "Not this one" leaves them out (S-0534).
async function offeredPersonRow(page: Page, size: { width: number; height: number }) {
  {
    await page.setViewportSize(size);
    const people = [
      { id: "POFR-1", version: 1, name: "Dana Sample", address: "dana@example.com", why: "Writes to you every week and you reply: likely your accountant.", relation: "your accountant", sides: ["Work"], count: 12 },
      { id: "POFR-2", version: 1, name: "Robin Sample", address: "robin@example.com", why: "You write to them often.", relation: null, sides: [], count: 4 },
    ];
    const posted: string[] = [];
    await page.route("**/api/today/queue", (route) =>
      route.fulfill({
        json: [{ key: "learned", group: "review", kind: "learned", count: 2, origins: { person: 2 }, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {} }],
      }),
    );
    await page.route("**/api/knowledge/proposals", (route) => route.fulfill({ json: { people, proposals: [], origins: {}, expired: 0 } }));
    await page.route("**/api/knowledge/people/*/*", (route) => {
      posted.push(new URL(route.request().url()).pathname.split("/api/")[1]);
      return route.fulfill({ json: { changeset: "CS-900" } });
    });
    await openScreen(page, "today");
    await expect(page.locator('[data-queue-line="learned"]')).toContainText("2 people to add");
    await page.locator('[data-queue-line="learned"]').getByRole("button", { name: "Review", exact: true }).click();
    const drawer = page.getByRole("dialog");
    const rows = drawer.getByRole("listitem");
    await expect(rows).toHaveCount(2);
    const texts = await rows.allTextContents();
    expect(texts[0]).toContain("Dana Sample");
    expect(texts[0]).toContain("Added as your accountant");
    expect(texts[0]).toContain("On Work");
    expect(texts[1]).not.toContain("Added as");
    for (const text of texts) expect(text).not.toMatch(INTERNAL);
    await rows.first().getByRole("button", { name: "Add to People" }).click();
    await expect.poll(() => posted).toContain("knowledge/people/POFR-1/keep");
    await expect(page.getByRole("region", { name: "Notifications" }).getByText("Added Dana Sample to People.")).toBeVisible();
    await rows.nth(1).getByRole("button", { name: "More actions for Robin Sample" }).click();
    await page.getByRole("menuitem", { name: "Not this one" }).click();
    await expect.poll(() => posted).toContain("knowledge/people/POFR-2/not-this-one");
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(sideways).toBeLessThanOrEqual(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
}

test("an offered person is a row of the review at 1440px, kept or left out from it, and nothing scrolls sideways (S-0534)", async ({ page }) => {
  await offeredPersonRow(page, { width: 1440, height: 900 });
});

test("an offered person is a row of the review at 390px, kept or left out from it, and nothing scrolls sideways (S-0534)", async ({ page }) => {
  await offeredPersonRow(page, { width: 390, height: 844 });
});
