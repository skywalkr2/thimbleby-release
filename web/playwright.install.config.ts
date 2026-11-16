// The browser test of a fresh install of the built app (S-0459): no server is started here, because the app under
// test is the installed one, already running; the script that runs it (deploy/desktop/build_support/fresh_install_check.py)
// gives its address in FRESH_INSTALL_URL and says which visit this is in FRESH_INSTALL_VISIT.
import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: "./e2e-install",
  testMatch: /fresh-install\.spec\.ts/,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    launchOptions: { executablePath },
    baseURL: process.env.FRESH_INSTALL_URL,
    screenshot: "only-on-failure",
  },
  outputDir: process.env.FRESH_INSTALL_PICTURES || "test-results-fresh-install",
});
