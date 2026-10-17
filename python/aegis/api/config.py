"""API server configuration.

The API serves the same state the demo/dev stack writes: proposals and the
audit log under ``state_dir``, and chain coordinates from
``state_dir/state.json`` (written by ``aegis.demo`` / the dev stack). Paths
default into ``state_dir`` so one directory holds a coherent world.

The guardian key comes from ``AEGIS_GUARDIAN_KEY`` through
:func:`aegis.approval.config.guardian_key_from_env`; there is no default.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from aegis.approval.config import ApprovalConfig, approver_tokens_from_env
from aegis.config import env_flag, optional_env
from aegis.keys import guardian_key_from_env, operator_key_from_env, policy_path_from_env
from aegis.state import load_chain_state

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class ApiConfig(BaseModel):
    approval: ApprovalConfig
    #: signs the agent's plain transfers and pays for anchors; required once a
    #: chain is configured (state.json exists), never read from state.json
    operator_key: str | None = None
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
        # the live deployment's chain wins over the generic default
        chain_id = int(os.environ.get("AEGIS_CHAIN_ID", str(state.get("chain_id", 31337))))
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
            policy_path=policy_path_from_env(chain_id),
            ttl_seconds=float(os.environ.get("AEGIS_APPROVAL_TTL_SECONDS", "900")),
            dual_control=env_flag("AEGIS_DUAL_CONTROL", False),
            guardian_key=guardian_key_from_env(chain_id),
            chain_id=chain_id,
            approver_tokens=approver_tokens_from_env(),
            admin_token=optional_env("AEGIS_ADMIN_TOKEN"),
        )
        cors = os.environ.get("AEGIS_CORS_ORIGINS")
        operator_key = operator_key_from_env(chain_id) if state else None
        return cls(
            approval=approval,
            operator_key=operator_key,
            state_dir=state_dir,
            cors_origins=[o.strip() for o in cors.split(",")] if cors else DEFAULT_CORS_ORIGINS,
            evals_report_path=os.environ.get("AEGIS_EVALS_REPORT", "evals/report.md"),
        )


__all__ = ["ApiConfig", "DEFAULT_CORS_ORIGINS", "load_chain_state"]
