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


class AnchorInfo(BaseModel):
    batch_id: int
    root: str
    tx_hash: str | None = None
    record_count: int


class InjectionStats(BaseModel):
    attacks: int
    bypasses: int
    blocked: int


class ChainStatus(BaseModel):
    configured: bool
    connected: bool
    rpc_url: str | None = None
    chain_id: int | None = None


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


class CannedInstruction(BaseModel):
    instruction: str
    description: str


class CannedInstructionsResponse(BaseModel):
    instructions: list[CannedInstruction]
