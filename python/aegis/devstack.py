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
from aegis.approval.config import DEV_KEYS_OPT_IN, guardian_key_from_env
from aegis.approval.identity import hash_token, new_token
from aegis.approval.store import ProposalStore
from aegis.demo import deploy
from aegis.devkeys import KEYS, address_of
from aegis.errors import ConfigError

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
    if "parties" not in state:
        return False  # written before W6: the console could not address its world
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


DEV_APPROVER_ID = "dev"
DEV_APPROVER_TOKEN_FILE = "dev-approver.token"  # git ignored; local dev chains only


def ensure_dev_approver(state_dir: Path) -> None:
    """On a local dev chain, make sure one approver exists and its token is on disk.

    The token file is what the console (and Playwright) read to sign in. It is
    written once, mode 0600, and never printed again; a hosted deployment gets
    its approvers from ``aegis approver add`` instead.
    """
    store = ProposalStore(str(state_dir / "approvals.db"))
    token_path = state_dir / DEV_APPROVER_TOKEN_FILE
    if store.get_approver(DEV_APPROVER_ID) is not None:
        if token_path.exists():
            print(f"dev approver '{DEV_APPROVER_ID}' present; token in {token_path}")
        else:
            print(
                f"dev approver '{DEV_APPROVER_ID}' exists but {token_path} is gone; "
                "add another with `aegis approver add <id>`"
            )
        return
    token = new_token()
    store.add_approver(DEV_APPROVER_ID, "Dev approver", hash_token(token))
    token_path.touch(mode=0o600)
    token_path.write_text(token + "\n")
    print(f"dev approver '{DEV_APPROVER_ID}' created; token written to {token_path}")


def resolve_operator_key(explicit: str | None, environ: dict[str, str] | None = None) -> str:
    """The deployer key: explicit, or anvil account 0 only when dev keys are opted in.

    There is no silent fallback to a public key (AGENTS.md C3). The dev
    scripts opt in; a hosted deployment must pass its own funded key.
    """
    if explicit:
        return explicit
    env = os.environ if environ is None else environ
    if env.get(DEV_KEYS_OPT_IN, "").strip().lower() == "true":
        return KEYS[0]
    raise ConfigError(
        "AEGIS_DEPLOYER_KEY (or --operator-key) is required to deploy; set "
        f"{DEV_KEYS_OPT_IN}=true to use anvil account 0 on a local dev chain"
    )


def run(
    rpc_url: str,
    state_dir: Path,
    guardian_key: str,
    operator_key: str | None = None,
    reuse: bool = False,
) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    operator_key = resolve_operator_key(operator_key)
    guardian = address_of(guardian_key)

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
            if str(existing.get("guardian", "")).lower() != guardian.lower():
                # a reused world whose token answers to another key is not
                # reusable: the approval service could never sign for it (C8)
                raise DeployError(
                    f"existing deployment has guardian {existing.get('guardian')} but "
                    f"AEGIS_GUARDIAN_KEY derives {guardian}; redeploy without --reuse "
                    "or restore the original key"
                )
            print(f"reusing {meta.name} deployment: anchor {existing['anchor_address']}")
            print(f"dev stack state -> {existing_path} (audit log preserved)")
            if not meta.public:
                ensure_dev_approver(state_dir)
            return 0

    # a fresh deployment is a fresh world: old proposals, audit records and
    # anchors point at contracts that no longer exist
    for stale in ("approvals.db", "audit.jsonl", "anchors.json"):
        (state_dir / stale).unlink(missing_ok=True)

    print(f"deploying Aegis suite on {meta.name} (chain {chain_id}) as {operator}")
    deployment = deploy(chain, guardian_key=guardian_key, operator=operator, chain_id=chain_id)

    state = {
        "rpc_url": rpc_url,
        "chain_id": chain_id,
        "chain_name": meta.name,
        "explorer_url": meta.explorer_url,
        "public": meta.public,
        "operator_key": operator_key,
        "operator_address": operator,
        "guardian": guardian,
        "anchor_address": deployment["anchor"].address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "parties": deployment["parties"],
        "deployed_block": chain.w3.eth.block_number,
        "audit_log_path": str(state_dir / "audit.jsonl"),
        "audit_key_file": str(state_dir / "audit.key"),
    }
    existing_path.write_text(json.dumps(state, indent=2) + "\n")
    print(f"dev stack state -> {existing_path}")
    if meta.explorer_url:
        print(f"  anchor contract {meta.explorer_url}/address/{state['anchor_address']}")
    if not meta.public:
        (state_dir / DEV_APPROVER_TOKEN_FILE).unlink(missing_ok=True)  # fresh world, fresh token
        ensure_dev_approver(state_dir)
    else:
        print("public chain: create approvers with `aegis approver add <id>` on this machine")
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
        guardian_key = guardian_key_from_env()
        return run(args.rpc_url, Path(args.state_dir), guardian_key, args.operator_key, args.reuse)
    except (DeployError, ConfigError) as exc:
        # a readable line, not a traceback: deploy/start.sh reads the exit code
        # and falls back to a local anvil
        print(f"devstack: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
