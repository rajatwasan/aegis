import { defineConfig } from "@playwright/test";

/**
 * E2E over the real stack: anvil + deployed contracts + API + vite, all booted
 * (and torn down) by scripts/dev-stack.sh via webServer. Uses the locally
 * installed Chrome (channel) so nothing is downloaded; set AEGIS_E2E_BROWSER
 * to a Chromium binary where Chrome is not installed.
 */
const browser = process.env.AEGIS_E2E_BROWSER
  ? { launchOptions: { executablePath: process.env.AEGIS_E2E_BROWSER } }
  : { channel: "chrome" as const };

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1, // one shared chain + approval store
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    ...browser,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  },
  webServer: {
    command: "bash ../scripts/dev-stack.sh",
    url: "http://localhost:5173",
    reuseExistingServer: false,
    stdout: "ignore",
    stderr: "pipe",
    timeout: 120_000,
  },
});
