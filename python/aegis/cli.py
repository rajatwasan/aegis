"""``aegis`` command-line interface: anchor audit batches and verify inclusion.

Two subcommands close the audit loop end to end:

  aegis anchor              Batch every not-yet-anchored audit record, compute
                            its Merkle root, and anchor the root on-chain in the
                            AuditAnchor contract.
  aegis verify <id>         Recompute a decision record's hash, rebuild its
                            Merkle proof, fetch the batch root from AuditAnchor
                            over RPC, and print PROOF OK / PROOF FAIL.
  aegis verify --all        Verify every anchored record.

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
from aegis.config import ConfigError
from aegis.keys import operator_key_from_env

DEFAULT_STATE_DIR = os.environ.get("AEGIS_STATE_DIR", ".aegis/demo")


# --------------------------------------------------------------------------- #
# anchor
# --------------------------------------------------------------------------- #


def cmd_anchor(state_dir: Path) -> int:
    state = anchoring.load_state(state_dir)
    operator_key = operator_key_from_env(state.get("chain_id"))
    batch = anchoring.anchor_unanchored(state_dir, operator_key)
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
    contract = anchoring.anchor_reader(state)

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

    guardian = sub.add_parser("guardian", help="guardian passkey administration")
    guardian_sub = guardian.add_subparsers(dest="guardian_command", required=True)
    pair = guardian_sub.add_parser(
        "pair-code", help="mint a single use pairing code directly in the approval store"
    )
    pair.add_argument(
        "--db",
        default=None,
        help="approval sqlite db (default: $AEGIS_DB_PATH or <state-dir>/approvals.db)",
    )
    pair.add_argument("--ttl", type=float, default=300.0, help="seconds the code lives")

    return parser


def cmd_pair_code(db_path: Path, ttl_seconds: float) -> int:
    """Operator path to a pairing code without the admin token: requires
    filesystem access to the approval store, which is already operator only."""
    import secrets
    import sqlite3

    from aegis.approval.store import ProposalStore
    from aegis.guardian_touch.store import GuardianStore

    if not db_path.exists():
        print(f"error: no approval store at {db_path}", file=sys.stderr)
        return 2
    ProposalStore(str(db_path))  # ensure the proposals table exists for the migration
    store = GuardianStore(str(db_path))
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    for _ in range(5):
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        try:
            store.create_pairing_code(code, ttl_seconds)
        except sqlite3.IntegrityError:
            continue
        print(code)
        return 0
    print("error: could not allocate a pairing code", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = Path(args.state_dir)
    try:
        if args.command == "anchor":
            return cmd_anchor(state_dir)
        if args.command == "verify":
            return cmd_verify(state_dir, args.decision_id, args.all)
        if args.command == "guardian" and args.guardian_command == "pair-code":
            db = args.db or os.environ.get("AEGIS_DB_PATH") or str(state_dir / "approvals.db")
            return cmd_pair_code(Path(db), args.ttl)
    except (StateError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
