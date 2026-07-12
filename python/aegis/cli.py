"""``aegis`` command-line interface: anchor audit batches and verify inclusion.

Two subcommands close the audit loop end to end:

  aegis anchor              Batch every not-yet-anchored audit record, compute
                            its Merkle root, and anchor the root on-chain in the
                            AuditAnchor contract.
  aegis verify <id>         Recompute a decision record's hash, rebuild its
                            Merkle proof, fetch the batch root from AuditAnchor
                            over RPC, and print PROOF OK / PROOF FAIL.
  aegis verify --all        Verify every anchored record.

State (RPC url, contract addresses, audit-log paths) is read from
``<state-dir>/state.json``; anchored batches are recorded in
``<state-dir>/anchors.json``. The state dir defaults to $AEGIS_STATE_DIR or
``.aegis/demo`` (written by the demo runner).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from aegis.agent import ChainClient
from aegis.audit import AuditLog, AuditSigner, MerkleTree, canonical_json
from aegis.audit.log import _hash_record

DEFAULT_STATE_DIR = os.environ.get("AEGIS_STATE_DIR", ".aegis/demo")


class StateError(RuntimeError):
    pass


def _load_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "state.json"
    if not path.exists():
        raise StateError(f"no state at {path}; run the demo (scripts/demo.sh) first")
    return json.loads(path.read_text())


def _load_anchors(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "anchors.json"
    return json.loads(path.read_text()) if path.exists() else []


def _save_anchors(state_dir: Path, anchors: list[dict[str, Any]]) -> None:
    (state_dir / "anchors.json").write_text(json.dumps(anchors, indent=2) + "\n")


def _records(state: dict[str, Any]) -> list[dict[str, Any]]:
    signer = AuditSigner.load_or_create(state["audit_key_file"])
    return AuditLog(state["audit_log_path"], signer).records()


def _anchor_contract(state: dict[str, Any]) -> tuple[ChainClient, Any]:
    chain = ChainClient(state["rpc_url"], state["operator_key"])
    contract = chain.at("AuditAnchor", state["anchor_address"])
    return chain, contract


# --------------------------------------------------------------------------- #
# anchor
# --------------------------------------------------------------------------- #


def cmd_anchor(state_dir: Path) -> int:
    state = _load_state(state_dir)
    records = _records(state)
    anchors = _load_anchors(state_dir)

    already = {did for batch in anchors for did in batch["decision_ids"]}
    fresh = [r for r in records if r["decision_id"] not in already]
    if not fresh:
        print("nothing to anchor: all audit records are already anchored")
        return 0

    tree = MerkleTree([canonical_json(r) for r in fresh])
    root = tree.root
    batch_id = len(anchors)

    chain, contract = _anchor_contract(state)
    chain.call_tx(contract.functions.anchor(root, batch_id))

    anchors.append(
        {
            "batch_id": batch_id,
            "root": root.hex(),
            "decision_ids": [r["decision_id"] for r in fresh],
        }
    )
    _save_anchors(state_dir, anchors)
    print(f"anchored batch {batch_id}: {len(fresh)} record(s), root 0x{root.hex()}")
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def _verify_one(
    state: dict[str, Any],
    anchors: list[dict[str, Any]],
    contract: Any,
    records_by_id: dict[str, dict[str, Any]],
    decision_id: str,
) -> bool:
    batch = next((b for b in anchors if decision_id in b["decision_ids"]), None)
    if batch is None:
        print(f"PROOF FAIL {decision_id}: not in any anchored batch")
        return False

    # rebuild the batch's leaves from the live audit log, recomputing each hash
    batch_records = []
    for did in batch["decision_ids"]:
        record = records_by_id.get(did)
        if record is None:
            print(f"PROOF FAIL {decision_id}: batch record {did} missing from log")
            return False
        if _hash_record(record) != record["record_hash"]:
            print(f"PROOF FAIL {decision_id}: record {did} hash mismatch (tampered)")
            return False
        batch_records.append(record)

    index = batch["decision_ids"].index(decision_id)
    tree = MerkleTree([canonical_json(r) for r in batch_records])
    proof = tree.proof(index)
    leaf = canonical_json(batch_records[index])

    onchain_root = bytes(contract.functions.rootOf(batch["batch_id"]).call())
    local_ok = MerkleTree.verify(leaf, proof, tree.root)
    chain_ok = tree.root == onchain_root

    if local_ok and chain_ok:
        print(
            f"PROOF OK   {decision_id}: included in batch {batch['batch_id']} "
            f"(root 0x{onchain_root.hex()})"
        )
        return True
    reason = "merkle proof invalid" if not local_ok else "local root != on-chain root"
    print(f"PROOF FAIL {decision_id}: {reason}")
    return False


def cmd_verify(state_dir: Path, decision_id: str | None, verify_all: bool) -> int:
    state = _load_state(state_dir)
    anchors = _load_anchors(state_dir)
    if not anchors:
        print("no anchored batches; run `aegis anchor` first")
        return 1

    records_by_id = {r["decision_id"]: r for r in _records(state)}
    _, contract = _anchor_contract(state)

    if verify_all:
        ids = [did for batch in anchors for did in batch["decision_ids"]]
    elif decision_id:
        ids = [decision_id]
    else:
        print("usage: aegis verify <decision-id> | aegis verify --all", file=sys.stderr)
        return 2

    ok = all(_verify_one(state, anchors, contract, records_by_id, did) for did in ids)
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis", description="Aegis audit anchoring and proofs")
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=f"directory holding state.json/anchors.json (default: {DEFAULT_STATE_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("anchor", help="anchor all unanchored audit records on-chain")

    verify = sub.add_parser("verify", help="verify a decision's Merkle inclusion proof")
    verify.add_argument("decision_id", nargs="?", help="audit record decision id")
    verify.add_argument("--all", action="store_true", help="verify every anchored record")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = Path(args.state_dir)
    try:
        if args.command == "anchor":
            return cmd_anchor(state_dir)
        if args.command == "verify":
            return cmd_verify(state_dir, args.decision_id, args.all)
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
