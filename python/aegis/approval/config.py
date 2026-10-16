"""Approval service configuration.

The guardian key has no default (AGENTS.md C3). A process that cannot find
``AEGIS_GUARDIAN_KEY`` does not start; anvil's development keys are refused
unless ``AEGIS_ALLOW_DEV_KEYS=true``, which only the dev and demo scripts set.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from aegis.devkeys import is_dev_key, normalize_key
from aegis.errors import ConfigError

DEV_KEYS_OPT_IN = "AEGIS_ALLOW_DEV_KEYS"


def guardian_key_from_env(environ: dict[str, str] | None = None) -> str:
    """Read and vet ``AEGIS_GUARDIAN_KEY``.

    Raises :class:`ConfigError` when the variable is missing, empty, not a
    32 byte hex key, or one of anvil's well known keys without the explicit
    opt in. The message names the fix.
    """
    env = os.environ if environ is None else environ
    raw = env.get("AEGIS_GUARDIAN_KEY", "").strip()
    if not raw:
        raise ConfigError(
            "AEGIS_GUARDIAN_KEY is required: the approval service signs every approved "
            "authorization with it, and it must be a key only this service holds"
        )
    try:
        normalize_key(raw)
    except ValueError as exc:
        raise ConfigError(f"AEGIS_GUARDIAN_KEY is not a usable private key: {exc}") from exc
    if is_dev_key(raw) and env.get(DEV_KEYS_OPT_IN, "").strip().lower() != "true":
        raise ConfigError(
            "AEGIS_GUARDIAN_KEY is one of anvil's public development keys; refusing to "
            f"sign with it. Generate a private key, or set {DEV_KEYS_OPT_IN}=true for a "
            "local dev chain only"
        )
    return raw


class ApprovalConfig(BaseModel):
    guardian_key: str  # required: no default, see guardian_key_from_env
    db_path: str = ".aegis/approvals.db"
    ttl_seconds: float = 900.0  # pending proposals auto-reject after this
    dual_control: bool = False  # require two distinct approvers
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
            guardian_key=guardian_key_from_env(),
            chain_id=int(os.environ.get("AEGIS_CHAIN_ID", "31337")),
        )

    def ensure_dirs(self) -> None:
        for p in (self.db_path, self.audit_log_path, self.audit_key_file):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
