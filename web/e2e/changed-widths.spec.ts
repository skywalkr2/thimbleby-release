// What changed at the laptop widths (design 7.13): the side menu is the icon rail from 1024px to 1279px, a change's detail is
// chosen on arrival only where it stands beside the list and does not cover it, a change not yet checked has Looks good on its
// own line, and a long title is cut by its row's width (two lines, then an ellipsis), never by a count of characters.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";

const LOADED = { timeout: 20_000 };
const LONG =
  "Confirm the seating plan for the launch dinner with the venue manager and the caterers before the invitations go out";

const change = (n: number, state: "review" | "done") => ({
  id: `REQ-${n}`,
  version: 1,
  state,
  created_at: "2026-10-30T09:00:00Z",
  dismissed: false,
  first_go: false,
  stage_task: false,
  refused: false,
  waiting: null,
  note: null,
  source: null,
  source_title: `${LONG} (${n})`,
  changeset: {
    id: `CS-${n}`,
    summary: "",
    status: "applied",
    reviewed: state === "done",
    trust: "trusted",
    ops: [
      {
        index: 0,
        op: "fact",
        status: "applied",
        reason: null,
        group: "op0",
        title: `A fact ${n}`,
        meta: { owners: [] },
        evidence: null,
        record: { kind: "fact", id: `FACT-${n}` },
        ask: null,
      },
    ],
  },
});

async function open(page: Page, width: number) {
  await page.route("**/api/changes", (route) =>
    route.fulfill({
      json: [change(1, "review"), change(2, "done"), change(3, "review")],
    }),
  );
  await page.setViewportSize({ width, height: 800 });
  await page.goto("?token=e2e-token");
  await page.evaluate(() => {
    window.location.hash = "work/changed";
  });
  await expect(
    page.getByRole("heading", { level: 1, name: "What changed" }),
  ).toBeVisible(LOADED);
  await expect(
    page.locator("[data-row-list]:not([data-detail]) > li[data-row]"),
  ).toHaveCount(3, LOADED);
}

test("What changed at 1440, 1280 and 1024px: the menu, the detail on arrival, Looks good on the row, titles cut by the row's width", async ({
  page,
}) => {
  for (const width of [1440, 1280, 1024]) {
    await page.unrouteAll();
    await open(page, width);
    const nav = await page
      .getByRole("navigation", { name: "Views" })
      .boundingBox();
    const list = await page
      .locator("[data-row-list]:not([data-detail])")
      .first()
      .boundingBox();
    const pane = page.locator("aside[data-detail-pane]");
    if (width >= 1280)
      expect(nav!.width, `the labelled menu at ${width}px`).toBeGreaterThan(
        200,
      );
    else expect(nav!.width, `the icon rail at ${width}px`).toBeLessThan(80);
    if (width === 1024) {
      // Nothing covers the list on arrival; a line the person picks opens its detail.
      await expect(pane).toHaveCount(0);
      expect(list!.width, "the list keeps its width at 1024px").toBeGreaterThan(
        560,
      );
    } else {
      await expect(pane).toBeVisible(LOADED);
      const box = (await pane.boundingBox())!;
      // Beside the list, never over it.
      expect(box.x).toBeGreaterThanOrEqual(list!.x + list!.width - 1);
    }
    // Looks good is on each row not yet checked, and on the filed one it is not.
    const rows = page.locator(
      "[data-row-list]:not([data-detail]) > li[data-row]",
    );
    await expect(
      rows.nth(0).getByRole("button", { name: "Looks good" }),
    ).toBeVisible();
    await expect(
      rows.nth(1).getByRole("button", { name: "Looks good" }),
    ).toHaveCount(0);
    await expect(
      rows.nth(2).getByRole("button", { name: "Looks good" }),
    ).toBeVisible();
    // The title is whole in the page (the row cuts it by its width), and the row does not scroll sideways.
    const title = rows.nth(0).locator("[id^='t-']").first();
    expect(await title.textContent()).toContain(
      "before the invitations go out",
    );
    const reach = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - window.innerWidth,
      rows: Math.max(
        ...Array.from(
          document.querySelectorAll("[data-row-list]:not([data-detail]) > li"),
        ).map((e) => e.scrollWidth - e.clientWidth),
      ),
    }));
    expect(reach.page).toBeLessThanOrEqual(0);
    expect(reach.rows).toBeLessThanOrEqual(1);
  }
});
