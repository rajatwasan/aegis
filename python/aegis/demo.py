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
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from langgraph.types import Command

from aegis.agent import AegisRuntime, ChainClient, MockLLM, build_graph
from aegis.approval import ApprovalConfig, GuardianSigner, build_authorization, create_app
from aegis.approval.config import guardian_key_from_env
from aegis.audit import AuditLog, AuditSigner
from aegis.devkeys import ACCOUNTS, KEYS, address_of
from aegis.policy import load_policy

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"

CHAIN_ID = 31337
THRESHOLD = 10_000

# anvil's dev accounts (aegis.devkeys); this module runs only against a
# throwaway local chain, which is why it may name them (AGENTS.md S2)
OPERATOR = ACCOUNTS[0]
FROZEN_ACCOUNT = ACCOUNTS[4]


def _rule(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m")


def deploy(
    chain: ChainClient,
    *,
    guardian_key: str,
    operator: str | None = None,
    chain_id: int = CHAIN_ID,
) -> dict[str, Any]:
    """Deploy the suite and seed a world: compliant parties, supply, one freeze.

    ``guardian_key`` is the approval service's signing key: its address becomes
    the token's on chain guardian, and it signs the seed mint and freeze below.
    There is no default (AGENTS.md C3); every caller passes the key it will run
    the approval service with, so the binding check at API startup passes.

    ``operator`` defaults to anvil's account 0 for the local demo; a public-chain
    deployment passes its own funded address, which must own the registry (it is
    the account that writes claims) and hold the minted supply. ``chain_id`` goes
    into the guardian's EIP-712 domain, so it must match the live chain or
    on-chain signature checks reject every authorization.
    """
    operator = operator or OPERATOR
    guardian = address_of(guardian_key)
    registry = chain.deploy("ComplianceRegistry", operator)
    token = chain.deploy(
        "GuardedToken", "Aegis Guarded", "AGD", guardian, operator, registry.address, THRESHOLD
    )
    anchor = chain.deploy("AuditAnchor", operator)
    print(f"  registry   {registry.address}")
    print(f"  token      {token.address}")
    print(f"  anchor     {anchor.address}")

    kyc_topic = registry.functions.TOPIC_KYC().call()
    compliant = [operator, *(ACCOUNTS[i] for i in range(4) if ACCOUNTS[i] != operator)]
    for party in compliant:
        chain.call_tx(registry.functions.setClaim(party, kyc_topic, True, 0))

    signer = GuardianSigner(guardian_key, chain_id)
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


def run(rpc_url: str, state_dir: Path, guardian_key: str) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    _rule("[1/5] Deploying the Aegis suite on anvil")
    chain = ChainClient(rpc_url, KEYS[0])
    deployment = deploy(chain, guardian_key=guardian_key)
    token = deployment["token"]

    config = ApprovalConfig(
        db_path=str(state_dir / "approvals.db"),
        audit_log_path=str(state_dir / "audit.jsonl"),
        audit_key_file=str(state_dir / "audit.key"),
        policy_path=str(POLICY_PATH),
        guardian_key=guardian_key,
        chain_id=CHAIN_ID,
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
    approval.post(
        f"/proposals/{decision_id}/approve",
        json={"approver": "demo-operator", "comment": "reviewed and approved"},
    )
    print(f"  approved decision {decision_id}")
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
        "chain_id": CHAIN_ID,
        "operator_key": KEYS[0],
        "guardian": address_of(guardian_key),
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
    # the demo's approval service signs with AEGIS_GUARDIAN_KEY; scripts/demo.sh
    # sets anvil's dev key 9 plus AEGIS_ALLOW_DEV_KEYS=true for the throwaway chain
    return run(args.rpc_url, Path(args.state_dir), guardian_key_from_env())


if __name__ == "__main__":
    raise SystemExit(main())
