"""FastAPI human-in-the-loop approval service.

Escalated proposals arrive here, wait for a human (or two, in dual-control
mode), and on approval receive a guardian EIP-712 signature the agent can
submit on-chain. Every resolution is written to the audit log.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from aegis.approval import store as st
from aegis.approval.config import ApprovalConfig
from aegis.approval.page import APPROVAL_PAGE
from aegis.approval.signer import GuardianSigner, authorization_to_json, build_authorization
from aegis.approval.store import ProposalStore
from aegis.audit import AuditLog, AuditSigner
from aegis.events import EmittingAuditLog, EventBus
from aegis.policy import load_policy


class ProposalIn(BaseModel):
    operation: int = Field(ge=1, le=4)
    token: str
    from_addr: str = Field(alias="from")
    to: str
    asset_class: int = 0
    amount: int = Field(ge=0)
    requester: str = "agent"
    policy_result: dict[str, Any] = {}

    model_config = {"populate_by_name": True}


class ActionIn(BaseModel):
    approver: str
    comment: str = ""


def create_app(config: ApprovalConfig | None = None, bus: EventBus | None = None) -> FastAPI:
    config = config or ApprovalConfig.from_env()
    config.ensure_dirs()

    app = FastAPI(title="Aegis approval service")
    app.state.config = config
    app.state.store = ProposalStore(config.db_path)
    app.state.signer = GuardianSigner(config.guardian_key, config.chain_id)
    audit_signer = AuditSigner.load_or_create(config.audit_key_file)
    app.state.audit = (
        EmittingAuditLog(config.audit_log_path, audit_signer, bus)
        if bus is not None
        else AuditLog(config.audit_log_path, audit_signer)
    )
    app.state.policy = load_policy(config.policy_path)
    app.state.bus = bus

    def _emit(event_type: str, row: dict[str, Any]) -> None:
        if bus is not None:
            bus.publish(event_type, _public(row))

    def sweep() -> None:
        for row in app.state.store.expire_older_than(time.time()):
            _write_audit(row, {"action": "expired", "approver": None, "comment": "ttl"})
            _emit("proposal.expired", row)

    def _write_audit(row: dict[str, Any], human_action: dict[str, Any]) -> None:
        app.state.audit.append(
            actor="approval-service",
            proposal=row["proposal"],
            policy_result=row["proposal"].get("policy_result", {}),
            human_action=human_action,
            decision_id=row["decision_id"],
        )

    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "decision_id": row["decision_id"],
            "status": row["status"],
            "proposal": row["proposal"],
            "approvals": row["approvals"],
            "resolution": row["resolution"],
            "authorization": row["authorization"],
            "signature": row["signature"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return APPROVAL_PAGE

    @app.post("/proposals", status_code=201)
    def submit(
        body: ProposalIn,
        response: Response,
        idempotency_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        sweep()
        row, created = app.state.store.create(
            body.model_dump(by_alias=True), config.ttl_seconds, idempotency_key
        )
        if not created:
            response.status_code = 200
        else:
            _emit("proposal.created", row)
        return _public(row)

    @app.get("/proposals")
    def list_proposals(status: str | None = None) -> list[dict[str, Any]]:
        sweep()
        return [_public(r) for r in app.state.store.list(status)]

    @app.get("/proposals/{decision_id}")
    def get_proposal(decision_id: str) -> dict[str, Any]:
        sweep()
        row = app.state.store.get(decision_id)
        if row is None:
            raise HTTPException(404, "unknown decision id")
        return _public(row)

    @app.post("/proposals/{decision_id}/approve")
    def approve(decision_id: str, body: ActionIn) -> dict[str, Any]:
        sweep()
        row = _pending_or_409(decision_id)
        if any(a["approver"] == body.approver for a in row["approvals"]):
            raise HTTPException(409, "approver already recorded for this proposal")
        row = app.state.store.add_approval(decision_id, body.approver, body.comment)

        required = 2 if config.dual_control else 1
        if len(row["approvals"]) < required:
            return _public(row)  # stays pending, waiting for the second approver

        prop = row["proposal"]
        nonce = app.state.store.next_nonce()
        authorization = build_authorization(
            decision_id=decision_id,
            operation=prop["operation"],
            token=prop["token"],
            from_addr=prop["from"],
            to=prop["to"],
            asset_class=prop.get("asset_class", 0),
            amount=prop["amount"],
            policy_hash=app.state.policy.policy_hash,
            nonce=nonce,
            deadline=int(time.time()) + config.auth_deadline_seconds,
        )
        signature = app.state.signer.sign_authorization(authorization)
        resolution = {
            "action": "approved",
            "approvers": [a["approver"] for a in row["approvals"]],
            "comment": body.comment,
        }
        row = app.state.store.resolve(
            decision_id,
            st.APPROVED,
            resolution,
            authorization=authorization_to_json(authorization),
            signature=signature,
            nonce=nonce,
        )
        _write_audit(row, resolution)
        _emit("proposal.approved", row)
        return _public(row)

    @app.post("/proposals/{decision_id}/reject")
    def reject(decision_id: str, body: ActionIn) -> dict[str, Any]:
        sweep()
        _pending_or_409(decision_id)
        resolution = {"action": "rejected", "approver": body.approver, "comment": body.comment}
        row = app.state.store.resolve(decision_id, st.REJECTED, resolution)
        _write_audit(row, resolution)
        _emit("proposal.rejected", row)
        return _public(row)

    def _pending_or_409(decision_id: str) -> dict[str, Any]:
        row = app.state.store.get(decision_id)
        if row is None:
            raise HTTPException(404, "unknown decision id")
        if row["status"] != st.PENDING:
            raise HTTPException(409, f"proposal is {row['status']}, not pending")
        return row

    return app
