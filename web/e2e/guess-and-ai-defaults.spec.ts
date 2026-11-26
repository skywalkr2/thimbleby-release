// A to-do whose owners were a guess from what was learned says so on its row with one click to take it back, and a correction the
// assistant could learn nothing from says so (S-0825, S-0826); a new account's harder work starts on the stronger model (S-0827).
// The server's answers for the row are replaced in the page so the row has a guess to show; the engine side is proven by
// tests/test_by_kind.py and tests/test_learn_correction.py.
import { expect } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";
import { widerThanWindow } from "./journey-helpers";

const LONG = "Send the sponsor thank-you letters for the harbor fair to every business that gave this year, with the printed program";

test.describe("guess and AI defaults", () => {
  test("the row of a guessed owner says who and from which correction, takes it back in one click, and fits at every width", async ({ page }) => {
    let taken = 0;
    await page.route("**/api/open-items", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      const first = data.actions[0];
      first.text = LONG;
      first.guess = { kind_of_work: "what goes out for the fair", learned_on: "2026-11-25", can_take_back: true };
      await route.fulfill({ response, json: data });
    });
    await page.route("**/api/knowledge/learned", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      const second = (await (await page.request.get("api/open-items")).json()).actions[1];
      if (second) data.lines.push({ signal: "SIG-9999", kind: "change_requested", changeset: null, refs: [second.id], state: "nothing", proposal: null });
      await route.fulfill({ response, json: data });
    });
    await page.route("**/api/actions/*/take-back-guess", async (route) => {
      taken += 1;
      await route.fulfill({ json: { changeset: "CS-9999" } });
    });
    await openScreen(page, "work/open");
    const guess = page.locator("[data-guess]").first();
    await expect(guess).toContainText(/, from your correction on Nov 25$|, from your correction on Nov 25 Take it back$/);
    await expect(page.locator("[data-learned-nothing]").first()).toHaveText("Couldn't learn from this; it applies to this to-do only.");
    expect(await widerThanWindow(page, "To-dos with a guess and a line that learned nothing")).toEqual([]);
    await guess.getByRole("button", { name: /^Take back who it goes to/ }).click();
    await expect.poll(() => taken).toBe(1);
    await expect(page.getByText("Taken back. Noted that it didn't fit.")).toBeVisible();
    // Taking it back reads what was learned again; that read may still be on its way when the page closes.
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("an app account's form starts the harder work on the stronger model and keeps the same model for everything as a choice", async ({ page }) => {
    await page.route("**/api/ai/endpoints*", async (route) => {
      const response = await route.fetch();
      const kinds = await response.json();
      for (const k of kinds) {
        if (k.program && !k.model_optional && k.model_examples.length > 1) {
          k.installed = true;
          k.model_deep = k.model_examples[k.model_examples.length - 1];
        }
      }
      await route.fulfill({ response, json: kinds });
    });
    await openScreen(page, "settings/ai");
    await page.getByRole("button", { name: "Add an account" }).first().click();
    const panel = page.getByRole("dialog", { name: "Add an account" });
    const apps = await panel.getByRole("radio").all();
    expect(apps.length).toBeGreaterThan(0);
    const harder = panel.getByLabel("AI model for harder work (optional)");
    let found = false;
    for (const radio of apps) {
      await radio.check();
      if (await harder.count()) {
        found = true;
        break;
      }
    }
    expect(found).toBe(true);
    // The control starts on a named model (the stronger one), not on "same"; "same" is still one of its choices.
    await expect(harder).not.toContainText("Same as the everyday model");
    await harder.click();
    await expect(page.getByRole("option", { name: "Same as the everyday model" })).toHaveCount(1);
    await page.keyboard.press("Escape");
    expect(await widerThanWindow(page, "Add an account with a harder model")).toEqual([]);
  });
});
