// Report a problem, end to end (S-0610, design 7 Help): the person opens it from Help, writes what happened, sees in what will be
// sent the version, the system and the recent problem lines, and nothing leaves before Send. After Send the report reaches the
// form (this project's server plays the website's form and says what it received). A form that is down is told in words, with
// Try again and Copy the report, and the report is sent once it answers.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";
import { checkAccessibility, collectProblems } from "./journey-helpers";

interface Reports {
  enabled: boolean;
  received: Array<{ words: string; reply_to: string; version: string; system: string; problems: string; details?: string }>;
  status: number;
  failed_read: string;
  log_line: string;
  stopped_answer: string;
}

const reports = async (page: Page): Promise<Reports> => (await page.request.get("/__e2e/reports")).json();
const answerWith = (page: Page, code: number) => page.request.post(`/__e2e/reports?code=${code}`);

async function openReport(page: Page) {
  await openScreen(page);
  await page.getByRole("button", { name: "Help" }).click();
  await page.getByRole("menuitem", { name: "Report a problem" }).click();
  const dialog = page.getByRole("dialog", { name: "Report a problem" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe("Report a problem", () => {
  test("a report shows its version, system and problem lines before anything leaves, and reaches the form only after Send", async ({ page }) => {
    const problems: string[] = [];
    collectProblems(page, problems);
    const seeded = await reports(page);
    expect(seeded.enabled).toBe(true);
    const before = seeded.received.length;

    const dialog = await openReport(page);
    // The cursor is in the first field.
    const words = dialog.getByLabel("What happened?");
    await expect(words).toBeFocused();
    await expect(dialog.getByRole("button", { name: "Send" })).toBeDisabled();
    await words.fill("Today stayed empty after I connected my mail");

    const preview = dialog.locator("textarea[readonly]").first();
    await expect(preview).toHaveValue(/Today stayed empty after I connected my mail/);
    await expect(preview).toHaveValue(/App version: (?!added)\S+/);
    await expect(preview).toHaveValue(/System: (?!added)\S+/);
    await expect(preview).toHaveValue(/Recent problems/);
    await expect(preview).toHaveValue(new RegExp(seeded.failed_read));
    // The technical details are shown before anything leaves.
    await expect(dialog.getByLabel("Technical details", { exact: true })).toHaveValue(new RegExp(seeded.log_line.slice(-30)));
    await checkAccessibility(page);
    // Everything is on screen and nothing has left.
    expect((await reports(page)).received).toHaveLength(before);

    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Sent. Thank you: the makers have your report.")).toBeVisible();
    await expect(dialog).toHaveCount(0);
    const { received } = await reports(page);
    expect(received).toHaveLength(before + 1);
    const got = received[before];
    expect(got.words).toBe("Today stayed empty after I connected my mail");
    expect(got.version).toMatch(/\S/);
    expect(got.system).toMatch(/\S/);
    expect(got.problems).toContain(seeded.failed_read);
    // The technical details reached the form as they were shown.
    expect(got.details).toContain(seeded.log_line);
    expect(Object.keys(got).sort()).toEqual(["details", "problems", "reply_to", "system", "version", "words"]);
    expect(problems).toEqual([]);
  });

  test("with the technical details taken out, none are shown and the form receives none", async ({ page }) => {
    const before = (await reports(page)).received.length;
    const dialog = await openReport(page);
    await dialog.getByLabel("What happened?").fill("Mail stopped arriving");
    await expect(dialog.getByLabel("Technical details", { exact: true })).toBeVisible();
    await dialog.getByRole("checkbox", { name: "Include technical details" }).uncheck();
    await expect(dialog.getByLabel("Technical details", { exact: true })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Sent. Thank you: the makers have your report.")).toBeVisible();
    const got = (await reports(page)).received[before];
    expect(got.words).toBe("Mail stopped arriving");
    expect(got).not.toHaveProperty("details");
  });

  test("the assistant's last answer is offered off, previewed as the exact text, and reaches the form only when turned on", async ({ page }) => {
    const problems: string[] = [];
    collectProblems(page, problems);
    const seeded = await reports(page);
    const choice = "Include the assistant's last answer: it contains your material";

    // Off by default: no preview of it, and a send carries none of it.
    let before = seeded.received.length;
    let dialog = await openReport(page);
    await dialog.getByLabel("What happened?").fill("The request stopped");
    await expect(dialog.getByRole("checkbox", { name: choice })).not.toBeChecked();
    await expect(dialog.getByLabel("The assistant's last answer", { exact: true })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Sent. Thank you: the makers have your report.")).toBeVisible();
    let got = (await reports(page)).received[before];
    expect(JSON.stringify(got)).not.toContain(seeded.stopped_answer);

    // On: the exact text is shown, and the same text is sent.
    before = (await reports(page)).received.length;
    dialog = await openReport(page);
    await dialog.getByLabel("What happened?").fill("The request stopped again");
    await expect(dialog.getByRole("checkbox", { name: choice })).not.toBeChecked(); // off again each time it opens
    await dialog.getByRole("checkbox", { name: choice }).check();
    const shown = dialog.getByLabel("The assistant's last answer", { exact: true });
    await expect(shown).toHaveValue(new RegExp(seeded.stopped_answer));
    await checkAccessibility(page);
    expect((await reports(page)).received).toHaveLength(before);
    const text = await shown.inputValue();
    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Sent. Thank you: the makers have your report.")).toBeVisible();
    got = (await reports(page)).received[before];
    expect(got.details).toContain(text);
    expect(Object.keys(got).sort()).toEqual(["details", "problems", "reply_to", "system", "version", "words"]);
    expect(problems).toEqual([]);
  });

  test("a form that is down is told in words, nothing is lost, and Try again sends once it answers", async ({ page }) => {
    const before = (await reports(page)).received.length;
    await answerWith(page, 503);
    const dialog = await openReport(page);
    await dialog.getByLabel("What happened?").fill("The schedule would not load");
    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(dialog.getByRole("alert")).toContainText("isn't answering right now. Nothing was sent.");
    await expect(dialog.getByLabel("What happened?")).toHaveValue("The schedule would not load");
    await expect(dialog.getByRole("button", { name: "Copy the report" })).toBeVisible();
    expect((await reports(page)).received).toHaveLength(before);

    await answerWith(page, 200);
    await dialog.getByRole("button", { name: "Try again" }).click();
    await expect(dialog).toHaveCount(0);
    const { received } = await reports(page);
    expect(received.slice(before).map((r) => r.words)).toEqual(["The schedule would not load"]);
  });

  test("Escape closes it without sending, and no sideways scroll at a phone width", async ({ page }) => {
    const before = (await reports(page)).received.length;
    await page.setViewportSize({ width: 360, height: 740 });
    await openScreen(page);
    // Exactly the bar's More (or the header's Help): a row's "More actions for ..." button also starts with the word.
    await page.getByRole("button", { name: /^(Help|More)$/ }).first().click();
    await page.getByRole("button", { name: "Report a problem" }).or(page.getByRole("menuitem", { name: "Report a problem" })).click();
    const dialog = page.getByRole("dialog", { name: "Report a problem" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("What happened?").fill("Nothing to send");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    expect((await reports(page)).received.length).toBe(before);
  });

  test("the alpha numbers are shown on this computer, and sharing them sends exactly the previewed text only after Send", async ({ page }) => {
    const problems: string[] = [];
    collectProblems(page, problems);
    const before = (await reports(page)).received.length;
    await openScreen(page);
    await page.getByRole("button", { name: "Help" }).click();
    await page.getByRole("menuitem", { name: "Your alpha numbers" }).click();
    const numbers = page.getByRole("dialog", { name: "Your alpha numbers" });
    await expect(numbers).toBeVisible();
    await expect(numbers.getByText(/^Days used: \d+ of \d+$/)).toBeVisible();
    await expect(numbers.getByText(/^Cost per day: /)).toBeVisible();
    await expect(numbers.getByText(/^Corrections per day: /)).toBeVisible();
    await expect(numbers.getByText(/^Drafts sent as written: \d+\. Edited first: \d+\.$/)).toBeVisible();
    await expect(numbers.getByText(/^Time from install to a first result: /)).toBeVisible();
    await checkAccessibility(page);
    // Looking at the numbers sends nothing.
    expect((await reports(page)).received).toHaveLength(before);

    await numbers.getByRole("button", { name: "Share these with the makers" }).click();
    const dialog = page.getByRole("dialog", { name: "Report a problem" });
    await expect(dialog).toBeVisible();
    const preview = dialog.locator("textarea[readonly]").first();
    await expect(preview).toHaveValue(/My numbers from the alpha/);
    await expect(preview).toHaveValue(/Days used: \d+ of \d+/);
    const shown = await preview.inputValue();
    expect((await reports(page)).received).toHaveLength(before);

    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Sent. Thank you: the makers have your report.")).toBeVisible();
    const { received } = await reports(page);
    expect(received).toHaveLength(before + 1);
    const got = received[before];
    expect(got.words).toContain("Days used:");
    // What the form received is the previewed words, first, then the lines the preview adds.
    expect(shown.startsWith(got.words)).toBe(true);
    expect(problems).toEqual([]);
  });
});
