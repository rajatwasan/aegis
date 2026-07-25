"""Anchoring and Merkle verification as library functions.

The ``aegis`` CLI (anchor / verify) and the web API's ``/audit/verify`` and
``/anchor`` endpoints share this logic: batch every not-yet-anchored audit
record under one Merkle root, anchor the root on-chain in AuditAnchor, and
later prove any record's inclusion against the on-chain root.

Chain state (RPC url, contract addresses, audit-log paths) comes from
``<state-dir>/state.json``; anchored batches are recorded in
``<state-dir>/anchors.json``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aegis import chains
from aegis.agent import ChainClient
from aegis.audit import AuditLog, AuditSigner, MerkleTree, canonical_json
from aegis.audit.log import _hash_record


class StateError(RuntimeError):
    """No usable chain state; run the demo (scripts/demo.sh) first."""


def load_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "state.json"
    if not path.exists():
        raise StateError(f"no state at {path}; run the demo (scripts/demo.sh) first")
    return json.loads(path.read_text())


def load_anchors(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "anchors.json"
    return json.loads(path.read_text()) if path.exists() else []


def save_anchors(state_dir: Path, anchors: list[dict[str, Any]]) -> None:
    (state_dir / "anchors.json").write_text(json.dumps(anchors, indent=2) + "\n")


def load_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    signer = AuditSigner.load_or_create(state["audit_key_file"])
    return AuditLog(state["audit_log_path"], signer).records()


def anchor_contract(state: dict[str, Any]) -> tuple[ChainClient, Any]:
    chain = ChainClient(state["rpc_url"], state["operator_key"])
    return chain, chain.at("AuditAnchor", state["anchor_address"])


def anchor_unanchored(state_dir: Path) -> dict[str, Any] | None:
    """Anchor every not-yet-anchored audit record as one batch.

    Returns the new batch (batch_id, root, tx_hash, decision_ids) or None when
    every record is already anchored.
    """
    state = load_state(state_dir)
    records = load_records(state)
    anchors = load_anchors(state_dir)

    already = {did for batch in anchors for did in batch["decision_ids"]}
    fresh = [r for r in records if r["decision_id"] not in already]
    if not fresh:
        return None

    tree = MerkleTree([canonical_json(r) for r in fresh])
    batch_id = len(anchors)
    chain, contract = anchor_contract(state)
    receipt = chain.call_tx(contract.functions.anchor(tree.root, batch_id))

    # keep the coordinates a third party needs to find this tx again: which
    # chain, which block, when. The explorer link is derived from them.
    batch = {
        "batch_id": batch_id,
        "root": tree.root.hex(),
        "tx_hash": chains.hex0x(receipt["transactionHash"].hex()),
        "chain_id": state.get("chain_id"),
        "block_number": receipt.get("blockNumber"),
        "anchored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision_ids": [r["decision_id"] for r in fresh],
    }
    anchors.append(batch)
    save_anchors(state_dir, anchors)
    return batch


def batch_view(state: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    """Present one anchored batch: on-chain facts plus explorer links.

    Batches written before the chain/block fields existed (and those anchored
    on a chain the state file no longer points at) still render — missing
    coordinates simply yield no link.
    """
    chain_id = batch.get("chain_id") or state.get("chain_id")
    explorer = state.get("explorer_url") or chains.explorer_from_env()
    meta = chains.chain_meta(chain_id, explorer)
    tx_hash = chains.hex0x(batch.get("tx_hash"))
    anchor_address = state.get("anchor_address")
    return {
        "batch_id": batch["batch_id"],
        "root": batch["root"],
        "tx_hash": tx_hash,
        "record_count": len(batch["decision_ids"]),
        "chain_id": chain_id,
        "chain_name": meta.name,
        "block_number": batch.get("block_number"),
        "anchored_at": batch.get("anchored_at"),
        "tx_url": chains.tx_url(chain_id, tx_hash, explorer),
        "anchor_address": anchor_address,
        "anchor_url": chains.address_url(chain_id, anchor_address, explorer),
    }


def _fail(decision_id: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"decision_id": decision_id, "proof_ok": False, "reason": reason, **extra}


def verify_decision(
    anchors: list[dict[str, Any]],
    contract: Any,
    records_by_id: dict[str, dict[str, Any]],
    decision_id: str,
) -> dict[str, Any]:
    """Rebuild one record's Merkle proof and check it against the on-chain root.

    Returns a structured result: proof_ok, reason (on failure), the record,
    its batch id and leaf index, the sibling path, and both roots.
    """
    record = records_by_id.get(decision_id)
    batch = next((b for b in anchors if decision_id in b["decision_ids"]), None)
    if batch is None:
        return _fail(decision_id, "not in any anchored batch", record=record)

    # rebuild the batch's leaves from the live audit log, recomputing each hash
    batch_records = []
    for did in batch["decision_ids"]:
        member = records_by_id.get(did)
        if member is None:
            return _fail(
                decision_id,
                f"batch record {did} missing from log",
                record=record,
                batch_id=batch["batch_id"],
            )
        if _hash_record(member) != member["record_hash"]:
            return _fail(
                decision_id,
                f"record {did} hash mismatch (tampered)",
                record=record,
                batch_id=batch["batch_id"],
            )
        batch_records.append(member)

    index = batch["decision_ids"].index(decision_id)
    tree = MerkleTree([canonical_json(r) for r in batch_records])
    proof = tree.proof(index)
    leaf = canonical_json(batch_records[index])

    onchain_root = bytes(contract.functions.rootOf(batch["batch_id"]).call())
    local_ok = MerkleTree.verify(leaf, proof, tree.root)
    chain_ok = tree.root == onchain_root

    result = {
        "decision_id": decision_id,
        "proof_ok": local_ok and chain_ok,
        "reason": None,
        "record": record,
        "batch_id": batch["batch_id"],
        "index": index,
        "merkle_path": [sibling.hex() for sibling in proof],
        "local_root": tree.root.hex(),
        "onchain_root": onchain_root.hex(),
    }
    if not local_ok:
        result["reason"] = "merkle proof invalid"
    elif not chain_ok:
        result["reason"] = "local root != on-chain root"
    return result


def verify_decision_in_dir(state_dir: Path, decision_id: str) -> dict[str, Any]:
    """One-shot verification: load state, anchors, and records from state_dir.

    The result carries the anchoring batch's on-chain coordinates so the caller
    can link straight to the transaction that sealed this record.
    """
    state = load_state(state_dir)
    anchors = load_anchors(state_dir)
    records_by_id = {r["decision_id"]: r for r in load_records(state)}
    batch = next((b for b in anchors if decision_id in b["decision_ids"]), None)
    if batch is None:
        record = records_by_id.get(decision_id)
        return _fail(decision_id, "not in any anchored batch", record=record, anchor=None)
    _, contract = anchor_contract(state)
    result = verify_decision(anchors, contract, records_by_id, decision_id)
    result["anchor"] = batch_view(state, batch)
    return result
