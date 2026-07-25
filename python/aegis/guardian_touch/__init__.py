"""Passkey-verified guardian approvals (WebAuthn).

A guardian pairs a platform passkey against a short-lived code, then
approves or rejects escalated proposals by signing a challenge derived from
the exact decision: ``sha256(decision_id || canonical_json(proposal))``.
"""

from aegis.guardian_touch.challenge import decision_challenge, pairing_challenge
from aegis.guardian_touch.config import GuardianTouchConfig
from aegis.guardian_touch.routes import mount_guardian_touch
from aegis.guardian_touch.store import GuardianStore

__all__ = [
    "GuardianStore",
    "GuardianTouchConfig",
    "decision_challenge",
    "mount_guardian_touch",
    "pairing_challenge",
]
