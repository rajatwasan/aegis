import { expect, test } from "@playwright/test";
import {
  API_URL,
  SHOT_DIR,
  escalateLargeTransfer,
  signInAsDevApprover,
} from "./support";

const PHONE = { width: 430, height: 932 };
const DESKTOP = { width: 1440, height: 900 };

/**
 * The phone flow on the real stack, with a real WebAuthn ceremony: Chromium's
 * virtual authenticator (CDP) plays the platform passkey, so the server runs
 * its actual registration and assertion verification. The signed in approver
 * mints a pairing code in the console, the phone enrolls with it, and a
 * decision made with the passkey resolves as that same approver with the
 * assertion embedded in the signed audit record (W10).
 */
test("pair a phone -> passkey approval -> human presence in the audit record", async ({
  page,
  request,
}) => {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });

  await signInAsDevApprover(page);
  const decisionId = await escalateLargeTransfer(page);

  // --- the signed in approver mints a pairing code
  await page.getByRole("button", { name: "pair phone" }).click();
  const code = await page.getByTestId("pairing-code-value").innerText();
  expect(code).toMatch(/^[A-Z2-9]{6}$/);

  // --- the "phone" enrolls a passkey with it and sees the queue as that approver
  await page.setViewportSize(PHONE);
  await page.goto("/guardian");
  await page.getByLabel("pairing code").fill(code);
  await page.getByRole("button", { name: "Pair with passkey" }).click();
  const card = page.getByTestId(`guardian-${decisionId}`);
  await expect(card).toContainText("50,000");
  await expect(page.getByTestId("guardian-identity")).toContainText(
    "signing as Dev approver",
  );
  await page.screenshot({ path: `${SHOT_DIR}/guardian.png` });

  // --- approve with the passkey; the card leaves the queue (optimistically,
  // so the server's own answer is what settles the outcome below)
  await card.getByLabel(`comment for ${decisionId}`).fill("approved from the phone");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card).toHaveCount(0);
  await page.setViewportSize(DESKTOP);

  // --- the decision resolved as the bound approver, by passkey
  const fetchRow = async () => (await request.get(`${API_URL}/proposals/${decisionId}`)).json();
  await expect.poll(async () => (await fetchRow()).status).toBe("approved");
  const row = await fetchRow();
  expect(row.resolution.approvers).toEqual(["dev"]);
  expect(row.resolution.auth_methods).toEqual(["passkey"]);
  expect(row.human_presence.credential_id).toBeTruthy();

  // --- and the signed audit record carries the presence evidence, still proving
  const anchored = await request.post(`${API_URL}/anchor`);
  expect(anchored.ok()).toBeTruthy();
  await page.goto(`/audit/${decisionId}`);
  await expect(page.getByTestId("human-presence")).toContainText(
    "human presence: passkey verified",
  );
  await page.getByRole("button", { name: "Verify against chain" }).click();
  await expect(page.getByTestId("verify-panel")).toContainText("PROOF OK");
});
