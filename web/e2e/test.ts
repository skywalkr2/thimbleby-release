// The `test` every spec uses: Playwright's own, with each browser context's clock following its project's server. When a context
// opens it asks the server for its moment (`/__e2e/now`, a route only the test servers have) and shifts the page's `Date` by the
// difference from the machine's clock, so a page reads the day and hour its server reads however long the run has been going; then
// both tick in real time. (A clock held still would give two reads of `Date.now()` the same value, which the app uses to tell one
// request from the next and to age a toast; a shift fixed at the start of the run drifts from each server's, which starts when it does.)
// A spec that makes its own context calls `followServer`.
import { test as base, type BrowserContext } from "@playwright/test";

export { expect } from "@playwright/test";

/** The server's own moment now, in milliseconds. */
export async function serverNow(baseURL: string): Promise<number> {
  const answer = await fetch(new URL("/__e2e/now", baseURL));
  return ((await answer.json()) as { now: number }).now;
}

/** Sets the context's pages to the moment of the server at `baseURL`, then lets the page's clock run at its own speed. */
export async function followServer(context: BrowserContext, baseURL: string | undefined): Promise<void> {
  if (!baseURL) return;
  const asked = Date.now();
  const shift = (await serverNow(baseURL)) - asked;
  await context.addInitScript((by: number) => {
    const Real = Date;
    const now = () => Real.now() + by;
    window.Date = new Proxy(Real, {
      construct: (target, args, newTarget) => (args.length === 0 ? new target(now()) : Reflect.construct(target, args, newTarget)),
      get: (target, key, receiver) => (key === "now" ? now : Reflect.get(target, key, receiver)),
    });
  }, shift);
}

export const test = base.extend({
  context: async ({ context, baseURL }, use) => {
    await followServer(context, baseURL);
    await use(context);
  },
});
