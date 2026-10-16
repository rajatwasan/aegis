"""Guardian passkey (WebAuthn) configuration.

``rp_id`` and ``expected_origin`` describe the domain the guardian PAGE is
served from (the frontend), not the API domain: WebAuthn binds credentials
to the relying party the browser is showing.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from pydantic import BaseModel


class GuardianTouchConfig(BaseModel):
    rp_id: str = "localhost"
    rp_name: str = "Aegis Guardian"
    expected_origin: str = "http://localhost:5173"
    pairing_ttl_seconds: float = 300.0  # pairing codes die after 5 minutes
    clock: Callable[[], float] = time.time  # injected so tests can move time (AGENTS.md T4)

    @classmethod
    def from_env(cls) -> GuardianTouchConfig:
        return cls(
            rp_id=os.environ.get("AEGIS_RP_ID", "localhost"),
            expected_origin=os.environ.get("AEGIS_EXPECTED_ORIGIN", "http://localhost:5173"),
        )
