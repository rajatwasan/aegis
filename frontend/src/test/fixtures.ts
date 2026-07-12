/** Canonical test data, mirroring the shapes the real API produces. */

import type {
  AuditRecordItem,
  DecisionItem,
  Metrics,
  PolicyResponse,
  ProposalRow,
  VerifyResponse,
} from "../api/types";

export const TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3";
export const OPERATOR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266";
export const ALICE = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8";

export function makeProposal(overrides: Partial<ProposalRow> = {}): ProposalRow {
  const now = Date.now() / 1000;
  return {
    decision_id: "dec-1",
    status: "pending",
    proposal: {
      operation: 1,
      token: TOKEN,
      from: OPERATOR,
      to: ALICE,
      asset_class: 0,
      amount: 50_000,
      policy_result: {
        effect: "escalate",
        matched_rules: ["escalate-large-transfer"],
        policy_hash: "ab".repeat(32),
      },
    },
    approvals: [],
    resolution: null,
    authorization: null,
    signature: null,
    created_at: now - 60,
    expires_at: now + 600,
    ...overrides,
  };
}

export function makeMetrics(overrides: Partial<Metrics> = {}): Metrics {
  return {
    total_decisions: 12,
    counts_by_effect: { allow: 8, escalate: 3, deny: 1 },
    escalation_rate: 0.25,
    pending_count: 2,
    last_anchor: {
      batch_id: 1,
      root: "cd".repeat(32),
      tx_hash: "0x" + "ef".repeat(32),
      record_count: 8,
    },
    injections: { attacks: 49, bypasses: 0, blocked: 49 },
    chain: {
      configured: true,
      connected: true,
      rpc_url: "http://127.0.0.1:8545",
      chain_id: 31337,
    },
    ...overrides,
  };
}

export function makeDecision(overrides: Partial<DecisionItem> = {}): DecisionItem {
  return {
    decision_id: "gate-1",
    ts: new Date(Date.UTC(2026, 6, 12, 9, 30)).toISOString(),
    actor: "agent",
    effect: "allow",
    status: "executed",
    matched_rules: ["allow-small-compliant-transfer"],
    tx_hash: "ab".repeat(32),
    proposal: { operation: 1, token: TOKEN, from: OPERATOR, to: ALICE, amount: 1200 },
    ...overrides,
  };
}

export function makeAuditRecord(
  index: number,
  overrides: Partial<AuditRecordItem> = {},
): AuditRecordItem {
  return {
    index,
    decision_id: `rec-${index}`,
    ts: new Date(Date.UTC(2026, 6, 12, 10, index)).toISOString(),
    actor: "agent",
    proposal: { operation: 1, token: TOKEN, from: OPERATOR, to: ALICE, amount: 1000 },
    policy_result: {
      effect: "allow",
      matched_rules: ["allow-small-compliant-transfer"],
      status: "executed",
    },
    human_action: null,
    prev_hash: index === 0 ? "0".repeat(64) : `${index - 1}`.repeat(1).padEnd(64, "a"),
    record_hash: `${index}`.repeat(1).padEnd(64, "a"),
    signature: "f0".repeat(64),
    ...overrides,
  };
}

export function makeVerifyResponse(
  overrides: Partial<VerifyResponse> = {},
): VerifyResponse {
  return {
    decision_id: "rec-1",
    PROOF_OK: true,
    reason: null,
    record: makeAuditRecord(1) as unknown as Record<string, never>,
    batch_id: 0,
    index: 1,
    merkle_path: ["11".repeat(32), "22".repeat(32)],
    local_root: "33".repeat(32),
    onchain_root: "33".repeat(32),
    ...overrides,
  };
}

export function makePolicy(
  overrides: Partial<PolicyResponse> = {},
): PolicyResponse {
  return {
    yaml: "version: 1\nrules: []\ndefault: escalate\n",
    policy_hash: "ab".repeat(32),
    version: 1,
    default: "escalate",
    allowlist: [ALICE.toLowerCase()],
    rules: [
      {
        id: "deny-frozen-party",
        effect: "deny",
        condition: "a party is frozen",
      },
      {
        id: "escalate-large-transfer",
        effect: "escalate",
        condition: "operation is transfer and amount > 10,000",
      },
    ],
    ...overrides,
  };
}
