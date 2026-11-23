// What waits to go out, in Follow-ups' To send tab, end to end (design 6.12, 7.4): a message drafted to a known person on the core's stand-in channel waits
// for the person's yes. The person opens the screen, reads the exact content and who it goes to, acknowledges the recipient
// called out, chooses Approve and send, confirms, and the message is handed to the channel exactly as shown. The project has a
// server of its own (`--fake-channel`), which says what the channel was handed.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";
import { checkAccessibility, collectProblems } from "./journey-helpers";

interface Outgoing {
  enabled: boolean;
  name: string;
  address: string;
  subject: string;
  body: string;
  delivered: Array<{ parts: Record<string, string>; to: string[] }>;
}

async function signIn(page: Page) {
  await openScreen(page);
}

const handed = async (page: Page): Promise<Outgoing> => (await page.request.get("/__e2e/delivered")).json();

test.describe("To send", () => {
  test("a message is approved and sent as shown: the content, the target, the recipient acknowledged, a confirm, then the channel has it", async ({ page }) => {
    const problems: string[] = [];
    collectProblems(page, problems);
    const first = await handed(page);
    expect(first.enabled).toBe(true);
    expect(first.delivered).toEqual([]);

    await signIn(page);
    // The side menu has no entry of its own for it: it is a tab of Follow-ups, and the old address lands there.
    await expect(page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: /^Waiting to go out/ })).toHaveCount(0);
    await page.goto("?token=e2e-token#work/outgoing");
    await expect(page.getByRole("heading", { level: 1, name: "Follow-ups" })).toBeVisible();
    await expect(page.getByRole("button", { name: "To send", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(new URL(page.url()).hash).toBe("#work/followups");

    // One line for the message, with its state in words, and its detail beside it with the exact content and the target.
    const line = page.getByRole("list", { name: "Waiting to go out" }).getByRole("listitem");
    await expect(line).toHaveCount(1);
    await expect(line).toContainText(`Message to ${first.name}`);
    await expect(line).toContainText("To approve");
    const pane = page.getByRole("complementary", { name: `Message to ${first.name}` });
    await expect(pane).toContainText(first.subject);
    await expect(pane).toContainText(first.body);
    await expect(pane).toContainText(`${first.name}, ${first.address}`);

    // A recipient never written to is called out: Approve and send waits for the acknowledgement by name.
    const send = pane.getByRole("button", { name: "Approve and send" });
    await expect(send).toBeDisabled();
    await pane.getByRole("checkbox", { name: new RegExp(`I know about ${first.name}`) }).check();
    await expect(send).toBeEnabled();
    await checkAccessibility(page);

    // A send confirms, in words, before anything leaves.
    await send.click();
    const dialog = page.getByRole("dialog", { name: `Send this message to ${first.name} now?` });
    await expect(dialog).toBeVisible();
    expect((await handed(page)).delivered).toEqual([]);
    await dialog.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText(`Sent the message to ${first.name}.`)).toBeVisible();
    await expect(page.getByRole("list", { name: "Waiting to go out" })).toHaveCount(0);

    // The channel was handed exactly what was shown, once.
    const after = await handed(page);
    expect(after.delivered).toHaveLength(1);
    expect(after.delivered[0].to).toEqual([first.address]);
    expect(after.delivered[0].parts).toEqual({ subject: first.subject, body: first.body });
    expect(problems).toEqual([]);
  });

  test("a message that credits the assistant waits, and Reword clears it", async ({ page }) => {
    const problems: string[] = [];
    collectProblems(page, problems);
    await signIn(page);
    const drafted = await (await page.request.post("/__e2e/draft-crediting")).json();
    expect(drafted.enabled).toBe(true);
    await page.goto("?token=e2e-token#work/followups");
    await page.getByRole("button", { name: "To send", exact: true }).click();
    await expect(page.getByRole("list", { name: "Waiting to go out" }).getByRole("listitem").first()).toBeVisible();
    const pane = page.getByRole("complementary", { name: `Message to ${drafted.person}` });

    // It is held, with the two ways on: Reword, or the name is a person. Nothing can be approved meanwhile.
    await expect(pane).toContainText(`credits ${drafted.assistant}`);
    await expect(pane.getByRole("button", { name: "Approve and send" })).toBeDisabled();
    await pane.getByRole("button", { name: "Reword" }).click();
    await expect(pane.getByLabel("Subject")).toBeFocused(); // a form puts the cursor in its first field
    await pane.getByLabel("Message", { exact: true }).fill("The date moved to Tuesday.");
    await pane.getByRole("button", { name: "Save wording" }).click();
    await expect(pane).not.toContainText(`credits ${drafted.assistant}`);
    await expect(pane.getByRole("button", { name: "Approve and send" })).toBeEnabled();
    await checkAccessibility(page);
    expect((await handed(page)).delivered).toHaveLength(1); // only the first message went; this one waits for the yes
    expect(problems).toEqual([]);
  });
});
