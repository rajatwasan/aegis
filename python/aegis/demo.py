"""Headless end-to-end demo scenario (M8).

Deploys the Aegis suite on an already-running anvil, then drives the M5 batch
through the LangGraph agent with a scripted MockLLM: four small compliant
transfers auto-execute, one large transfer escalates and is auto-approved by the
demo (standing in for a human) so the guardian co-signs it, and a transfer to a
frozen address is denied. Every decision is written to the hash-chained audit
log. Finally the run's state is saved to ``<state-dir>/state.json`` so the
``aegis anchor`` and ``aegis verify`` CLIs can close the loop.

Invoked by ``scripts/demo.sh``; anvil's lifecycle is owned by that script.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from langgraph.types import Command
from web3 import Web3

from aegis import devchain
from aegis.agent import AegisRuntime, ChainClient, MockLLM, build_graph
from aegis.approval import ApprovalConfig, GuardianSigner, build_authorization, create_app
from aegis.audit import AuditLog, AuditSigner
from aegis.keys import guardian_key_from_env, operator_key_from_env
from aegis.policy import load_policy

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"

CHAIN_ID = 31337
THRESHOLD = 10_000

# the demo world is built from anvil's dev accounts; see aegis.devchain
ACCOUNTS = devchain.ACCOUNTS
KEYS = devchain.KEYS
OPERATOR = ACCOUNTS[devchain.OPERATOR_INDEX]
FROZEN_ACCOUNT = ACCOUNTS[devchain.FROZEN_INDEX]


def _rule(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m")


def deploy(
    chain: ChainClient,
    *,
    guardian: GuardianSigner,
    operator: str | None = None,
    chain_id: int = CHAIN_ID,
) -> dict[str, Any]:
    """Deploy the suite and seed a world: compliant parties, supply, one freeze.

    ``guardian`` is the signer the approval service will run with; its address
    becomes the token's guardian and it signs the seed mint and freeze. There is
    no default: the caller resolves the key (``AEGIS_GUARDIAN_KEY``, or the anvil
    dev key on a dev chain) so a public deployment can never be gated by a
    publicly known key. ``guardian.chain_id`` must equal ``chain_id``.

    ``operator`` defaults to anvil's account 0 for the local demo; a public-chain
    deployment passes its own funded address, which must own the registry (it is
    the account that writes claims) and hold the minted supply. ``chain_id`` goes
    into the guardian's EIP-712 domain, so it must match the live chain or
    on-chain signature checks reject every authorization.
    """
    if guardian.chain_id != chain_id:
        raise ValueError(
            f"guardian signer is bound to chain {guardian.chain_id}, deploying on {chain_id}"
        )
    operator = operator or OPERATOR
    registry = chain.deploy("ComplianceRegistry", operator)
    token = chain.deploy(
        "GuardedToken",
        "Aegis Guarded",
        "AGD",
        guardian.address,
        operator,
        registry.address,
        THRESHOLD,
    )
    anchor = chain.deploy("AuditAnchor", operator)
    print(f"  registry   {registry.address}")
    print(f"  token      {token.address}")
    print(f"  anchor     {anchor.address}")

    kyc_topic = registry.functions.TOPIC_KYC().call()
    compliant = [operator, *(ACCOUNTS[i] for i in range(4) if ACCOUNTS[i] != operator)]
    for party in compliant:
        chain.call_tx(registry.functions.setClaim(party, kyc_topic, True, 0))

    signer = guardian
    now = int(time.time())
    mint_auth = build_authorization(
        decision_id="demo-mint-operator",
        operation=2,
        token=token.address,
        from_addr="0x" + "0" * 40,
        to=operator,
        asset_class=0,
        amount=1_000_000,
        policy_hash="00" * 32,
        nonce=0,
        deadline=now + 3600,
    )
    chain.mint_with_authorization(token, mint_auth, signer.sign_authorization(mint_auth))
    freeze_auth = build_authorization(
        decision_id="demo-freeze-account4",
        operation=4,
        token=token.address,
        from_addr=FROZEN_ACCOUNT,
        to="0x" + "0" * 40,
        asset_class=0,
        amount=1,
        policy_hash="00" * 32,
        nonce=0,
        deadline=now + 3600,
    )
    chain.set_frozen(token, freeze_auth, signer.sign_authorization(freeze_auth))
    print("  minted 1,000,000 AGD to operator; froze account 4")
    return {"registry": registry, "token": token, "anchor": anchor}


def _transfer(token_addr: str, to: str, amount: int) -> dict[str, Any]:
    return {
        "tool": "propose_transfer",
        "args": {"token": token_addr, "from": OPERATOR, "to": to, "amount": amount},
    }


def run(rpc_url: str, state_dir: Path) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    _rule("[1/5] Deploying the Aegis suite on anvil")
    probe = Web3(Web3.HTTPProvider(rpc_url))
    chain_id = int(probe.eth.chain_id)
    chain = ChainClient(rpc_url, operator_key_from_env(chain_id))
    guardian_key = guardian_key_from_env(chain_id)
    guardian = GuardianSigner(guardian_key, chain_id)
    deployment = deploy(chain, guardian=guardian, chain_id=chain_id)
    token = deployment["token"]

    # the demo stands in for the human; its token lives only in this process
    demo_token = secrets.token_hex(16)
    config = ApprovalConfig(
        db_path=str(state_dir / "approvals.db"),
        audit_log_path=str(state_dir / "audit.jsonl"),
        audit_key_file=str(state_dir / "audit.key"),
        policy_path=str(POLICY_PATH),
        guardian_key=guardian_key,
        chain_id=chain_id,
        approver_tokens={"demo-operator": demo_token},
    )
    for stale in (state_dir / "approvals.db", state_dir / "audit.jsonl"):
        stale.unlink(missing_ok=True)
    approval = TestClient(create_app(config))
    audit_signer = AuditSigner.load_or_create(config.audit_key_file)
    audit = AuditLog(config.audit_log_path, audit_signer)
    runtime = AegisRuntime(
        policy=load_policy(POLICY_PATH),
        audit=audit,
        chain=chain,
        token=token,
        registry=deployment["registry"],
        approval_client=approval,
    )

    _rule("[2/5] Agent proposes a batch of operations (LLM is fully scripted)")
    script = [
        _transfer(token.address, ACCOUNTS[1], 1_000),
        _transfer(token.address, ACCOUNTS[2], 2_000),
        _transfer(token.address, ACCOUNTS[3], 3_000),
        _transfer(token.address, ACCOUNTS[1], 4_000),
        _transfer(token.address, ACCOUNTS[1], 50_000),  # escalates: above threshold
        _transfer(token.address, FROZEN_ACCOUNT, 10),  # denied: frozen party
        {"tool": "done", "args": {}},
    ]
    graph = build_graph(MockLLM(script=script), runtime)
    graph_config = {"configurable": {"thread_id": "demo"}}
    instructions = [f"operation {i}" for i in range(len(script))]

    state = graph.invoke({"instructions": instructions, "results": []}, graph_config)
    for result in state["results"]:
        effect = result.get("effect", "-")
        status = result.get("status")
        amount = result.get("proposal", {}).get("amount")
        to = result.get("proposal", {}).get("to")
        print(f"  {status:<16} effect={effect:<9} amount={amount} to={to}")

    pending = [r for r in state["results"] if r["status"] == "pending_approval"]
    assert len(pending) == 1, "expected exactly one escalation"
    decision_id = pending[0]["decision_id"]

    _rule("[3/5] Human approves the escalated transfer; guardian co-signs (EIP-712)")
    approved = approval.post(
        f"/proposals/{decision_id}/approve",
        json={"comment": "reviewed and approved"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    approved.raise_for_status()
    who = approved.json()["approvals"][-1]
    print(f"  approved decision {decision_id} as {who['approver']} (auth: {who['auth']})")
    state = graph.invoke(Command(resume="approved"), graph_config)
    resumed = [r for r in state["results"] if r.get("approval_status") == "approved"]
    print(f"  guardian-signed transfer executed: tx {resumed[0]['tx_hash']}")

    records = audit.records()
    verified = audit.verify(audit_signer.public_key_hex())
    _rule(
        f"[4/5] Audit log holds {len(records)} hash-chained records; chain verifies ({verified} ok)"
    )

    state_json = {
        "rpc_url": rpc_url,
        "chain_id": chain_id,
        "operator_address": chain.operator_address,
        "guardian": guardian.address,
        "anchor_address": deployment["anchor"].address,
        "token_address": token.address,
        "registry_address": deployment["registry"].address,
        "audit_log_path": config.audit_log_path,
        "audit_key_file": config.audit_key_file,
        "audit_public_key": audit_signer.public_key_hex(),
        "decision_ids": [r["decision_id"] for r in records],
    }
    (state_dir / "state.json").write_text(json.dumps(state_json, indent=2) + "\n")
    _rule("[5/5] State written; now run `aegis anchor` then `aegis verify`")
    print(f"  state -> {state_dir / 'state.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aegis-demo", description="Aegis end-to-end demo scenario"
    )
    parser.add_argument(
        "--rpc-url", default=os.environ.get("AEGIS_RPC_URL", "http://127.0.0.1:8545")
    )
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("AEGIS_STATE_DIR", str(REPO_ROOT / ".aegis" / "demo")),
    )
    args = parser.parse_args(argv)
    return run(args.rpc_url, Path(args.state_dir))


if __name__ == "__main__":
    raise SystemExit(main())
