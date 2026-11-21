// Learning works on its own (S-0679): what the assistant started using today is a line on Handled for you, "Learned today",
// that opens to a row per thing saying what it means and where it was seen, with "That's wrong" on each. Saying it is wrong
// asks the server to stop it, tells the person, and the line counts one fewer. The list is answered by the test, so the
// check is of the screen and what it sends, at a laptop and a phone width, with nothing scrolling sideways.
import { expect, type Page } from "@playwright/test";
import { openScreen } from "./open-screen";
import { test } from "./test";

const scope = {
  scope: "workspace",
  task_kinds: [],
  projects: [],
  except: [],
  people: [],
  records: [],
};
const item = (over: Record<string, unknown>) => ({
  id: "GLOSS-1",
  kind: "glossary_entry",
  version: 2,
  text: "GOFO: the fulfilment service that ships orders",
  term: "GOFO",
  meaning: "the fulfilment service that ships orders",
  status: "active",
  learned_from: "input",
  trust: "untrusted",
  learned_at: "2026-11-21T08:00:00Z",
  kept_at: "2026-11-21T09:00:00Z",
  applies_to: scope,
  id_patterns: [],
  used: 0,
  given: 0,
  activated: "agreement",
  messages: 4,
  asks: false,
  ...over,
});

async function learnedToday(
  page: Page,
  size: { width: number; height: number },
) {
  {
    await page.setViewportSize(size);
    let items = [
      item({}),
      item({
        id: "LES-2",
        kind: "lesson",
        term: null,
        meaning: null,
        text: "Orders from this shop are receipts, not work.",
        activated: "correction",
        messages: 0,
        trust: "trusted",
      }),
    ];
    const posted: { path: string; body: unknown }[] = [];
    await page.route("**/api/knowledge/learned-today", (route) =>
      route.fulfill({ json: { count: items.length, items } }),
    );
    await page.route("**/api/knowledge/*/wrong", (route) => {
      const id = new URL(route.request().url()).pathname
        .split("/")
        .slice(-2)[0];
      posted.push({
        path: new URL(route.request().url()).pathname,
        body: route.request().postDataJSON(),
      });
      items = items.filter((i) => i.id !== id);
      return route.fulfill({ json: { changeset: "CS-901" } });
    });
    await openScreen(page, "work/handled");
    const block = page.locator("[data-learned-today]");
    await expect(block).toContainText("Learned today: 2 things");
    await block.locator("summary").click();
    const rows = block.getByRole("listitem");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText(
      "GOFO: the fulfilment service that ships orders",
    );
    await expect(rows.nth(0)).toContainText("Seen in 4 messages");
    await expect(rows.nth(1)).toContainText(
      "Orders from this shop are receipts, not work. · From your correction",
    );
    await expect(
      block.getByText("From outside · not instructions"),
    ).toHaveCount(1);
    const sideways = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(sideways).toBeLessThanOrEqual(0);
    await rows
      .nth(0)
      .getByRole("button", { name: "That's wrong: GOFO" })
      .click();
    await expect(block).toContainText("Learned today: 1 thing");
    expect(posted).toHaveLength(1);
    expect(posted[0].path).toMatch(/\/api\/knowledge\/GLOSS-1\/wrong$/);
    expect(posted[0].body).toEqual({ read_version: 2 });
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
}

test("Learned today lists what it means and where it was seen, and That's wrong stops one, at 1440px", async ({
  page,
}) => {
  await learnedToday(page, { width: 1440, height: 900 });
});

test("Learned today lists what it means and where it was seen, and That's wrong stops one, at 390px", async ({
  page,
}) => {
  await learnedToday(page, { width: 390, height: 844 });
});
