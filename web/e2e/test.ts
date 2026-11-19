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

/** What the app at `baseURL` is waiting for a restart for ("code" when its own files changed while it ran); none when it waits for none. */
export async function waitingForRestart(baseURL: string): Promise<string[]> {
  const answer = await fetch(new URL("/__e2e/now", baseURL));
  return ((await answer.json()) as { restart_for?: string[] }).restart_for ?? [];
}

export const test = base.extend<{ restartSaid: void }>({
  context: async ({ context, baseURL }, use) => {
    await followServer(context, baseURL);
    await use(context);
  },
  // An app whose own files or settings changed while it ran holds its background work for a restart (it reads no source and starts
  // no run), and a test then fails on a wait that never ends. A failed test says so, so the hold is not hunted as a fault of the app.
  restartSaid: [
    async ({ baseURL }, use, testInfo) => {
      await use();
      if (!baseURL || testInfo.status === testInfo.expectedStatus) return;
      const waiting = await waitingForRestart(baseURL).catch(() => []);
      if (!waiting.length) return;
      const said = `the app under test was waiting for a restart (${waiting.join(", ")} changed while it ran): its background work was held, so this failure may be that hold. Run it again with nothing changing under the app.`;
      testInfo.annotations.push({ type: "held for a restart", description: said });
      console.error(`[${testInfo.project.name}] ${testInfo.title}: ${said}`);
    },
    { auto: true },
  ],
});
