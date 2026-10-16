"""Typed response models for the Guardian Console API.

Audit records themselves stay loose dicts (their schema is owned by the audit
module and hashed canonically), but every envelope the frontend consumes is a
pydantic model so the generated TypeScript client is fully typed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DecisionItem(BaseModel):
    """One policy-gate decision, projected from its audit record."""

    decision_id: str
    ts: str
    actor: str
    effect: str
    status: str | None = None
    matched_rules: list[str] = Field(default_factory=list)
    tx_hash: str | None = None
    proposal: dict[str, Any]


class DecisionsPage(BaseModel):
    items: list[DecisionItem]
    total: int
    limit: int
    offset: int


class AuditRecordItem(BaseModel):
    """A raw audit record plus its position in the hash chain."""

    index: int
    decision_id: str
    ts: str
    actor: str
    proposal: dict[str, Any]
    policy_result: dict[str, Any]
    human_action: dict[str, Any] | None = None
    prev_hash: str
    record_hash: str
    signature: str


class AuditRecordsPage(BaseModel):
    items: list[AuditRecordItem]
    total: int
    limit: int
    offset: int


class AuditRecordDetail(BaseModel):
    record: AuditRecordItem
    total: int
    # the surrounding slice of the chain (up to two records each side)
    neighbors: list[AuditRecordItem]


class AnchorInfo(BaseModel):
    """One anchored batch, with the coordinates needed to track it on-chain."""

    batch_id: int
    root: str
    tx_hash: str | None = None
    record_count: int
    chain_id: int | None = None
    chain_name: str | None = None
    block_number: int | None = None
    anchored_at: str | None = None
    #: block-explorer link to the anchoring transaction (None on a dev chain)
    tx_url: str | None = None
    anchor_address: str | None = None
    anchor_url: str | None = None


class VerifyResponse(BaseModel):
    decision_id: str
    proof_ok: bool = Field(alias="PROOF_OK")
    reason: str | None = None
    record: dict[str, Any] | None = None
    batch_id: int | None = None
    index: int | None = None
    merkle_path: list[str] | None = None
    local_root: str | None = None
    onchain_root: str | None = None
    #: the batch that sealed this record, incl. its explorer link (None if
    #: the record has not been anchored yet)
    anchor: AnchorInfo | None = None

    model_config = {"populate_by_name": True}


class PolicyRuleView(BaseModel):
    id: str
    effect: str
    condition: str


class PolicyResponse(BaseModel):
    yaml: str
    policy_hash: str
    version: int
    default: str
    allowlist: list[str]
    rules: list[PolicyRuleView]
    #: the rolling window behind within_daily_limit, read back from the audit log (W4)
    daily_window_seconds: int


class InjectionStats(BaseModel):
    attacks: int
    bypasses: int
    blocked: int


class ChainStatus(BaseModel):
    configured: bool
    connected: bool
    #: path-redacted: hosted RPC providers carry their API key in the path
    rpc_url: str | None = None
    chain_id: int | None = None
    chain_name: str | None = None
    #: False for a dev chain (anvil) — nothing here is externally verifiable
    public: bool | None = None
    explorer_url: str | None = None
    anchor_address: str | None = None
    anchor_url: str | None = None
    #: the token's on chain guardian, read at startup; None until a chain is configured
    guardian_address: str | None = None
    #: True only when the approval service's signer equals guardian_address
    guardian_verified: bool = False


class PartyStatus(BaseModel):
    """On-chain standing of one address, as the policy gate would see it."""

    address: str
    known: bool
    compliant: bool | None = None
    frozen: bool | None = None


class MetricsResponse(BaseModel):
    total_decisions: int
    counts_by_effect: dict[str, int]
    escalation_rate: float
    pending_count: int
    last_anchor: AnchorInfo | None = None
    injections: InjectionStats | None = None
    chain: ChainStatus


class AnchorResponse(BaseModel):
    anchored: bool
    batch: AnchorInfo | None = None


class AgentRunRequest(BaseModel):
    instruction: str


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    instruction: str
    #: which provider drives this run: "mock" (scripted) or "anthropic" (real model)
    mode: str


class CannedInstruction(BaseModel):
    instruction: str
    description: str


class CannedInstructionsResponse(BaseModel):
    #: "mock": only these instructions run, scripted. "anthropic": free text runs
    #: through the real model and these are examples.
    mode: str
    instructions: list[CannedInstruction]
