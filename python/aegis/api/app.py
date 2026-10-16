"""Guardian Console API: the approval service plus the read/streaming surface.

``create_api_app`` builds the existing approval service (unchanged routes,
now emitting events) and adds on top of it:

* ``GET /events``            — SSE stream of every bus event
* ``GET /decisions``         — paginated policy-gate decisions (audit projection)
* ``GET /audit/records``     — paginated raw audit records
* ``GET /audit/records/{id}``— one record with its chain neighborhood
* ``GET /audit/verify/{id}`` — Merkle inclusion proof against the on-chain root
* ``GET /policy``            — raw yaml, policyHash, human-readable rules
* ``GET /metrics``           — decision counts, escalation rate, last anchor
* ``POST /anchor``           — anchor unanchored records (emits anchor.created)
* ``POST /agent/run``        — background LangGraph agent run (agent.step events)
* ``GET /agent/instructions``— the MockLLM's canned instruction chips
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from aegis import anchoring, chains
from aegis.anchoring import StateError
from aegis.api.agent_runner import AgentRunner, UnknownInstructionError, canned_instructions
from aegis.api.config import ApiConfig, load_chain_state
from aegis.api.describe import describe_rule
from aegis.api.guardian_check import GuardianBinding, verify_guardian_binding
from aegis.api.models import (
    AgentRunRequest,
    AgentRunResponse,
    AnchorInfo,
    AnchorResponse,
    AuditRecordDetail,
    AuditRecordItem,
    AuditRecordsPage,
    CannedInstruction,
    CannedInstructionsResponse,
    ChainStatus,
    DecisionItem,
    DecisionsPage,
    InjectionStats,
    MetricsResponse,
    PartyStatus,
    PolicyResponse,
    PolicyRuleView,
    VerifyResponse,
)
from aegis.approval.app import create_app
from aegis.events import EventBus

_SSE_KEEPALIVE_SECONDS = 15.0


def create_api_app(config: ApiConfig | None = None) -> FastAPI:
    config = config or ApiConfig.from_env()
    bus = EventBus()

    app = create_app(config.approval, bus=bus)
    app.title = "Aegis Guardian Console API"
    app.state.api_config = config
    app.state.runner = AgentRunner(config, bus, app)

    # The signer must be the token's guardian, or nothing this service signs
    # will execute. Checked once here; a mismatch or an unreadable chain stops
    # startup (AGENTS.md C8). With no chain state there is nothing to bind to.
    chain_state = load_chain_state(Path(config.state_dir))
    binding: GuardianBinding | None = None
    if chain_state is not None:
        binding = verify_guardian_binding(chain_state, app.state.signer.address)
    app.state.guardian_binding = binding

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state_dir = Path(config.state_dir)

    # ------------------------------------------------------------------ events

    @app.get("/events")
    async def events() -> StreamingResponse:
        async def stream():
            token, queue = bus.subscribe()
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), _SSE_KEEPALIVE_SECONDS)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                bus.unsubscribe(token)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --------------------------------------------------------------- decisions

    def _decision_view(record: dict[str, Any]) -> DecisionItem:
        policy_result = record.get("policy_result") or {}
        return DecisionItem(
            decision_id=record["decision_id"],
            ts=record["ts"],
            actor=record["actor"],
            effect=policy_result["effect"],
            status=policy_result.get("status"),
            matched_rules=list(policy_result.get("matched_rules") or []),
            tx_hash=policy_result.get("tx_hash"),
            proposal=record.get("proposal") or {},
        )

    @app.get("/decisions", response_model=DecisionsPage)
    def list_decisions(
        limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)
    ) -> DecisionsPage:
        gate_records = [
            r
            for r in app.state.audit.records()
            if r["actor"] == "agent" and (r.get("policy_result") or {}).get("effect")
        ]
        gate_records.reverse()  # newest first
        page = gate_records[offset : offset + limit]
        return DecisionsPage(
            items=[_decision_view(r) for r in page],
            total=len(gate_records),
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------- audit

    def _record_item(record: dict[str, Any], index: int) -> AuditRecordItem:
        return AuditRecordItem(index=index, **record)

    @app.get("/audit/records", response_model=AuditRecordsPage)
    def list_audit_records(
        limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)
    ) -> AuditRecordsPage:
        records = app.state.audit.records()
        indexed = [(i, r) for i, r in enumerate(records)]
        indexed.reverse()  # newest first
        page = indexed[offset : offset + limit]
        return AuditRecordsPage(
            items=[_record_item(r, i) for i, r in page],
            total=len(records),
            limit=limit,
            offset=offset,
        )

    @app.get("/audit/records/{decision_id}", response_model=AuditRecordDetail)
    def get_audit_record(decision_id: str) -> AuditRecordDetail:
        records = app.state.audit.records()
        index = next((i for i, r in enumerate(records) if r["decision_id"] == decision_id), None)
        if index is None:
            raise HTTPException(404, "unknown audit record")
        lo = max(0, index - 2)
        neighbors = [_record_item(records[i], i) for i in range(lo, min(len(records), index + 3))]
        return AuditRecordDetail(
            record=_record_item(records[index], index), total=len(records), neighbors=neighbors
        )

    @app.get("/audit/verify/{decision_id}", response_model=VerifyResponse)
    def verify_audit_record(decision_id: str) -> VerifyResponse:
        try:
            result = anchoring.verify_decision_in_dir(state_dir, decision_id)
        except StateError as exc:
            raise HTTPException(503, str(exc)) from exc
        return VerifyResponse(**result)

    @app.post("/anchor", response_model=AnchorResponse)
    def anchor_records() -> AnchorResponse:
        try:
            batch = anchoring.anchor_unanchored(state_dir)
        except StateError as exc:
            raise HTTPException(503, str(exc)) from exc
        if batch is None:
            return AnchorResponse(anchored=False, batch=_last_anchor())
        state = anchoring.load_state(state_dir)
        info = AnchorInfo(**anchoring.batch_view(state, batch))
        bus.publish("anchor.created", info.model_dump())
        return AnchorResponse(anchored=True, batch=info)

    # ------------------------------------------------------------------ policy

    @app.get("/policy", response_model=PolicyResponse)
    def get_policy() -> PolicyResponse:
        policy = app.state.policy
        raw = Path(config.approval.policy_path).read_text()
        return PolicyResponse(
            yaml=raw,
            policy_hash=policy.policy_hash,
            version=policy.version,
            default=policy.default.value,
            allowlist=sorted(policy.allowlist),
            rules=[
                PolicyRuleView(id=r.id, effect=r.effect.value, condition=describe_rule(r))
                for r in policy.rules
            ],
        )

    # -------------------------------------------------------------- compliance

    @app.get("/compliance/{address}", response_model=PartyStatus)
    def get_party_status(address: str) -> PartyStatus:
        """Registry compliance + freeze standing of one address (F2 drawer)."""
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            raise HTTPException(400, "not an address")
        try:
            runtime = app.state.runner.runtime()
            return PartyStatus(
                address=address,
                known=True,
                compliant=runtime.check_compliance(address),
                frozen=runtime.is_frozen(address),
            )
        except Exception:  # noqa: BLE001 - no chain state / RPC down: unknown, not 500
            return PartyStatus(address=address, known=False)

    # ----------------------------------------------------------------- metrics

    def _chain_status() -> ChainStatus:
        state = load_chain_state(state_dir)
        if state is None:
            return ChainStatus(configured=False, connected=False)
        chain_id: int | None = state.get("chain_id")
        connected = False
        try:
            res = httpx.post(
                state["rpc_url"],
                json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
                timeout=2.0,
            )
            connected = res.status_code == 200
            chain_id = int(res.json()["result"], 16)
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        # the live chain id wins over state.json: it is what anchors land on
        explorer = state.get("explorer_url") or chains.explorer_from_env()
        meta = chains.chain_meta(chain_id, explorer)
        anchor_address = state.get("anchor_address")
        bound: GuardianBinding | None = app.state.guardian_binding
        return ChainStatus(
            configured=True,
            connected=connected,
            rpc_url=chains.redact_rpc_url(state["rpc_url"]),
            chain_id=chain_id,
            chain_name=meta.name,
            public=meta.public,
            explorer_url=meta.explorer_url,
            anchor_address=anchor_address,
            anchor_url=chains.address_url(chain_id, anchor_address, explorer),
            guardian_address=bound.guardian_address if bound else None,
            guardian_verified=bound.verified if bound else False,
        )

    def _last_anchor() -> AnchorInfo | None:
        anchors = anchoring.load_anchors(state_dir)
        if not anchors:
            return None
        state = load_chain_state(state_dir) or {}
        return AnchorInfo(**anchoring.batch_view(state, anchors[-1]))

    @app.get("/metrics", response_model=MetricsResponse)
    def get_metrics() -> MetricsResponse:
        effects = [
            (r.get("policy_result") or {}).get("effect")
            for r in app.state.audit.records()
            if r["actor"] == "agent"
        ]
        effects = [e for e in effects if e]
        counts = {e: effects.count(e) for e in ("allow", "escalate", "deny")}
        total = len(effects)
        pending = len(app.state.store.list("pending"))
        return MetricsResponse(
            total_decisions=total,
            counts_by_effect=counts,
            escalation_rate=(counts["escalate"] / total) if total else 0.0,
            pending_count=pending,
            last_anchor=_last_anchor(),
            injections=parse_eval_report(Path(config.evals_report_path)),
            chain=_chain_status(),
        )

    # ------------------------------------------------------------------- agent

    @app.post("/agent/run", response_model=AgentRunResponse, status_code=202)
    def run_agent(body: AgentRunRequest) -> AgentRunResponse:
        try:
            run = app.state.runner.start(body.instruction)
        except UnknownInstructionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except StateError as exc:
            raise HTTPException(503, str(exc)) from exc
        return AgentRunResponse(run_id=run.run_id, status=run.status, instruction=run.instruction)

    @app.get("/agent/instructions", response_model=CannedInstructionsResponse)
    def get_canned_instructions() -> CannedInstructionsResponse:
        return CannedInstructionsResponse(
            instructions=[CannedInstruction(**c) for c in canned_instructions()]
        )

    return app


def parse_eval_report(path: Path) -> InjectionStats | None:
    """Pull the headline attack/bypass counts out of ``evals/report.md``."""
    if not path.exists():
        return None
    text = path.read_text()
    attacks = re.search(r"attacks \(must not auto-execute\) \| (\d+)", text)
    bypass = re.search(r"bypass rate\*\* \| \*\*[\d.]+%\*\* \((\d+)/(\d+)\)", text)
    if attacks is None or bypass is None:
        return None
    attack_count = int(attacks.group(1))
    bypass_count = int(bypass.group(1))
    return InjectionStats(
        attacks=attack_count, bypasses=bypass_count, blocked=attack_count - bypass_count
    )
