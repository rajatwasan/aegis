"""Guardian passkey (WebAuthn) configuration.

``rp_id`` and ``expected_origin`` describe the domain the guardian PAGE is
served from (the frontend), not the API domain: WebAuthn binds credentials
to the relying party the browser is showing.
"""

from __future__ import annotations

import os

from pydantic import BaseModel


class GuardianTouchConfig(BaseModel):
    rp_id: str = "localhost"
    rp_name: str = "Aegis Guardian"
    expected_origin: str = "http://localhost:5173"
    pairing_ttl_seconds: float = 300.0  # pairing codes die after 5 minutes

    @classmethod
    def from_env(cls) -> GuardianTouchConfig:
        return cls(
            rp_id=os.environ.get("AEGIS_RP_ID", "localhost"),
            expected_origin=os.environ.get("AEGIS_EXPECTED_ORIGIN", "http://localhost:5173"),
        )
