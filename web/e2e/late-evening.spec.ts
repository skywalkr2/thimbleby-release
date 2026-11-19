// Late evening (the UI/UX re-review of B-9, R-0): after midnight UTC, in a workspace whose time zone is behind UTC, the
// day is still the earlier one where the person is. Marking a message sent and recording a follow-up are written in that
// day, so a wait counts zero days ("sent today"), never a negative number. The project's server starts its clock at
// 00:30 UTC (`--clock-at`), which is the evening before in the demo workspace's zone, and has a server of its own so no
// other scenario's clock or lines are mixed in.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";

interface Section {
  person: string;
  name: string;
  is_pm: boolean;
  to_send: number;
  questions: Array<{ id: string; status: string }>;
  actions: Array<{ id: string; version: number; text: string; told: string | null; to_send: boolean }>;
}

const NEGATIVE_DAYS = /-\d+\s*days?/;

async function signIn(page: Page) {
  await page.goto("?token=e2e-token");
  await expect(page.getByRole("heading", { level: 2, name: "Needs you", exact: true })).toBeVisible();
}

async function openView(page: Page, label: string) {
  const dismiss = page.getByRole("region", { name: "Notifications" }).getByRole("button", { name: "Dismiss" });
  while (await dismiss.count()) await dismiss.last().click();
  const link = page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: new RegExp(`^${label}`) });
  await link.click();
  await expect(link).toHaveAttribute("aria-current", "page");
}

/** No wait on the screen is counted below zero. */
async function expectNoNegativeDays(page: Page) {
  await expect(page.getByRole("main")).not.toContainText(NEGATIVE_DAYS);
}

test.describe("Late evening", () => {
  test("after midnight UTC, in a workspace behind UTC, a message marked sent and a follow-up count zero days, never below", async ({ page }) => {
    await signIn(page);
    await expectNoNegativeDays(page);

    // Someone with an action to send, from the server's own list.
    const sections = (await (await page.request.get("api/followups")).json()) as Section[];
    const target = sections.find((s) => !s.is_pm && s.to_send > 0 && s.actions.some((a) => a.told === null));
    expect(target, "someone with an action to send").toBeTruthy();
    const { name } = target!;
    const sent = target!.actions.filter((a) => a.told === null);

    await openView(page, "Follow-ups");
    await expect(page.getByRole("heading", { name: "Follow-ups", exact: true })).toBeVisible();
    // A person is one line of the list; choosing it shows their message in the detail pane beside the list.
    const card = page.getByRole("listitem", { name, exact: true });
    await expectNoNegativeDays(page);

    // Choosing the person shows the message, Copy puts it on the clipboard, and Mark sent records it.
    await card.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expect(page.locator("aside[data-detail-pane]").getByRole("textbox").first()).toBeVisible();
    await page.locator("aside[data-detail-pane]").getByRole("button", { name: "Copy message" }).first().click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(sent[0].text);
    await page.locator("aside[data-detail-pane]").getByRole("button", { name: "I've sent it" }).first().click();
    await expect(page.getByText(`Marked as sent to ${name}`)).toBeVisible();
    await expectNoNegativeDays(page);

    // Under Waiting on them it was sent today, and no wait shows yet.
    await page.getByRole("button", { name: "Waiting on them" }).click();
    await page.getByRole("listitem", { name, exact: true }).getByRole("button", { name: new RegExp(`^${name}`) }).click();
    const waiting = page.locator("aside[data-detail-pane]", { has: page.getByRole("heading", { name }) });
    const item = waiting.locator("li[data-item]", { hasText: sent[0].text });
    await expect(item).toContainText("sent today");
    await expect(item).not.toContainText(/waiting \d+ days?/);
    await expectNoNegativeDays(page);

    // Recording a follow-up on it starts the wait again, still without a negative count.
    await item.getByRole("button", { name: /^More actions for / }).click();
    await page.getByRole("menuitem", { name: "Followed up" }).click();
    await expect(page.getByText(/^Recorded your follow-up with /)).toBeVisible();
    await expect(waiting.locator("li[data-item]", { hasText: sent[0].text })).toContainText("followed up");
    await expectNoNegativeDays(page);

    // Today shows the same wait without a negative number, however it counts it.
    await openView(page, "Today");
    await expect(page.getByRole("heading", { level: 2, name: "Needs you", exact: true })).toBeVisible();
    await expectNoNegativeDays(page);
    await expect(page.getByRole("main")).not.toContainText(/waiting up to -/);
  });

  // H5-29 O2: what changes after the message was copied did not go out as it now reads. Mark sent leaves it to send and asks; the
  // person's answer that it went as copied is what marks it.
  test("an item that changes between Copy and Mark sent is asked about and stays to send until the person answers", async ({ page }) => {
    await signIn(page);
    const read = async () => (await (await page.request.get("api/followups")).json()) as Section[];
    const target = (await read()).find((s) => !s.is_pm && s.actions.some((a) => a.to_send));
    expect(target, "someone with an action to send").toBeTruthy();
    const { name, person } = target!;
    const item = target!.actions.find((a) => a.to_send)!;
    const still = async () => (await read()).find((s) => s.person === person)?.actions.find((a) => a.id === item.id);

    await openView(page, "Follow-ups");
    const pane = page.locator("aside[data-detail-pane]");
    await page.getByRole("listitem", { name, exact: true }).getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await pane.getByRole("button", { name: "Copy message" }).first().click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(item.text);

    // While the person is in their mail program, the to-do's day moves: the copied message no longer says what the app holds.
    const moved = await page.request.post("api/records/edit", { data: { kind: "action", id: item.id, fields: { due: "2026-12-18" }, read_version: item.version } });
    expect(moved.ok(), await moved.text()).toBe(true);

    await pane.getByRole("button", { name: "I've sent it" }).first().click();
    const asked = page.locator("[data-changed-since-copy]");
    await expect(asked).toBeVisible();
    await expect(asked).toContainText(`after you copied the message to ${name}`);
    await expect(asked).toContainText(item.text);
    expect((await still())?.to_send, "the changed item is not marked sent unseen").toBe(true);

    await asked.getByRole("button", { name: "Yes, mark as sent" }).click();
    await expect(asked).toHaveCount(0);
    await expect.poll(async () => (await still())?.to_send ?? false).toBe(false);
  });
});

// S-0422: a page's clock is its own server's, not the run's: this project's server runs at another moment than every other one,
// and a page, however long into the run it opens, reads that server's moment (within a second) and then keeps ticking with it.
test("the page's clock is the server's, at the moment this server runs at, and ticks", async ({ page }) => {
  await page.goto("?token=e2e-token");
  const read = async () => page.evaluate(() => Date.now());
  // The page's clock is read before and after the server's, so the time the two requests take on a busy computer is not counted
  // against the second the page may be off by.
  const before = await read();
  const { now } = (await (await page.request.get("/__e2e/now")).json()) as { now: number };
  const first = await read();
  expect(now).toBeGreaterThan(before - 1000);
  expect(now).toBeLessThan(first + 1000);
  expect(new Date(now).toISOString().slice(0, 10)).toBe("2026-10-21");
  await expect.poll(async () => (await read()) - first, { message: "the page's clock ticks" }).toBeGreaterThan(0);
});
