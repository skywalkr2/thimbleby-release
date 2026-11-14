// Batch R2, S-0362: on a workspace with five sides (three with long names) the side picker is not a phone's bottom sheet on a wide
// window, and the narrow side menu (the icon rail) tells each icon apart by a name that shows on hover and on focus.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";

const LOADED = { timeout: 20_000 };

const open = async (page: Page, hash = "today") => {
  await page.goto(`?token=e2e-token#${hash}`);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible(LOADED);
};

test.describe("the side picker and the icon rail (S-0362)", () => {
  test("at 1440 the picker opens as a panel in the middle, never a strip across the window's foot", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "work/handled");
    const opener = page.getByRole("button", { name: /^Side: / }).first();
    await expect(opener).toBeVisible(LOADED);
    await opener.click();
    const dialog = page.getByRole("dialog", { name: "Show one side" });
    await expect(dialog).toBeVisible(LOADED);
    const box = (await dialog.boundingBox())!;
    expect(box.width).toBeLessThanOrEqual(520);
    // Centered, with room on both sides, and not resting on the window's bottom edge.
    expect(box.x).toBeGreaterThan(200);
    expect(box.y + box.height).toBeLessThan(900 - 24);
    // Every side's whole name is there, to pick from.
    await expect(dialog.getByRole("button", { name: /Willowbrook Handmade Ceramics and Garden Supply Cooperative/ })).toBeVisible();
    await page.keyboard.press("Escape");
    // On a phone it is still the sheet from the foot.
    await page.setViewportSize({ width: 390, height: 800 });
    await page.getByRole("button", { name: /^Side: / }).first().click();
    const phone = (await page.locator("[data-modal-open][data-overlay=sheet]").boundingBox())!;
    expect(phone.width).toBeGreaterThanOrEqual(388);
    expect(phone.y + phone.height).toBeGreaterThanOrEqual(800 - 2);
  });

  test("below 1024 each icon of the side menu shows its name when hovered or focused, and the sides are told apart by it", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: 900 });
    await open(page);
    const nav = page.getByRole("navigation", { name: "Views" });
    expect((await nav.boundingBox())!.width).toBeLessThan(80);
    const links = nav.getByRole("link");
    await expect(links.first()).toBeVisible(LOADED);
    const count = await links.count();
    expect(count).toBeGreaterThanOrEqual(8);
    const missing: string[] = [];
    for (let n = 0; n < count; n += 1) {
      const link = links.nth(n);
      // The name is the link's own title (a pointer shows it on hover), and the keyboard's tooltip shows it on focus.
      const name = (await link.locator("xpath=..").getAttribute("title")) ?? "";
      const spans = await link.locator("span").evaluateAll((els) => els.map((e) => (e.textContent ?? "").trim()));
      if (!name || !spans.includes(name)) {
        missing.push(`${spans.join(" / ")} has no title naming it`);
        continue;
      }
      await link.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      if (!(await page.getByRole("tooltip").filter({ hasText: name }).count())) missing.push(`${name} shows no tooltip on focus`);
    }
    expect(missing).toEqual([]);
    // The sides, whose icons are two letters, are told apart by their whole names.
    const sides = ["Willowbrook Handmade Ceramics and Garden Supply Cooperative", "Northfield Mobile Bicycle Repair and Neighborhood Delivery Service"];
    for (const name of sides) await expect(nav.getByRole("link", { name }).locator("xpath=..")).toHaveAttribute("title", name);
  });
});
