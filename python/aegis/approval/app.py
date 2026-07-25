"""FastAPI human-in-the-loop approval service.

Escalated proposals arrive here, wait for a human (or two, in dual-control
mode), and on approval receive a guardian EIP-712 signature the agent can
submit on-chain. Every resolution is written to the audit log.

Who approved is never taken from the request body. Approve and reject require
an approver credential (``Authorization: Bearer <token>``), the identity is
resolved server side (:mod:`aegis.approval.identity`), and every path that
resolves a decision goes through :func:`resolve_decision` so there is exactly
one place that records an approval, signs an authorization and writes the
audit record (AGENTS.md C4, C6, I2; spec W2, decision D1).
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from aegis.approval import store as st
from aegis.approval.config import ApprovalConfig
from aegis.approval.identity import Approver, Unauthenticated, resolve_approver
from aegis.approval.page import APPROVAL_PAGE
from aegis.approval.signer import GuardianSigner, authorization_to_json, build_authorization
from aegis.approval.store import ProposalStore
from aegis.audit import AuditLog, AuditSigner
from aegis.events import EmittingAuditLog, EventBus
from aegis.policy import load_policy

Action = Literal["approve", "reject"]


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
    """Body of approve and reject: the comment, and nothing else.

    ``extra="forbid"`` so a client that still sends ``approver`` (the pre W2
    shape) gets a 422 naming the field instead of being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    comment: str = ""


class ApproverOut(BaseModel):
    id: str
    display_name: str
    auth_method: str


def require_approver(
    request: Request, authorization: str | None = Header(default=None)
) -> Approver:
    """FastAPI dependency: the authenticated approver, or 401 before any work (C4)."""
    try:
        return resolve_approver(request.app.state.store, authorization)
    except Unauthenticated as exc:
        raise HTTPException(
            401, str(exc), headers={"WWW-Authenticate": 'Bearer realm="aegis-approvals"'}
        ) from exc


AuthedApprover = Annotated[Approver, Depends(require_approver)]


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
            human_presence=_human_presence(row),
        )

    def _human_presence(row: dict[str, Any]) -> dict[str, Any] | None:
        """Passkey evidence stashed by /guardian/decide, or None (console path).

        Verified once at decide time — from here on it is evidence, embedded
        in the audit record before hashing/signing so the chain covers it.
        """
        raw = row.get("passkey_assertion")
        if not raw:
            return None
        try:
            assertion = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return None
        fields = (
            "credential_id",
            "sign_count",
            "signature",
            "authenticator_data",
            "client_data_json",
        )
        return {k: assertion.get(k) for k in fields}

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
            "human_presence": _human_presence(row),
        }

    # ------------------------------------------------------------ resolver

    def resolve_decision(
        decision_id: str,
        approver: Approver,
        action: Action,
        comment: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The one code path that records a human decision.

        ``approver`` is an authenticated identity (token today, passkey with
        W10). ``evidence`` is extra verified material (a passkey assertion) that
        is written into the audit record before hashing so the chain covers it.
        """
        sweep()
        row = _pending_or_409(decision_id)
        identity = approver.as_record()

        if action == "reject":
            resolution = {"action": "rejected", **identity, "comment": comment}
            if evidence is not None:
                resolution["evidence"] = evidence
            row = app.state.store.resolve(decision_id, st.REJECTED, resolution)
            _write_audit(row, resolution)
            _emit("proposal.rejected", row)
            return row

        if any(a["approver"] == approver.id for a in row["approvals"]):
            raise HTTPException(409, "approver already recorded for this proposal")
        row = app.state.store.add_approval(decision_id, identity, comment)

        required = 2 if config.dual_control else 1
        if len(row["approvals"]) < required:
            return row  # stays pending, waiting for a second, distinct approver

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
        resolution: dict[str, Any] = {
            "action": "approved",
            "approvers": [a["approver"] for a in row["approvals"]],
            "auth_methods": [a.get("auth_method") for a in row["approvals"]],
            "comment": comment,
        }
        if evidence is not None:
            resolution["evidence"] = evidence
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
        return row

    app.state.resolve_decision = resolve_decision

    # --------------------------------------------------------------- routes

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

    @app.get("/approvers/me", response_model=ApproverOut)
    def whoami(approver: AuthedApprover) -> ApproverOut:
        return ApproverOut(
            id=approver.id, display_name=approver.display_name, auth_method=approver.auth_method
        )

    @app.post("/proposals/{decision_id}/approve")
    def approve(decision_id: str, body: ActionIn, approver: AuthedApprover) -> dict[str, Any]:
        return _public(resolve_decision(decision_id, approver, "approve", body.comment))

    @app.post("/proposals/{decision_id}/reject")
    def reject(decision_id: str, body: ActionIn, approver: AuthedApprover) -> dict[str, Any]:
        return _public(resolve_decision(decision_id, approver, "reject", body.comment))

    def _pending_or_409(decision_id: str) -> dict[str, Any]:
        row = app.state.store.get(decision_id)
        if row is None:
            raise HTTPException(404, "unknown decision id")
        if row["status"] != st.PENDING:
            raise HTTPException(409, f"proposal is {row['status']}, not pending")
        return row

    return app
