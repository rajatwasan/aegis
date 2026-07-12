import { expect, test } from "@playwright/test";

const API_URL = "http://127.0.0.1:8000";
const SHOT = { dir: "../docs/screenshots" };

/**
 * The whole story on the real stack: a canned instruction runs the agent,
 * the policy escalates, a human approves in the console, the transfer
 * executes, and the audit record verifies against the on-chain anchor.
 */
test("canned instruction -> escalation -> approval -> executed -> PROOF OK", async ({
  page,
  request,
}) => {
  // --- console: identity + canned instruction
  await page.goto("/console");
  await page.getByPlaceholder("your name").fill("playwright");
  await page
    .getByRole("button", { name: "Send 50,000 AGD to the treasury desk" })
    .click();

  // steps stream in until the gate escalates
  const steps = page.getByTestId("console-steps");
  await expect(steps).toContainText("steps planned");
  await expect(steps).toContainText("awaits a human");

  // the escalation appears on the right with the amount
  const card = page.locator('[data-testid^="escalation-"]');
  await expect(card).toContainText("50,000");
  const decisionId = (await card.getAttribute("data-testid"))!.replace(
    "escalation-",
    "",
  );

  // --- approvals queue shows the same proposal (screenshot with drawer open)
  await page.goto("/approvals");
  const row = page.getByTestId(`proposal-${decisionId}`);
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByRole("dialog")).toContainText("escalate-large-transfer");
  await expect(page.getByRole("dialog")).toContainText("compliant");
  await page.screenshot({ path: `${SHOT.dir}/approvals.png` });
  await page.keyboard.press("Escape");

  // --- back in the console, approve inline and watch the loop close
  await page.goto("/console");
  await expect(card).toBeVisible();
  await card.getByRole("textbox").fill("looks right, approved in e2e");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(steps).toContainText("human approved — resuming");
  await expect(steps).toContainText("run complete");
  await page.screenshot({ path: `${SHOT.dir}/console.png` });

  // --- anchor the audit log, then verify the decision from the UI
  const anchored = await request.post(`${API_URL}/anchor`);
  expect(anchored.ok()).toBeTruthy();

  await page.goto(`/audit/${decisionId}`);
  await page.getByRole("button", { name: "Verify against chain" }).click();
  const panel = page.getByTestId("verify-panel");
  await expect(panel).toContainText("PROOF OK");
  await expect(panel).toContainText("roots match");
  await page.screenshot({ path: `${SHOT.dir}/audit-verify.png` });

  // --- dashboard reflects the run
  await page.goto("/");
  await expect(page.getByText("total decisions")).toBeVisible();
  await expect(page.getByTestId("effect-bar")).toBeVisible();
  await expect(page.getByText(/batch #\d+/)).toBeVisible();
  await page.screenshot({ path: `${SHOT.dir}/dashboard.png` });
});
