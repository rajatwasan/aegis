"""Backend the MCP tools call into.

Wraps a live :class:`AegisRuntime` (policy gate + on-chain execution + audit)
plus an in-process approval service over a shared SQLite database, so the four
MCP tools read and write exactly the state the rest of the runtime uses.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aegis import devchain
from aegis.agent import AegisRuntime, ChainClient
from aegis.approval import ApprovalConfig, GuardianSigner, create_app
from aegis.approval.config import guardian_key_from_env
from aegis.audit import AuditLog, AuditSigner, MerkleTree, canonical_json
from aegis.config import ConfigError, validate_hex_key
from aegis.policy import Operation, Proposal, load_policy

# GuardedToken and ComplianceRegistry are addressed by their forge artifact ABIs.
_TOKEN_ARTIFACT = "GuardedToken"
_REGISTRY_ARTIFACT = "ComplianceRegistry"


class AegisBackend:
    """Implements the four MCP tools against the shared Aegis state."""

    def __init__(
        self,
        *,
        runtime: AegisRuntime,
        approval_client: TestClient,
        audit: AuditLog,
        audit_public_key: str,
    ) -> None:
        self.runtime = runtime
        self.approval = approval_client
        self.audit = audit
        self.audit_public_key = audit_public_key

    # --------------------------------------------------------------- tool: propose
    def propose_transfer(
        self,
        *,
        token: str,
        from_addr: str,
        to: str,
        amount: int,
        asset_class: int = 0,
    ) -> dict[str, Any]:
        """Gate a transfer proposal; execute on ALLOW, escalate, or deny."""
        proposal = Proposal(
            operation=Operation.TRANSFER,
            token=token,
            **{"from": from_addr},
            to=to,
            asset_class=asset_class,
            amount=amount,
        )
        result = self.runtime.handle(proposal)
        # the runtime just appended this decision's audit record
        result["audit_decision_id"] = self.audit.records()[-1]["decision_id"]
        return result

    # ---------------------------------------------------------- tool: proposal status
    def get_proposal_status(self, *, decision_id: str) -> dict[str, Any]:
        response = self.approval.get(f"/proposals/{decision_id}")
        if response.status_code == 404:
            return {"found": False, "decision_id": decision_id}
        response.raise_for_status()
        row = response.json()
        return {
            "found": True,
            "decision_id": row["decision_id"],
            "status": row["status"],
            "proposal": row["proposal"],
            "approvals": row["approvals"],
            "has_signature": row["signature"] is not None,
        }

    # -------------------------------------------------------------- tool: list pending
    def list_pending(self) -> dict[str, Any]:
        response = self.approval.get("/proposals", params={"status": "pending"})
        response.raise_for_status()
        rows = response.json()
        pending = [
            {
                "decision_id": r["decision_id"],
                "proposal": r["proposal"],
                "expires_at": r["expires_at"],
            }
            for r in rows
        ]
        return {"count": len(pending), "pending": pending}

    # ----------------------------------------------------------- tool: audit proof
    def get_audit_proof(self, *, decision_id: str) -> dict[str, Any]:
        """Merkle inclusion proof for the audit record with this decision id."""
        records = self.audit.records()
        leaves = [canonical_json(r) for r in records]
        index = next((i for i, r in enumerate(records) if r["decision_id"] == decision_id), None)
        if index is None:
            return {"found": False, "decision_id": decision_id, "record_count": len(records)}
        tree = MerkleTree(leaves)
        proof = tree.proof(index)
        return {
            "found": True,
            "decision_id": decision_id,
            "index": index,
            "record_count": len(records),
            "record_hash": records[index]["record_hash"],
            "leaf": leaves[index].hex(),
            "root": tree.root.hex(),
            "proof": [sibling.hex() for sibling in proof],
            "audit_public_key": self.audit_public_key,
        }


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"MCP server requires environment variable {name}")
    return value


def build_backend_from_env() -> AegisBackend:
    """Assemble the backend from AEGIS_* environment variables.

    Required: AEGIS_RPC_URL, AEGIS_TOKEN_ADDRESS, AEGIS_REGISTRY_ADDRESS,
    AEGIS_OPERATOR_KEY, and AEGIS_GUARDIAN_KEY unless the chain is a dev chain
    (then the anvil dev guardian key is substituted and announced). Optional:
    AEGIS_CHAIN_ID, AEGIS_POLICY_PATH, AEGIS_DB_PATH, AEGIS_AUDIT_LOG_PATH,
    AEGIS_AUDIT_KEY_FILE.
    """
    rpc_url = _require("AEGIS_RPC_URL")
    operator_key = validate_hex_key(_require("AEGIS_OPERATOR_KEY"), "AEGIS_OPERATOR_KEY")
    token_address = _require("AEGIS_TOKEN_ADDRESS")
    registry_address = _require("AEGIS_REGISTRY_ADDRESS")
    chain_id = int(os.environ.get("AEGIS_CHAIN_ID", "31337"))
    devchain.require_not_dev_key(operator_key, "operator", chain_id)

    chain = ChainClient(rpc_url, operator_key)
    token = chain.at(_TOKEN_ARTIFACT, token_address)
    registry = chain.at(_REGISTRY_ARTIFACT, registry_address)

    workdir = Path(os.environ.get("AEGIS_STATE_DIR", ".aegis/mcp"))
    workdir.mkdir(parents=True, exist_ok=True)
    config = ApprovalConfig(
        db_path=os.environ.get("AEGIS_DB_PATH", str(workdir / "approvals.db")),
        audit_log_path=os.environ.get("AEGIS_AUDIT_LOG_PATH", str(workdir / "audit.jsonl")),
        audit_key_file=os.environ.get("AEGIS_AUDIT_KEY_FILE", str(workdir / "audit.key")),
        policy_path=os.environ.get("AEGIS_POLICY_PATH", "policies/default.yaml"),
        chain_id=chain_id,
        guardian_key=guardian_key_from_env(chain_id),
    )
    config.ensure_dirs()
    # the signatures this backend hands out must be the ones the token accepts
    onchain_guardian = token.functions.guardian().call()
    signer_address = GuardianSigner(config.guardian_key, chain_id).address
    if onchain_guardian.lower() != signer_address.lower():
        raise ConfigError(
            f"guardian key mismatch: configured signer {signer_address} is not the guardian"
            f" of token {token_address} (on-chain guardian is {onchain_guardian})"
        )

    approval_client = TestClient(create_app(config))
    audit_signer = AuditSigner.load_or_create(config.audit_key_file)
    audit = AuditLog(config.audit_log_path, audit_signer)
    runtime = AegisRuntime(
        policy=load_policy(config.policy_path),
        audit=audit,
        chain=chain,
        token=token,
        registry=registry,
        approval_client=approval_client,
    )
    return AegisBackend(
        runtime=runtime,
        approval_client=approval_client,
        audit=audit,
        audit_public_key=audit_signer.public_key_hex(),
    )
