"""Challenge derivation: the passkey signs the exact decision, nothing else."""

from __future__ import annotations

import hashlib
from typing import Any

from aegis.audit.canonical import canonical_json


def decision_challenge(decision_id: str, proposal: dict[str, Any]) -> bytes:
    """The bytes a guardian passkey asserts over for one decision.

    ``sha256(decision_id || canonical_json(proposal))`` — deterministic, so
    the server can recompute it at verification time and the assertion is
    bound to this proposal's exact payload.
    """
    return hashlib.sha256(decision_id.encode() + canonical_json(proposal)).digest()


def pairing_challenge(code: str) -> bytes:
    """Registration challenge derived from the pairing code (no extra state)."""
    return hashlib.sha256(b"aegis-guardian-pair:" + code.encode()).digest()
