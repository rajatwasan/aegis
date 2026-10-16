"""Approver identity: who a human is, established by a credential the agent never holds.

An approver is created by an operator (``aegis approver add``) and receives a
random bearer token once. The service stores only ``sha256(token)``. Approve
and reject require ``Authorization: Bearer <token>``; the identity written to
approvals and audit records is resolved from that token, never read from the
request body (AGENTS.md C4). A missing, malformed, unknown or revoked token is
rejected before any state changes (C1, I2).

Spec: docs/specs/2026-10-hardening.md W2, decision D1.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from aegis.errors import AegisError

#: how the approver proved presence; "passkey" arrives with W10
AuthMethod = str
TOKEN_AUTH: AuthMethod = "token"


class Unauthenticated(AegisError):
    """No usable approver credential on the request. Maps to HTTP 401."""


@dataclass(frozen=True)
class Approver:
    id: str
    display_name: str
    auth_method: AuthMethod = TOKEN_AUTH

    def as_record(self) -> dict[str, str]:
        """The identity fields written into approvals and audit records."""
        return {
            "approver": self.id,
            "display_name": self.display_name,
            "auth_method": self.auth_method,
        }


def new_token() -> str:
    """A fresh approver token: 32 random bytes, url safe. Shown exactly once."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The only form of a token the database ever holds."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(stored_hash: str, presented: str) -> bool:
    """Constant time comparison of a presented token against a stored hash."""
    return hmac.compare_digest(stored_hash, hash_token(presented))


def bearer_token(authorization: str | None) -> str:
    """Extract the token from an ``Authorization: Bearer ...`` header value."""
    if not authorization:
        raise Unauthenticated("approver token required: send Authorization: Bearer <token>")
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("approver token required: send Authorization: Bearer <token>")
    return token.strip()


def resolve_approver(store: ApproverStore, authorization: str | None) -> Approver:
    """Turn a request's Authorization header into an :class:`Approver`.

    Unknown and revoked tokens produce the same client visible error; which it
    was is an operator concern, logged server side by the caller if needed.
    """
    token = bearer_token(authorization)
    row = store.get_approver_by_token_hash(hash_token(token))
    if row is None or row.get("revoked_at") is not None:
        raise Unauthenticated("approver token not recognized")
    if not tokens_match(row["token_hash"], token):  # defense in depth; the lookup was by hash
        raise Unauthenticated("approver token not recognized")
    return Approver(id=row["id"], display_name=row["display_name"])


class ApproverStore:
    """The subset of the proposal store the identity layer needs (structural)."""

    def get_approver_by_token_hash(self, token_hash: str) -> dict | None:  # pragma: no cover
        raise NotImplementedError
