"""API server configuration.

The API serves the same state the demo/dev stack writes: proposals and the
audit log under ``state_dir``, and chain coordinates from
``state_dir/state.json`` (written by ``aegis.demo`` / the dev stack). Paths
default into ``state_dir`` so one directory holds a coherent world.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aegis.approval.config import DEFAULT_GUARDIAN_KEY, ApprovalConfig

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class ApiConfig(BaseModel):
    approval: ApprovalConfig
    state_dir: str = ".aegis/demo"
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    evals_report_path: str = "evals/report.md"
    # how long a background agent run waits for a human before giving up
    approval_wait_seconds: float = 600.0
    approval_poll_seconds: float = 0.25

    @classmethod
    def from_env(cls) -> ApiConfig:
        state_dir = os.environ.get("AEGIS_STATE_DIR", ".aegis/demo")
        state = load_chain_state(Path(state_dir)) or {}
        approval = ApprovalConfig(
            db_path=os.environ.get("AEGIS_DB_PATH", str(Path(state_dir) / "approvals.db")),
            audit_log_path=os.environ.get(
                "AEGIS_AUDIT_LOG_PATH",
                state.get("audit_log_path", str(Path(state_dir) / "audit.jsonl")),
            ),
            audit_key_file=os.environ.get(
                "AEGIS_AUDIT_KEY_FILE",
                state.get("audit_key_file", str(Path(state_dir) / "audit.key")),
            ),
            policy_path=os.environ.get("AEGIS_POLICY_PATH", "policies/default.yaml"),
            ttl_seconds=float(os.environ.get("AEGIS_APPROVAL_TTL_SECONDS", "900")),
            dual_control=os.environ.get("AEGIS_DUAL_CONTROL", "false").lower() == "true",
            guardian_key=os.environ.get("AEGIS_GUARDIAN_KEY", DEFAULT_GUARDIAN_KEY),
            chain_id=int(os.environ.get("AEGIS_CHAIN_ID", str(state.get("chain_id", 31337)))),
        )
        cors = os.environ.get("AEGIS_CORS_ORIGINS")
        return cls(
            approval=approval,
            state_dir=state_dir,
            cors_origins=[o.strip() for o in cors.split(",")] if cors else DEFAULT_CORS_ORIGINS,
            evals_report_path=os.environ.get("AEGIS_EVALS_REPORT", "evals/report.md"),
        )


def load_chain_state(state_dir: Path) -> dict[str, Any] | None:
    """Read ``state.json`` (chain coordinates) if the dev/demo stack wrote one."""
    path = state_dir / "state.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
