"""Passkey endpoints mounted on the existing approval app.

A passkey is a second credential of an existing approver, never an identity of
its own. Pairing starts from an authenticated approver (bearer token): the
6 character code it mints is bound to that approver id, and the passkey
enrolled with the code inherits the binding. Deciding verifies that the
passkey asserted over the exact decision (challenge =
``sha256(decision_id || canonical_json(proposal))``), resolves the bound
approver, and hands the verified assertion to :func:`resolve_decision` as
evidence, the same path the console takes (AGENTS.md C4, I2; spec W10,
decision D9).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
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
from aegis.approval.app import AuthedApprover, public_row
from aegis.approval.identity import PASSKEY_AUTH, Approver
from aegis.guardian_touch.challenge import decision_challenge, pairing_challenge
from aegis.guardian_touch.config import GuardianTouchConfig
from aegis.guardian_touch.store import GuardianStore

# uppercase, minus lookalikes (0/O, 1/I/L)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


class PairStartOut(BaseModel):
    code: str
    approver_id: str
    expires_at: float


class PairOptionsIn(BaseModel):
    code: str


class PairCompleteIn(BaseModel):
    code: str
    credential: dict[str, Any]


class PairCompleteOut(BaseModel):
    credential_id: str
    sign_count: int
    approver_id: str
    display_name: str


class DecideIn(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = ""
    credential: dict[str, Any]


def mount_guardian_touch(app: FastAPI, config: GuardianTouchConfig | None = None) -> None:
    """Add the /guardian/* passkey routes to an approval-service app."""
    config = config or GuardianTouchConfig.from_env()
    store = GuardianStore(app.state.config.db_path)
    app.state.guardian_config = config
    app.state.guardian_store = store

    def _live_code(code: str, now: float) -> dict[str, Any]:
        row = store.get_pairing_code(code)
        if row is None:
            raise HTTPException(404, "unknown pairing code")
        if row["used"]:
            raise HTTPException(409, "pairing code already used")
        if row["expires_at"] <= now:
            raise HTTPException(410, "pairing code expired")
        return row

    def _bound_approver(approver_id: str) -> Approver:
        """The approver a credential or code is bound to, if still allowed to act."""
        row = app.state.store.get_approver(approver_id)
        if row is None or row.get("revoked_at") is not None:
            raise HTTPException(401, "passkey approver not recognized")
        return Approver(id=row["id"], display_name=row["display_name"], auth_method=PASSKEY_AUTH)

    @app.post("/guardian/pair/start", response_model=PairStartOut)
    def pair_start(approver: AuthedApprover) -> PairStartOut:
        """Mint a pairing code for the signed in approver (bearer token required)."""
        for _ in range(5):  # codes are PKs and never deleted, so retry collisions
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
            expires_at = config.clock() + config.pairing_ttl_seconds
            try:
                store.create_pairing_code(code, approver.id, expires_at)
            except sqlite3.IntegrityError:
                continue
            return PairStartOut(code=code, approver_id=approver.id, expires_at=expires_at)
        raise HTTPException(500, "could not allocate a pairing code")

    @app.post("/guardian/pair/options")
    def pair_options(body: PairOptionsIn) -> dict[str, Any]:
        code = body.code.upper()
        pairing = _live_code(code, config.clock())
        approver = _bound_approver(pairing["approver_id"])
        options = generate_registration_options(
            rp_id=config.rp_id,
            rp_name=config.rp_name,
            user_id=code.encode(),
            user_name=approver.id,
            user_display_name=approver.display_name,
            challenge=pairing_challenge(code),
        )
        return json.loads(options_to_json(options))

    @app.post("/guardian/pair/complete", response_model=PairCompleteOut)
    def pair_complete(body: PairCompleteIn) -> PairCompleteOut:
        code = body.code.upper()
        pairing = _live_code(code, config.clock())
        approver = _bound_approver(pairing["approver_id"])
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
            credential_id,
            verification.credential_public_key,
            verification.sign_count,
            approver.id,
        )
        store.mark_code_used(code)
        return PairCompleteOut(
            credential_id=credential_id,
            sign_count=verification.sign_count,
            approver_id=approver.id,
            display_name=approver.display_name,
        )

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
        approver = _bound_approver(stored["approver_id"])
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
        resolved = app.state.resolve_decision(
            proposal_id, approver, body.action, body.comment, evidence=assertion
        )
        return public_row(resolved)
