"""Passkey endpoints mounted on the existing approval app.

Pairing enrolls a guardian passkey against a short-lived 6-char code.
Deciding verifies that the passkey asserted over the exact decision —
challenge = ``sha256(decision_id || canonical_json(proposal))`` — then routes
into the existing approve/reject endpoints unchanged, with the verified
assertion returned to the caller and stashed on the proposal row.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from aegis.approval import store as st
from aegis.approval.app import ActionIn
from aegis.approval.auth import Principal, require_admin
from aegis.guardian_touch.challenge import decision_challenge, pairing_challenge
from aegis.guardian_touch.config import GuardianTouchConfig
from aegis.guardian_touch.store import GuardianStore

ADMIN = Depends(require_admin)

# uppercase, minus lookalikes (0/O, 1/I/L)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


class PairStartOut(BaseModel):
    code: str


class PairOptionsIn(BaseModel):
    code: str


class PairCompleteIn(BaseModel):
    code: str
    credential: dict[str, Any]


class PairCompleteOut(BaseModel):
    credential_id: str
    sign_count: int


class DecideIn(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = ""
    credential: dict[str, Any]


def mount_guardian_touch(app: FastAPI, config: GuardianTouchConfig | None = None) -> None:
    """Add the /guardian/* passkey routes to an approval-service app."""
    config = config or GuardianTouchConfig.from_env(app.state.config.chain_id)
    store = GuardianStore(app.state.config.db_path)
    app.state.guardian_config = config
    app.state.guardian_store = store

    def _endpoint(path: str) -> Any:
        return next(r.endpoint for r in app.routes if getattr(r, "path", None) == path)

    # the existing approve/reject logic, invoked exactly as HTTP would
    approve = _endpoint("/proposals/{decision_id}/approve")
    reject = _endpoint("/proposals/{decision_id}/reject")

    def _live_code(code: str) -> None:
        row = store.get_pairing_code(code)
        if row is None:
            raise HTTPException(404, "unknown pairing code")
        if row["used"]:
            raise HTTPException(409, "pairing code already used")
        if row["expires_at"] <= time.time():
            raise HTTPException(410, "pairing code expired")

    @app.post("/guardian/pair/start", response_model=PairStartOut)
    def pair_start(_: None = ADMIN) -> PairStartOut:
        """Mint a single use pairing code. Operator only (admin bearer token):
        an open pairing endpoint would let anyone enrol a passkey and approve."""
        for _ in range(5):  # codes are PKs and never deleted, so retry collisions
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
            try:
                store.create_pairing_code(code, config.pairing_ttl_seconds)
            except sqlite3.IntegrityError:
                continue
            return PairStartOut(code=code)
        raise HTTPException(500, "could not allocate a pairing code")

    @app.post("/guardian/pair/options")
    def pair_options(body: PairOptionsIn) -> dict[str, Any]:
        code = body.code.upper()
        _live_code(code)
        options = generate_registration_options(
            rp_id=config.rp_id,
            rp_name=config.rp_name,
            user_id=code.encode(),
            user_name="guardian",
            challenge=pairing_challenge(code),
        )
        return json.loads(options_to_json(options))

    @app.post("/guardian/pair/complete", response_model=PairCompleteOut)
    def pair_complete(body: PairCompleteIn) -> PairCompleteOut:
        code = body.code.upper()
        _live_code(code)
        try:
            verification = verify_registration_response(
                credential=body.credential,
                expected_challenge=pairing_challenge(code),
                expected_origin=config.expected_origin,
                expected_rp_id=config.rp_id,
            )
        except WebAuthnException as exc:
            raise HTTPException(400, f"registration verification failed: {exc}") from exc
        credential_id = bytes_to_base64url(verification.credential_id)
        store.add_credential(
            credential_id, verification.credential_public_key, verification.sign_count
        )
        store.mark_code_used(code)
        return PairCompleteOut(credential_id=credential_id, sign_count=verification.sign_count)

    @app.post("/guardian/auth-options/{proposal_id}")
    def auth_options(proposal_id: str) -> dict[str, Any]:
        row = app.state.store.get(proposal_id)
        if row is None:
            raise HTTPException(404, "unknown decision id")
        credentials = store.list_credentials()
        if not credentials:
            raise HTTPException(409, "no guardian passkey paired")
        options = generate_authentication_options(
            rp_id=config.rp_id,
            challenge=decision_challenge(proposal_id, row["proposal"]),
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]))
                for c in credentials
            ],
        )
        return json.loads(options_to_json(options))

    @app.post("/guardian/decide/{proposal_id}")
    def decide(proposal_id: str, body: DecideIn) -> dict[str, Any]:
        row = app.state.store.get(proposal_id)
        if row is None:
            raise HTTPException(404, "unknown decision id")
        if row["status"] != st.PENDING:
            raise HTTPException(409, f"proposal is {row['status']}, not pending")
        credential_id = body.credential.get("id") or body.credential.get("rawId")
        if not isinstance(credential_id, str):
            raise HTTPException(400, "credential id missing")
        stored = store.get_credential(credential_id)
        if stored is None:
            raise HTTPException(404, "unknown credential")
        try:
            verification = verify_authentication_response(
                credential=body.credential,
                expected_challenge=decision_challenge(proposal_id, row["proposal"]),
                expected_origin=config.expected_origin,
                expected_rp_id=config.rp_id,
                credential_public_key=stored["public_key"],
                credential_current_sign_count=stored["sign_count"],
            )
        except WebAuthnException as exc:
            raise HTTPException(400, f"assertion verification failed: {exc}") from exc
        store.update_sign_count(credential_id, verification.new_sign_count)

        response = body.credential.get("response") or {}
        assertion = {
            "credential_id": credential_id,
            "signature": response.get("signature"),
            "authenticator_data": response.get("authenticatorData"),
            "client_data_json": response.get("clientDataJSON"),
            "sign_count": verification.new_sign_count,
        }
        # stash BEFORE routing: the audit record written inside approve/reject
        # embeds this as human_presence, hashed and signed with the payload
        store.set_proposal_assertion(proposal_id, json.dumps(assertion))
        # the verified assertion IS the credential: the principal comes from it
        principal = Principal(id=f"passkey:{credential_id[:8]}", auth="passkey")
        action = ActionIn(comment=body.comment)
        result = (
            approve(proposal_id, action, principal)
            if body.action == "approve"
            else reject(proposal_id, action, principal)
        )
        return {**result, "passkey_assertion": assertion}
