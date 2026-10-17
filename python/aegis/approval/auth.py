"""Approver authentication: a request becomes a :class:`Principal` or a 401.

Every approve or reject carries an authenticated principal (AGENTS.md R4). Two
credential kinds exist:

* ``token``: a static bearer secret configured per named human in
  ``AEGIS_APPROVER_TOKENS`` (``id:token,id:token``), compared in constant time
  against every entry so timing reveals nothing about which id matched.
* ``passkey``: a WebAuthn assertion bound to the exact decision, verified by
  ``aegis.guardian_touch`` which then constructs the principal itself.

The approver identity is derived from the credential, never read from a request
body, query string or client side setting. Tokens are never logged.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aegis.config import ConfigError

AuthMethod = Literal["token", "passkey"]

#: approver ids: lowercase, start alphanumeric, dots dashes underscores, <= 64
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MIN_TOKEN_LENGTH = 24
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class Principal:
    """Who acted and how they proved it. Recorded on approvals and in the audit log."""

    id: str
    auth: AuthMethod

    def as_record(self) -> dict[str, str]:
        return {"approver": self.id, "auth": self.auth}


def parse_approver_tokens(raw: str, variable: str = "AEGIS_APPROVER_TOKENS") -> dict[str, str]:
    """Parse ``id:token,id:token`` into a mapping, validating shape without echoing tokens.

    Entries are numbered from 1 in error messages; the token value never appears.
    """
    tokens: dict[str, str] = {}
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not entries:
        raise ConfigError(f"{variable} is set but contains no id:token entries")
    for position, entry in enumerate(entries, start=1):
        if ":" not in entry:
            raise ConfigError(f"{variable} entry {position} is not of the form id:token")
        approver_id, token = entry.split(":", 1)
        approver_id = approver_id.strip()
        token = token.strip()
        if not _ID_PATTERN.match(approver_id):
            raise ConfigError(f"{variable} entry {position}: id must match {_ID_PATTERN.pattern}")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(
                f"{variable} entry {position} ({approver_id}): token shorter than"
                f" {MIN_TOKEN_LENGTH} characters"
            )
        if ":" in token or "," in token:
            raise ConfigError(f"{variable} entry {position} ({approver_id}): token contains : or ,")
        if approver_id in tokens:
            raise ConfigError(f"{variable} entry {position}: duplicate id {approver_id}")
        tokens[approver_id] = token
    return tokens


class ApproverRegistry:
    """Static bearer tokens for named approvers, looked up in constant shape."""

    def __init__(self, tokens: Mapping[str, str]) -> None:
        self._tokens = dict(tokens)

    def __len__(self) -> int:
        return len(self._tokens)

    def lookup(self, token: str) -> Principal | None:
        """Return the principal for ``token``, scanning every entry regardless of match."""
        presented = token.encode()
        matched: str | None = None
        for approver_id, stored in self._tokens.items():
            if hmac.compare_digest(presented, stored.encode()):
                matched = approver_id  # keep scanning: no early exit
        return Principal(id=matched, auth="token") if matched is not None else None


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


#: declared so the OpenAPI schema (and the generated client types) carry the
#: bearer requirement; auto_error is off so our own 401 messages are used
APPROVER_SCHEME = HTTPBearer(scheme_name="ApproverToken", auto_error=False)
ADMIN_SCHEME = HTTPBearer(scheme_name="AdminToken", auto_error=False)
_APPROVER_CREDENTIALS = Depends(APPROVER_SCHEME)
_ADMIN_CREDENTIALS = Depends(ADMIN_SCHEME)


def require_approver(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _APPROVER_CREDENTIALS,
) -> Principal:
    """FastAPI dependency: the authenticated approver, or 401 with a Bearer challenge."""
    registry: ApproverRegistry | None = getattr(request.app.state, "approvers", None)
    token = credentials.credentials.strip() if credentials is not None else None
    if not token:
        raise HTTPException(
            401, "approver credential required: Authorization: Bearer <token>", _CHALLENGE
        )
    if registry is None or len(registry) == 0:
        raise HTTPException(
            401, "no approvers configured on this service (AEGIS_APPROVER_TOKENS)", _CHALLENGE
        )
    principal = registry.lookup(token)
    if principal is None:
        raise HTTPException(401, "approver token not recognised", _CHALLENGE)
    return principal


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _ADMIN_CREDENTIALS,
) -> None:
    """FastAPI dependency for operator only routes (pairing code minting)."""
    expected: str | None = getattr(request.app.state, "admin_token", None)
    token = credentials.credentials.strip() if credentials is not None else None
    if not token:
        raise HTTPException(401, "admin credential required: Authorization: Bearer", _CHALLENGE)
    if not expected:
        raise HTTPException(401, "no admin token configured (AEGIS_ADMIN_TOKEN)", _CHALLENGE)
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "admin token not recognised", _CHALLENGE)
