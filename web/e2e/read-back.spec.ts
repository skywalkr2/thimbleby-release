// A rule the person stated is read back (S-0508, design 6.7): the four lines and Undo on What changed, and a rule that
// contradicts one in force asking which wins, answered from the line on Today. The history and the queue are served by the
// test (the stand-in AI states no rules), so the check is of the screen at a wide window and a phone's, and that nothing
// scrolls sideways; the whole path from a note is proven in `tests/test_read_back.py`.
import { expect, type Page } from "@playwright/test";
import { openScreen } from "./open-screen";
import { test } from "./test";

const BACK = {
  applies: {
    everywhere: false,
    targets: [{ kind: "action", kind_label: "action", field: "project" }],
    filter: [],
    projects: [],
    except: [],
    people: [],
    task_kinds: [],
  },
  unchanged: [{ why: "field", kind: "note", kind_label: "note", field: "project" }],
  overlaps: [{ id: "RULE-3", name: "names-a-project", text: "Every to-do names the project it belongs to." }],
  count: 2,
  items: [
    { kind: "action", id: "ACT-1", title: "Send the final interior file to the printer" },
    { kind: "action", id: "ACT-2", title: "Agree on the back-cover copy" },
  ],
  matches_nothing: false,
};
const HELD = { ask: "contradiction", item: "A to-do never needs a project.", against: ["Every to-do names the project it belongs to."], record: "RULE-3" };

const change = (status: "applied" | "held") => ({
  id: "REQ-1",
  version: 1,
  state: "review",
  created_at: "2026-10-30T09:00:00Z",
  dismissed: false,
  first_go: false,
  stage_task: false,
  refused: false,
  note: null,
  source: null,
  source_title: "A note about to-dos",
  waiting: null,
  changeset: {
    id: "CS-1",
    summary: "Kept a rule.",
    status,
    reviewed: false,
    trust: "trusted",
    ops: [
      {
        index: 0,
        op: "rule.add",
        status,
        reason: status === "held" ? "contradicts a rule you already have" : null,
        group: "op0",
        title: "Add the rule: a to-do never needs a project",
        meta: {},
        held: status === "held" ? HELD : null,
        read_back: BACK,
      },
    ],
  },
});

async function noSideways(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

for (const size of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`a rule stated in a note shows its four lines and Undo at ${size.width}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route("**/api/changes", (route) => route.fulfill({ json: [change("applied")] }));
    let undone: unknown = null;
    await page.route("**/api/changesets/CS-1/undo", (route) => {
      undone = route.request().postDataJSON();
      return route.fulfill({ json: { restored: [0], skipped: [] } });
    });
    await openScreen(page, "work/changed");
    if (size.width < 700) await page.getByRole("button", { name: /A note about to-dos/ }).first().click();
    const lines = page.getByRole("region", { name: "What this rule does" });
    await expect(lines).toBeVisible();
    await expect(lines).toContainText("Applies to");
    await expect(lines).toContainText("to-do project");
    await expect(lines).toContainText("Doesn't change");
    await expect(lines).toContainText("note project");
    await expect(lines.getByRole("link", { name: "Every to-do names the project it belongs to." })).toBeVisible();
    await expect(lines).toContainText("Right now it would change");
    await expect(lines).toContainText("2 open items");
    await lines.getByRole("button", { name: "Show the items" }).click();
    await expect(lines.getByRole("link", { name: "Agree on the back-cover copy" })).toBeVisible();
    await noSideways(page);
    await page.getByRole("button", { name: /More actions for Add the rule/ }).click();
    await page.getByRole("menuitem", { name: "Undo this" }).click();
    await expect.poll(() => undone).toEqual({ ops: [0] });
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });
}

test("a rule that contradicts one in force is a line on Today asking which wins, with the three answers", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("**/api/changes", (route) => route.fulfill({ json: [change("held")] }));
  await page.route("**/api/today/queue", (route) =>
    route.fulfill({
      json: [
        {
          key: "held:CS-1:0",
          group: "decide",
          kind: "held",
          count: 1,
          text: "Add the rule: a to-do never needs a project",
          untrusted: false,
          unpriced: 0,
          actions: [],
          questions: [],
          outcome: {},
          changeset: "CS-1",
          op: 0,
          request: "REQ-1",
          waiting: "contradicts a rule you already have",
          held: HELD,
        },
      ],
    }),
  );
  let answered: unknown = null;
  await page.route("**/api/changesets/CS-1/ops/0/rule-answer", (route) => {
    answered = route.request().postDataJSON();
    return route.fulfill({ json: { ok: "CS-1", retired: "CS-9" } });
  });
  await openScreen(page, "today");
  const line = page.locator('[data-queue-line="held"]');
  await expect(line).toContainText("Choose which rule to follow");
  await expect(line.getByRole("button", { name: "Keep the old rule" })).toBeVisible();
  await expect(line.getByRole("button", { name: "Use the new rule" })).toBeVisible();
  await line.getByRole("button", { name: "Use the new rule" }).click();
  await expect.poll(() => answered).toEqual({ choice: "new", applies_to: null });
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
