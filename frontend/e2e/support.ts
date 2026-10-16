import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

export const API_URL = "http://127.0.0.1:8000";
export const SHOT_DIR = "../docs/screenshots";

/**
 * The dev stack (scripts/dev-stack.sh -> aegis.devstack) registers approver
 * "dev" and writes its token next to state.json. The human in these tests is
 * that approver: the token goes into the browser, never into the agent (W2).
 * Read inside a test, after Playwright has started the stack.
 */
export function devApproverToken(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return readFileSync(
    resolve(here, "../../.aegis/dev/dev-approver.token"),
    "utf8",
  ).trim();
}

/** Put the approver token in the browser before the app loads. */
export async function signInAsDevApprover(page: Page): Promise<void> {
  await page.addInitScript((token) => {
    window.localStorage.setItem("aegis.approver_token", token);
  }, devApproverToken());
}

/**
 * Run the canned large transfer in the console and return the decision id of
 * the escalation it produces.
 */
export async function escalateLargeTransfer(page: Page): Promise<string> {
  await page.goto("/console");
  await page
    .getByRole("button", { name: "Send 50,000 AGD to the treasury desk" })
    .click();
  const steps = page.getByTestId("console-steps");
  await steps.getByText("awaits a human").waitFor();
  const card = page.locator('[data-testid^="escalation-"]');
  await card.getByText("50,000").waitFor();
  return (await card.getAttribute("data-testid"))!.replace("escalation-", "");
}
