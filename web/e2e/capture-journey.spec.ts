import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";
import { collectProblems, openFold, openView } from "./journey-helpers";

interface CaptureFixture {
  label: string;
}

interface CapturedNote {
  text: string;
}

async function fixture(page: Page): Promise<CaptureFixture> {
  const response = await page.request.get("/__e2e/capture");
  expect(response.ok()).toBe(true);
  return response.json();
}

async function putNote(page: Page, text: string) {
  const response = await page.request.post("/__e2e/capture", { data: { text } });
  expect(response.status()).toBe(201);
}

async function noteCount(page: Page, text: string) {
  const notes = (await (await page.request.get("api/notes")).json()) as CapturedNote[];
  return notes.filter((note) => note.text === text).length;
}

interface ChangeLine {
  state: string;
  title: { topic: string | null } | null;
}

async function runAnswered(page: Page, text: string) {
  const changes = (await (await page.request.get("api/changes")).json()) as ChangeLine[];
  return changes.some((change) => (change.title?.topic ?? "") === text && (change.state === "review" || change.state === "done"));
}

async function readCapture(page: Page, label: string) {
  const sourceMenu = page.getByRole("button", { name: `More actions for ${label}` });
  await sourceMenu.click();
  // The read answers when it has filed what it found, so the notes are looked for after its answer, not after the click.
  const answered = page.waitForResponse((r) => r.request().method() === "POST" && /\/watch\/[^/]+\/read$/.test(new URL(r.url()).pathname), { timeout: 30_000 });
  await page.getByRole("menuitem", { name: "Read now", exact: true }).click();
  expect((await answered).ok()).toBe(true);
}

/** Reads the folder until the note is filed. A read asked for while the app's own read of the same source is under way does
 * nothing and says so (a source is never read twice at once), and that read may have listed the folder before the note was
 * put in it; so a read that found nothing is asked for again, and a note is still filed once. */
async function readUntilFiled(page: Page, label: string, text: string) {
  await expect(async () => {
    await readCapture(page, label);
    expect(await noteCount(page, text)).toBe(1);
  }).toPass({ timeout: 30_000 });
}

// The journey files notes on its server; a re-run would start from that used server, where the note is there twice, and prove
// nothing: it takes none and shows its failure as it is (S-0560).
test.describe.configure({ retries: 0 });

test("a capture folder files notes once and offers Undo", async ({ page }, testInfo) => {
  const problems: string[] = [];
  collectProblems(page, problems);
  const seeded = await fixture(page);
  const first = `Capture journey: remember the silver heron marker ${testInfo.repeatEachIndex}.`;
  const second = `Capture journey: remember the amber thimble marker ${testInfo.repeatEachIndex}.`;

  await openScreen(page);
  await openView(page, "Connections");

  const sourceMenu = page.getByRole("button", { name: `More actions for ${seeded.label}` });
  await sourceMenu.click();
  const turnOff = page.getByRole("menuitem", { name: "Turn off", exact: true });
  if (await turnOff.isVisible()) {
    await turnOff.click();
    await sourceMenu.click();
  }
  await page.getByRole("menuitem", { name: "Turn on", exact: true }).click();
  await expect(sourceMenu).toBeVisible();

  await putNote(page, first);
  await readUntilFiled(page, seeded.label, first);

  await openView(page, "Notes");
  await expect(page.getByRole("link", { name: first, exact: true })).toBeVisible();

  // What changed reads the changes once when it opens; filing the note can come before its run's change, so the run is waited for.
  await expect.poll(() => runAnswered(page, first), { timeout: 30_000 }).toBe(true);
  await openView(page, "What changed");
  const change = page.getByRole("complementary", { name: `Your note · ${first}` });
  await expect(change).toBeVisible();
  // The card leads with the assistant's sentence; what it did is under its fold.
  await openFold(change);
  await change.getByRole("button", { name: `More actions for ${first}` }).click();
  await page.getByRole("menuitem", { name: "Undo this", exact: true }).click();
  await expect(page.getByText("Undone.")).toBeVisible();
  await expect.poll(() => noteCount(page, first)).toBe(0);

  await openView(page, "Notes");
  await expect(page.getByRole("link", { name: first, exact: true })).toHaveCount(0);
  await openView(page, "Connections");
  await putNote(page, second);
  await readUntilFiled(page, seeded.label, second);

  await openView(page, "Notes");
  await expect(page.getByRole("link", { name: second, exact: true })).toBeVisible();
  await openView(page, "Connections");
  await readCapture(page, seeded.label);
  await expect.poll(async () => ({ first: await noteCount(page, first), second: await noteCount(page, second) })).toEqual({
    first: 0,
    second: 1,
  });

  expect(problems).toEqual([]);
});
