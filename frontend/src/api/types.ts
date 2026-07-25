import type { components } from "./schema";

/** Generated schema aliases — the vocabulary the whole app speaks. */
export type Metrics = components["schemas"]["MetricsResponse"];
export type ChainStatus = components["schemas"]["ChainStatus"];
export type PartyStatus = components["schemas"]["PartyStatus"];
export type AnchorInfo = components["schemas"]["AnchorInfo"];
export type DecisionItem = components["schemas"]["DecisionItem"];
export type DecisionsPage = components["schemas"]["DecisionsPage"];
export type AuditRecordItem = components["schemas"]["AuditRecordItem"];
export type AuditRecordsPage = components["schemas"]["AuditRecordsPage"];
export type AuditRecordDetail = components["schemas"]["AuditRecordDetail"];
export type VerifyResponse = components["schemas"]["VerifyResponse"];
export type PolicyResponse = components["schemas"]["PolicyResponse"];
export type PolicyRuleView = components["schemas"]["PolicyRuleView"];
export type CannedInstruction = components["schemas"]["CannedInstruction"];
export type AgentRunResponse = components["schemas"]["AgentRunResponse"];

/**
 * The approval service predates the typed read models and returns free-form
 * objects; these interfaces pin down the shape its store actually produces
 * (see aegis.approval.app._public). Narrowed at the fetch boundary.
 */
export interface ProposalPayload {
  operation: number;
  token: string;
  from: string;
  to: string;
  asset_class: number;
  amount: number;
  requester?: string;
  policy_result?: {
    effect?: string;
    matched_rules?: string[];
    policy_hash?: string;
  };
}

export interface ApprovalEntry {
  approver: string;
  comment: string;
  ts: number;
}

/** Passkey evidence embedded in a record at decide time (never re-verified). */
export interface HumanPresence {
  credential_id: string;
  sign_count: number;
  signature: string;
  authenticator_data: string;
  client_data_json: string;
}

export function asHumanPresence(value: unknown): HumanPresence | null {
  if (
    typeof value === "object" &&
    value !== null &&
    "credential_id" in value &&
    typeof (value as { credential_id: unknown }).credential_id === "string"
  ) {
    return value as HumanPresence;
  }
  return null;
}

export interface ProposalRow {
  decision_id: string;
  status: "pending" | "approved" | "rejected" | "expired";
  proposal: ProposalPayload;
  approvals: ApprovalEntry[];
  resolution: Record<string, unknown> | null;
  authorization: Record<string, unknown> | null;
  signature: string | null;
  created_at: number;
  expires_at: number;
  human_presence?: HumanPresence | null;
}

export function asProposalRow(value: unknown): ProposalRow {
  return value as ProposalRow;
}

export function asProposalRows(value: unknown): ProposalRow[] {
  return (value as ProposalRow[]) ?? [];
}
