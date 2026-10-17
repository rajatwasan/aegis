/**
 * The approver token the e2e run uses. playwright.config.ts hands it to the
 * dev stack through AEGIS_APPROVER_TOKENS (the stack mints a random one only
 * when none is given), and the spec pastes it into the console's token field,
 * exactly as an operator would.
 */
export const E2E_APPROVER_ID = "e2e";
export const E2E_APPROVER_TOKEN = "e2e-approver-token-00000000000000000000";
