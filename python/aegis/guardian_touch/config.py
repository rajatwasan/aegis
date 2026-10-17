"""Guardian passkey (WebAuthn) configuration.

``rp_id`` and ``expected_origin`` describe the domain the guardian PAGE is
served from (the frontend), not the API domain: WebAuthn binds credentials
to the relying party the browser is showing.

On a dev chain both default to the local vite origin. On a public chain both
are required: a deployment that silently binds passkeys to ``localhost``
would accept no real phone, or worse, the wrong origin (AGENTS.md R2).
"""

from __future__ import annotations

from pydantic import BaseModel

from aegis import devchain
from aegis.config import ConfigError, optional_env

DEV_RP_ID = "localhost"
DEV_ORIGIN = "http://localhost:5173"


class GuardianTouchConfig(BaseModel):
    rp_id: str = DEV_RP_ID
    rp_name: str = "Aegis Guardian"
    expected_origin: str = DEV_ORIGIN
    pairing_ttl_seconds: float = 300.0  # pairing codes die after 5 minutes

    @classmethod
    def from_env(cls, chain_id: int | None = 31337) -> GuardianTouchConfig:
        rp_id = optional_env("AEGIS_RP_ID")
        origin = optional_env("AEGIS_EXPECTED_ORIGIN")
        if not devchain.is_dev_chain(chain_id):
            missing = [
                name
                for name, value in (("AEGIS_RP_ID", rp_id), ("AEGIS_EXPECTED_ORIGIN", origin))
                if value is None
            ]
            if missing:
                raise ConfigError(
                    f"{', '.join(missing)} required on chain {chain_id}: passkeys must be bound"
                    " to the domain the guardian page is served from"
                )
        return cls(rp_id=rp_id or DEV_RP_ID, expected_origin=origin or DEV_ORIGIN)
