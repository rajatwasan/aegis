"""``aegis`` command-line interface: anchor audit batches and verify inclusion.

Two subcommands close the audit loop end to end, and one manages approvers:

  aegis anchor              Batch every not-yet-anchored audit record, compute
                            its Merkle root, and anchor the root on-chain in the
                            AuditAnchor contract.
  aegis verify <id>         Recompute a decision record's hash, rebuild its
                            Merkle proof, fetch the batch root from AuditAnchor
                            over RPC, and print PROOF OK / PROOF FAIL.
  aegis verify --all        Verify every anchored record.
  aegis approver add <id>   Register a human approver and print their bearer
                            token exactly once (only its hash is stored).
  aegis approver revoke <id>
  aegis approver list

The heavy lifting lives in :mod:`aegis.anchoring` (shared with the web API);
this module is the thin printing/exit-code layer. State (RPC url, contract
addresses, audit-log paths) is read from ``<state-dir>/state.json``; anchored
batches are recorded in ``<state-dir>/anchors.json``. The state dir defaults
to $AEGIS_STATE_DIR or ``.aegis/demo`` (written by the demo runner).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from aegis import anchoring
from aegis.anchoring import StateError
from aegis.approval.identity import hash_token, new_token
from aegis.approval.store import ProposalStore

DEFAULT_STATE_DIR = os.environ.get("AEGIS_STATE_DIR", ".aegis/demo")


# --------------------------------------------------------------------------- #
# anchor
# --------------------------------------------------------------------------- #


def cmd_anchor(state_dir: Path) -> int:
    batch = anchoring.anchor_unanchored(state_dir)
    if batch is None:
        print("nothing to anchor: all audit records are already anchored")
        return 0
    view = anchoring.batch_view(anchoring.load_state(state_dir), batch)
    print(
        f"anchored batch {batch['batch_id']}: {len(batch['decision_ids'])} record(s),"
        f" root 0x{batch['root']}"
    )
    print(f"  chain {view['chain_name']} block {view['block_number']} tx {view['tx_hash']}")
    if view["tx_url"]:
        print(f"  track  {view['tx_url']}")
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def _print_result(result: dict[str, Any]) -> bool:
    decision_id = result["decision_id"]
    if result["proof_ok"]:
        print(
            f"PROOF OK   {decision_id}: included in batch {result['batch_id']} "
            f"(root 0x{result['onchain_root']})"
        )
        return True
    print(f"PROOF FAIL {decision_id}: {result['reason']}")
    return False


def cmd_verify(state_dir: Path, decision_id: str | None, verify_all: bool) -> int:
    state = anchoring.load_state(state_dir)
    anchors = anchoring.load_anchors(state_dir)
    if not anchors:
        print("no anchored batches; run `aegis anchor` first")
        return 1

    records_by_id = {r["decision_id"]: r for r in anchoring.load_records(state)}
    _, contract = anchoring.anchor_contract(state)

    if verify_all:
        ids = [did for batch in anchors for did in batch["decision_ids"]]
    elif decision_id:
        ids = [decision_id]
    else:
        print("usage: aegis verify <decision-id> | aegis verify --all", file=sys.stderr)
        return 2

    ok = all(
        _print_result(anchoring.verify_decision(anchors, contract, records_by_id, did))
        for did in ids
    )
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# approver
# --------------------------------------------------------------------------- #


def approvals_db_path(state_dir: Path, explicit: str | None) -> Path:
    """Same resolution the API uses: AEGIS_DB_PATH, else <state-dir>/approvals.db."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("AEGIS_DB_PATH")
    return Path(env) if env else state_dir / "approvals.db"


def cmd_approver_add(db_path: Path, approver_id: str, display_name: str | None) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = ProposalStore(str(db_path))
    if store.get_approver(approver_id) is not None:
        print(f"error: approver '{approver_id}' already exists", file=sys.stderr)
        return 1
    token = new_token()
    store.add_approver(approver_id, display_name or approver_id, hash_token(token))
    print(f"approver '{approver_id}' created in {db_path}")
    print("token (shown once, store it where only this person can read it):")
    print(token)
    return 0


def cmd_approver_revoke(db_path: Path, approver_id: str) -> int:
    store = ProposalStore(str(db_path))
    try:
        row = store.revoke_approver(approver_id)
    except KeyError:
        print(f"error: no approver '{approver_id}' in {db_path}", file=sys.stderr)
        return 1
    print(f"approver '{approver_id}' revoked at {row['revoked_at']:.0f}")
    return 0


def cmd_approver_list(db_path: Path) -> int:
    store = ProposalStore(str(db_path))
    rows = store.list_approvers()
    if not rows:
        print(f"no approvers in {db_path}; add one with `aegis approver add <id>`")
        return 0
    print(f"{'id':<20} {'display name':<24} {'created':<12} status")
    for row in rows:
        status = "revoked" if row["revoked_at"] is not None else "active"
        print(f"{row['id']:<20} {row['display_name']:<24} {row['created_at']:<12.0f} {status}")
    return 0


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

    approver = sub.add_parser("approver", help="manage human approvers and their tokens")
    approver.add_argument(
        "--db",
        default=None,
        help="approvals database (default: $AEGIS_DB_PATH or <state-dir>/approvals.db)",
    )
    approver_sub = approver.add_subparsers(dest="approver_command", required=True)
    add = approver_sub.add_parser("add", help="create an approver and print the token once")
    add.add_argument("approver_id", help="short stable id, e.g. ops-casey")
    add.add_argument("--name", default=None, help="display name shown in the console")
    revoke = approver_sub.add_parser("revoke", help="revoke an approver's token")
    revoke.add_argument("approver_id")
    approver_sub.add_parser("list", help="list approvers (never shows tokens or hashes)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = Path(args.state_dir)
    try:
        if args.command == "anchor":
            return cmd_anchor(state_dir)
        if args.command == "verify":
            return cmd_verify(state_dir, args.decision_id, args.all)
        if args.command == "approver":
            db_path = approvals_db_path(state_dir, args.db)
            if args.approver_command == "add":
                return cmd_approver_add(db_path, args.approver_id, args.name)
            if args.approver_command == "revoke":
                return cmd_approver_revoke(db_path, args.approver_id)
            if args.approver_command == "list":
                return cmd_approver_list(db_path)
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
