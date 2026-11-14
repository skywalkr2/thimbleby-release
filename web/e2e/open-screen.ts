// Opening a screen and waiting for it: the app marks its main region `data-ready` (holding the address it is ready at) when the
// screen's first reads have answered and no request is pending (src/lib/ready.ts). A test waits for that mark, with the page-load
// time as its only limit, and never for a number of seconds of its own. A wait that still needs one is a missing ready mark or a
// product fault, and is reported as that.
import type { Page } from "@playwright/test";

/** The most a page is given to load: the machine may be busy, and the limit is for a page that never comes. */
export const PAGE_LOAD = { timeout: 20_000 };

/** Waits until the main region is marked ready at the address the page is on now (so a mark left from the screen before does not count). */
export async function screenReady(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const main = document.getElementById("main");
      return main !== null && main.getAttribute("data-ready") === location.hash;
    },
    undefined,
    PAGE_LOAD,
  );
}

/** Opens a screen by the address after the `#` (none for the first screen) and waits for its ready mark. The token signs the page in,
 * as the harness does; a page already signed in at the same path only moves to the screen. */
export async function openScreen(page: Page, hash = "", token = "e2e-token"): Promise<void> {
  const at = hash.replace(/^#/, "");
  await page.goto(`?token=${token}${at ? `#${at}` : ""}`);
  await screenReady(page);
}
