"""Approval service configuration.

There is no default guardian key. ``from_env`` requires ``AEGIS_GUARDIAN_KEY``
and refuses a publicly known anvil key unless the target chain is a dev chain,
where the anvil key is substituted and announced once (SPEC.md section 5,
AGENTS.md R2 and R3). Resolution lives in :mod:`aegis.keys`.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from aegis import devchain
from aegis.config import env_flag, validate_hex_key
from aegis.keys import guardian_key_from_env

__all__ = ["ApprovalConfig", "guardian_key_from_env"]


class ApprovalConfig(BaseModel):
    guardian_key: str
    chain_id: int = 31337
    db_path: str = ".aegis/approvals.db"
    ttl_seconds: float = 900.0  # pending proposals auto-reject after this
    dual_control: bool = False  # require two distinct approvers
    auth_deadline_seconds: int = 3600  # on-chain authorization validity window
    policy_path: str = "policies/default.yaml"
    audit_log_path: str = ".aegis/audit.jsonl"
    audit_key_file: str = ".aegis/audit_signing.key"

    @field_validator("guardian_key")
    @classmethod
    def _hex_key(cls, value: str) -> str:
        return validate_hex_key(value, "guardian_key")

    @model_validator(mode="after")
    def _no_dev_key_on_public_chain(self) -> ApprovalConfig:
        devchain.require_not_dev_key(self.guardian_key, "guardian", self.chain_id)
        return self

    @classmethod
    def from_env(cls) -> ApprovalConfig:
        chain_id = int(os.environ.get("AEGIS_CHAIN_ID", "31337"))
        return cls(
            guardian_key=guardian_key_from_env(chain_id),
            chain_id=chain_id,
            ttl_seconds=float(os.environ.get("AEGIS_APPROVAL_TTL_SECONDS", "900")),
            dual_control=env_flag("AEGIS_DUAL_CONTROL", False),
        )

    def ensure_dirs(self) -> None:
        for p in (self.db_path, self.audit_log_path, self.audit_key_file):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
