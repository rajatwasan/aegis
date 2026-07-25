"""Deploy an Aegis suite against a live chain and write state.json.

``scripts/dev-stack.sh`` runs this once against a local anvil before starting
the API + vite; ``deploy/start.sh`` runs the same code against a public testnet
(Base Sepolia) so anchored roots land somewhere a third party can inspect. The
deployment shape matches the demo (operator funded and compliant, accounts 1-3
compliant, account 4 frozen) with no pre-run agent batch — the console starts
clean.

On a public chain the operator key must already hold native gas; ``--reuse``
keeps an existing deployment (and its audit log) across restarts instead of
paying to redeploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from web3 import Web3

from aegis import chains
from aegis.agent import ChainClient
from aegis.demo import ACCOUNTS, KEYS, deploy

REPO_ROOT = Path(__file__).resolve().parents[2]

#: below this the operator cannot fund a deploy + a few anchors
MIN_OPERATOR_WEI = 10**15  # 0.001 ETH


class DeployError(RuntimeError):
    """The target chain is unusable (unreachable, or the operator is broke)."""


def _detect_chain_id(rpc_url: str) -> int:
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    try:
        return int(w3.eth.chain_id)
    except Exception as exc:  # noqa: BLE001 - any RPC failure means "unusable"
        raise DeployError(f"cannot reach {chains.redact_rpc_url(rpc_url)}: {exc}") from exc


def _reusable(state: dict[str, Any], chain: ChainClient, chain_id: int) -> bool:
    """True when state.json already describes a live deployment on this chain.

    Every contract address must still hold code — a fresh anvil (or a different
    chain) answers with empty code, which means the recorded world is gone.
    """
    if state.get("chain_id") != chain_id:
        return False
    try:
        for key in ("anchor_address", "token_address", "registry_address"):
            address = state.get(key)
            if not address:
                return False
            if chain.w3.eth.get_code(Web3.to_checksum_address(address)) in (b"", None):
                return False
    except Exception:  # noqa: BLE001 - RPC hiccup: redeploy rather than trust it
        return False
    return True


def run(
    rpc_url: str,
    state_dir: Path,
    operator_key: str | None = None,
    reuse: bool = False,
) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    operator_key = operator_key or KEYS[0]

    chain_id = _detect_chain_id(rpc_url)
    meta = chains.chain_meta(chain_id, chains.explorer_from_env())
    chain = ChainClient(rpc_url, operator_key)
    operator = chain.operator_address

    if meta.public:
        balance = chain.w3.eth.get_balance(operator)
        if balance < MIN_OPERATOR_WEI:
            raise DeployError(
                f"operator {operator} holds {Web3.from_wei(balance, 'ether')} native token "
                f"on {meta.name} — fund it before deploying"
            )

    existing_path = state_dir / "state.json"
    if reuse and existing_path.exists():
        existing = json.loads(existing_path.read_text())
        if _reusable(existing, chain, chain_id):
            print(f"reusing {meta.name} deployment: anchor {existing['anchor_address']}")
            print(f"dev stack state -> {existing_path} (audit log preserved)")
            return 0

    # a fresh deployment is a fresh world: old proposals, audit records and
    # anchors point at contracts that no longer exist
    for stale in ("approvals.db", "audit.jsonl", "anchors.json"):
        (state_dir / stale).unlink(missing_ok=True)

    print(f"deploying Aegis suite on {meta.name} (chain {chain_id}) as {operator}")
    deployment = deploy(chain, operator=operator, chain_id=chain_id)

    state = {
        "rpc_url": rpc_url,
        "chain_id": chain_id,
        "chain_name": meta.name,
        "explorer_url": meta.explorer_url,
        "public": meta.public,
        "operator_key": operator_key,
        "operator_address": operator,
        "guardian": ACCOUNTS[9],
        "anchor_address": deployment["anchor"].address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "deployed_block": chain.w3.eth.block_number,
        "audit_log_path": str(state_dir / "audit.jsonl"),
        "audit_key_file": str(state_dir / "audit.key"),
    }
    existing_path.write_text(json.dumps(state, indent=2) + "\n")
    print(f"dev stack state -> {existing_path}")
    if meta.explorer_url:
        print(f"  anchor contract {meta.explorer_url}/address/{state['anchor_address']}")
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
    parser.add_argument(
        "--operator-key",
        default=os.environ.get("AEGIS_DEPLOYER_KEY"),
        help="funded key that deploys and sends anchors (default: anvil account 0)",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="keep an existing deployment on this chain instead of redeploying",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.rpc_url, Path(args.state_dir), args.operator_key, args.reuse)
    except DeployError as exc:
        # a readable line, not a traceback: deploy/start.sh reads the exit code
        # and falls back to a local anvil
        print(f"devstack: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
