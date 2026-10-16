"""Exception types shared across the Aegis services.

Every failure a process entry point must turn into a one line message and a
non zero exit lives here, so ``python -m aegis.api`` and friends can catch
one base class instead of guessing.
"""

from __future__ import annotations


class AegisError(Exception):
    """Base class for operator facing failures."""


class ConfigError(AegisError):
    """Configuration is missing or unusable. The process must not start."""


class GuardianMismatch(AegisError):
    """The configured guardian signer is not the token's on chain guardian.

    Every authorization the service would sign would be rejected by the
    contract, so the service refuses to start rather than serve approvals
    that cannot execute (AGENTS.md C8, I5).
    """

    def __init__(self, expected: str, actual: str, token_address: str) -> None:
        self.expected = expected
        self.actual = actual
        self.token_address = token_address
        super().__init__(
            "guardian mismatch: approval service signs as "
            f"{actual} but token {token_address} accepts only {expected}; "
            "set AEGIS_GUARDIAN_KEY to the guardian's key or rotate the guardian on chain"
        )


class GuardianUnverified(AegisError):
    """The on chain guardian could not be read, so the binding is unknown.

    Unknown is not acceptable for a signer (AGENTS.md C1): the operator fixes
    the chain connection, the check does not get skipped.
    """

    def __init__(self, reason: str, token_address: str) -> None:
        self.reason = reason
        self.token_address = token_address
        super().__init__(
            f"guardian binding unverified for token {token_address}: {reason}; "
            "the approval service will not start until the on chain guardian can be read"
        )
