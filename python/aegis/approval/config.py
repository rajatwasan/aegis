"""Approval service configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

# anvil dev key #9 — test-only, publicly known
DEFAULT_GUARDIAN_KEY = "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6"


class ApprovalConfig(BaseModel):
    db_path: str = ".aegis/approvals.db"
    ttl_seconds: float = 900.0  # pending proposals auto-reject after this
    dual_control: bool = False  # require two distinct approvers
    guardian_key: str = DEFAULT_GUARDIAN_KEY
    chain_id: int = 31337
    auth_deadline_seconds: int = 3600  # on-chain authorization validity window
    policy_path: str = "policies/default.yaml"
    audit_log_path: str = ".aegis/audit.jsonl"
    audit_key_file: str = ".aegis/audit_signing.key"

    @classmethod
    def from_env(cls) -> ApprovalConfig:
        return cls(
            ttl_seconds=float(os.environ.get("AEGIS_APPROVAL_TTL_SECONDS", "900")),
            dual_control=os.environ.get("AEGIS_DUAL_CONTROL", "false").lower() == "true",
            guardian_key=os.environ.get("AEGIS_GUARDIAN_KEY", DEFAULT_GUARDIAN_KEY),
            chain_id=int(os.environ.get("AEGIS_CHAIN_ID", "31337")),
        )

    def ensure_dirs(self) -> None:
        for p in (self.db_path, self.audit_log_path, self.audit_key_file):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
