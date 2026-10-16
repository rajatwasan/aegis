"""M5 end-to-end integration on anvil.

Batch of 5 transfers: 4 auto-allowed and executed on-chain, 1 escalated ->
approved via the API -> guardian signature -> executed. A 6th transfer to a
frozen address is denied. Every decision lands in the audit log.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from aegis.agent import AegisRuntime, MockLLM, build_graph
from aegis.approval import ApprovalConfig, create_app
from aegis.audit import AuditLog, AuditSigner
from aegis.policy import load_policy
from tests.conftest import (
    ACCOUNTS,
    FROZEN_ACCOUNT,
    KEYS,
    OPERATOR,
    REPO_ROOT,
    bearer,
    register_approver,
)

POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"


@pytest.fixture()
def stack(deployment, tmp_path: Path):
    """Approval service + runtime + graph wired to the deployed contracts."""
    token = deployment["token"]
    config = ApprovalConfig(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(POLICY_PATH),
        guardian_key=KEYS[9],
        chain_id=31337,
    )
    approval_app = create_app(config)
    approval_client = TestClient(approval_app)
    ops1 = bearer(register_approver(approval_app, "ops-1"))
    audit_signer = AuditSigner.load_or_create(tmp_path / "audit.key")
    audit = AuditLog(tmp_path / "audit.jsonl", audit_signer)
    runtime = AegisRuntime(
        policy=load_policy(POLICY_PATH),
        audit=audit,
        chain=deployment["chain"],
        token=token,
        registry=deployment["registry"],
        approval_client=approval_client,
    )
    return {
        "runtime": runtime,
        "approval": approval_client,
        "ops1": ops1,  # W2: the human's credential; the runtime never holds it
        "audit": audit,
        "audit_public": audit_signer.public_key_hex(),
        "token": token,
    }


def transfer_action(token: str, to: str, amount: int) -> dict:
    return {
        "tool": "propose_transfer",
        "args": {"token": token, "from": OPERATOR, "to": to, "amount": amount},
    }


def test_end_to_end_batch(stack) -> None:
    token = stack["token"]
    runtime = stack["runtime"]
    balances_before = {i: token.functions.balanceOf(ACCOUNTS[i]).call() for i in (1, 2, 3, 4)}

    script = [
        transfer_action(token.address, ACCOUNTS[1], 1_000),
        transfer_action(token.address, ACCOUNTS[2], 2_000),
        transfer_action(token.address, ACCOUNTS[3], 3_000),
        transfer_action(token.address, ACCOUNTS[1], 4_000),
        transfer_action(token.address, ACCOUNTS[1], 50_000),  # escalates
        transfer_action(token.address, FROZEN_ACCOUNT, 10),  # denied: frozen
        {"tool": "done", "args": {}},
    ]
    graph = build_graph(MockLLM(script=script), runtime)
    config = {"configurable": {"thread_id": "e2e"}}
    instructions = [f"instruction {i}" for i in range(7)]

    state = graph.invoke({"instructions": instructions, "results": []}, config)

    # paused at the escalation
    assert "__interrupt__" in state
    pending = [r for r in state["results"] if r["status"] == "pending_approval"]
    assert len(pending) == 1
    decision_id = pending[0]["decision_id"]

    # 4 small transfers already executed on-chain
    executed = [r for r in state["results"] if r["status"] == "executed"]
    assert len(executed) == 4
    assert token.functions.balanceOf(ACCOUNTS[2]).call() == balances_before[2] + 2_000

    # the runtime (the agent's side) cannot resolve its own escalation: its
    # approval client carries no approver credential, so approve is 401 and
    # nothing is recorded (W2, AGENTS.md C6)
    self_approve = stack["runtime"].approval.post(
        f"/proposals/{decision_id}/approve", json={"comment": "agent says yes"}
    )
    assert self_approve.status_code == 401
    assert stack["approval"].get(f"/proposals/{decision_id}").json()["approvals"] == []

    # human approves via the API
    res = stack["approval"].post(
        f"/proposals/{decision_id}/approve", json={"comment": "reviewed"}, headers=stack["ops1"]
    )
    assert res.json()["status"] == "approved"

    # resume the graph: guardian-signed execution + the denied 6th transfer
    state = graph.invoke(Command(resume="approved"), config)
    assert "__interrupt__" not in state

    resumed = [r for r in state["results"] if r.get("approval_status") == "approved"]
    assert len(resumed) == 1 and resumed[0]["status"] == "executed"
    assert (
        token.functions.balanceOf(ACCOUNTS[1]).call() == balances_before[1] + 1_000 + 4_000 + 50_000
    )

    denied = [r for r in state["results"] if r["status"] == "denied"]
    assert len(denied) == 1
    assert denied[0]["matched_rules"] == ["deny-frozen-party"]
    assert token.functions.balanceOf(FROZEN_ACCOUNT).call() == balances_before[4]

    # every decision is in the audit log: 4 allow + 1 escalate + 1 approve
    # (service) + 1 resumed execution + 1 deny = 8 records, chain verifies
    records = stack["audit"].records()
    assert len(records) == 8
    assert stack["audit"].verify(stack["audit_public"]) == 8
    statuses = [r["policy_result"].get("status") for r in records]
    assert statuses.count("executed") == 5
    assert statuses.count("denied") == 1
    assert statuses.count("pending_approval") == 1


def test_rejected_escalation_never_executes(stack) -> None:
    token = stack["token"]
    runtime = stack["runtime"]
    before = token.functions.balanceOf(ACCOUNTS[3]).call()

    script = [
        transfer_action(token.address, ACCOUNTS[3], 99_000),
        {"tool": "done", "args": {}},
    ]
    graph = build_graph(MockLLM(script=script), runtime)
    config = {"configurable": {"thread_id": "reject"}}

    state = graph.invoke({"instructions": ["a", "b"], "results": []}, config)
    decision_id = state["results"][0]["decision_id"]
    stack["approval"].post(f"/proposals/{decision_id}/reject", json={}, headers=stack["ops1"])

    state = graph.invoke(Command(resume="rejected"), config)
    outcome = state["results"][-1]
    assert outcome["status"] == "rejected"
    assert "tx_hash" not in outcome
    assert token.functions.balanceOf(ACCOUNTS[3]).call() == before


def test_direct_bypass_attempt_reverts_on_chain(stack) -> None:
    """Even skipping the whole agent stack, the chain refuses gated transfers."""
    token = stack["token"]
    chain = stack["runtime"].chain
    with pytest.raises(RuntimeError, match="reverted"):
        chain.transfer(token, ACCOUNTS[1], 50_000)  # above threshold, no authorization
