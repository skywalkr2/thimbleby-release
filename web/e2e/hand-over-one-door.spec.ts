// What the person writes to the assistant about a to-do is read once (H5-52): "Hand it over" with words sends them to the
// one reading about that record, and with none it still asks for a draft. The server is the real one: the page's click
// is checked by what the engine kept.
import { expect } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

test.describe("H5-52, Hand it over", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  test("words typed in Hand it over go to the one reading about the to-do, and the box says what may happen", async ({ page }) => {
    await openScreen(page, "work/open");
    const row = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: "Mark done: Send the final interior file to the printer" }) });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: /^More actions for/ }).click();
    await page.getByRole("menuitem", { name: "Hand to the assistant" }).click();
    const box = page.getByRole("textbox", { name: /What do you want from it/ });
    await expect(box).toBeFocused();
    await expect(page.getByText(/It may make a rule from it, change or close this to-do, or write a draft for you to read/)).toBeVisible();
    await expect(page.getByText(/drafts it for you/)).toHaveCount(0);
    await box.fill("Any mail from this sender should record reminders on the schedule, but is paid by itself so it should not be a to-do");
    const sent = page.waitForRequest((r) => r.url().includes("/hand-over"));
    await page.getByRole("button", { name: "Hand it over" }).click();
    const id = new URL((await sent).url()).pathname.match(/actions\/([^/]+)\/hand-over/)![1];
    await expect(page.getByText(/is reading what you wrote/)).toBeVisible();
    // The words were written once, as one message about the to-do in its conversation, not as a request for a draft.
    const turns = await page.request.get(`api/records/action/${id}/conversation`);
    expect(turns.ok()).toBe(true);
    const body = (await turns.json()) as { turns: { question: string }[] };
    expect(body.turns).toHaveLength(1);
    expect(body.turns[0].question).toContain("should not be a to-do");
    const handed = (await (await page.request.get("api/actions/handed")).json()) as { action: string }[];
    expect(handed.filter((h) => h.action === id)).toHaveLength(0);
  });
});
