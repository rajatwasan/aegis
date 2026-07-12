"""Deploy a fresh Aegis suite for the dev stack and write state.json.

``scripts/dev-stack.sh`` runs this once against a live anvil before starting
the API + vite; the Guardian Console then operates on a real chain. The same
deployment shape as the demo (operator funded, accounts 0-3 compliant,
account 4 frozen) but with no pre-run agent batch — the console starts clean.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aegis.agent import ChainClient
from aegis.demo import ACCOUNTS, CHAIN_ID, KEYS, deploy

REPO_ROOT = Path(__file__).resolve().parents[2]


def run(rpc_url: str, state_dir: Path) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("approvals.db", "audit.jsonl", "anchors.json"):
        (state_dir / stale).unlink(missing_ok=True)

    chain = ChainClient(rpc_url, KEYS[0])
    deployment = deploy(chain)

    state = {
        "rpc_url": rpc_url,
        "chain_id": CHAIN_ID,
        "operator_key": KEYS[0],
        "guardian": ACCOUNTS[9],
        "anchor_address": deployment["anchor"].address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "audit_log_path": str(state_dir / "audit.jsonl"),
        "audit_key_file": str(state_dir / "audit.key"),
    }
    (state_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")
    print(f"dev stack state -> {state_dir / 'state.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aegis-devstack")
    parser.add_argument(
        "--rpc-url", default=os.environ.get("AEGIS_RPC_URL", "http://127.0.0.1:8545")
    )
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("AEGIS_STATE_DIR", str(REPO_ROOT / ".aegis" / "dev")),
    )
    args = parser.parse_args(argv)
    return run(args.rpc_url, Path(args.state_dir))


if __name__ == "__main__":
    raise SystemExit(main())
