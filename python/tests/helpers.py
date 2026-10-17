"""Shared test helpers: configs built from the dev chain world, explicitly.

Every ``ApprovalConfig`` in the suite passes the guardian key and the policy
path on purpose; there is no default to lean on (AGENTS.md R2).
"""

from __future__ import annotations

from pathlib import Path

from aegis import devchain
from aegis.approval import ApprovalConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "dev.yaml"

DEV_GUARDIAN_KEY = devchain.dev_guardian_key()
DEV_OPERATOR_KEY = devchain.dev_operator_key()

#: approver tokens the suite uses; long enough for the registry, obviously fake
TOKENS = {
    "ops-1": "test-token-ops-1-000000000000000000",
    "ops-2": "test-token-ops-2-000000000000000000",
}


def bearer(approver_id: str) -> dict[str, str]:
    """Authorization header for one of the suite's approvers."""
    return {"Authorization": f"Bearer {TOKENS[approver_id]}"}


def dev_approval_config(tmp_path: Path, **overrides) -> ApprovalConfig:
    """An ApprovalConfig rooted in ``tmp_path`` for the anvil dev world."""
    defaults = dict(
        guardian_key=DEV_GUARDIAN_KEY,
        chain_id=31337,
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(POLICY_PATH),
        ttl_seconds=900.0,
        approver_tokens=dict(TOKENS),
    )
    defaults.update(overrides)
    return ApprovalConfig(**defaults)


def fresh_key() -> str:
    """A newly generated private key as 0x prefixed hex (hexbytes agnostic)."""
    from eth_account import Account
    from web3 import Web3

    return Web3.to_hex(Account.create().key)
