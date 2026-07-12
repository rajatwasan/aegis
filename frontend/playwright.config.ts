import { defineConfig } from "@playwright/test";

/**
 * E2E smoke over the real stack: anvil + deployed contracts + API + vite,
 * all booted (and torn down) by scripts/dev-stack.sh via webServer.
 * Uses the locally installed Chrome (channel) — no browser downloads.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1, // one shared chain + approval store
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    channel: "chrome",
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
