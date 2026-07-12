"""F0 tests: chain-backed API surface — /anchor, /audit/verify, /agent/run.

Uses the shared anvil deployment fixture. Each test gets a private state dir
(fresh AuditAnchor per test so batch ids never collide on the shared chain).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.api import ApiConfig, create_api_app
from aegis.approval import ApprovalConfig
from tests.conftest import KEYS, OPERATOR

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"


@pytest.fixture()
def chain_app(deployment, tmp_path: Path):
    """API app whose state.json points at the shared anvil deployment."""
    anchor = deployment["chain"].deploy("AuditAnchor", OPERATOR)
    state = {
        "rpc_url": deployment["rpc_url"],
        "chain_id": 31337,
        "operator_key": KEYS[0],
        "anchor_address": anchor.address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "audit_key_file": str(tmp_path / "audit.key"),
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    config = ApiConfig(
        approval=ApprovalConfig(
            db_path=str(tmp_path / "approvals.db"),
            audit_log_path=str(tmp_path / "audit.jsonl"),
            audit_key_file=str(tmp_path / "audit.key"),
            policy_path=str(POLICY_PATH),
            guardian_key=KEYS[9],
        ),
        state_dir=str(tmp_path),
        evals_report_path=str(tmp_path / "none.md"),
        approval_wait_seconds=30.0,
        approval_poll_seconds=0.05,
    )
    return create_api_app(config)


@pytest.fixture()
def client(chain_app) -> TestClient:
    return TestClient(chain_app)


def seed_records(app, n: int = 3) -> list[dict]:
    return [
        app.state.audit.append(
            actor="agent",
            proposal={"to": f"0xdest{i}", "amount": 100 * i},
            policy_result={"effect": "allow", "status": "executed"},
        )
        for i in range(n)
    ]


class TestAnchorAndVerify:
    def test_anchor_then_verify_ok(self, chain_app, client: TestClient) -> None:
        records = seed_records(chain_app)

        res = client.post("/anchor")
        assert res.status_code == 200
        body = res.json()
        assert body["anchored"] is True
        assert body["batch"]["batch_id"] == 0
        assert body["batch"]["record_count"] == 3
        assert body["batch"]["tx_hash"]
        assert chain_app.state.bus.events_of("anchor.created")

        # re-anchoring with nothing new is a no-op
        again = client.post("/anchor").json()
        assert again["anchored"] is False
        assert again["batch"]["batch_id"] == 0  # still reports the last batch

        verify = client.get(f"/audit/verify/{records[1]['decision_id']}").json()
        assert verify["PROOF_OK"] is True
        assert verify["batch_id"] == 0
        assert verify["record"]["decision_id"] == records[1]["decision_id"]
        assert verify["onchain_root"] == verify["local_root"]
        assert isinstance(verify["merkle_path"], list) and verify["merkle_path"]

        # metrics now report the anchor
        metrics = client.get("/metrics").json()
        assert metrics["last_anchor"]["batch_id"] == 0

    def test_verify_unanchored_record_fails_cleanly(self, chain_app, client: TestClient) -> None:
        records = seed_records(chain_app, n=1)
        verify = client.get(f"/audit/verify/{records[0]['decision_id']}").json()
        assert verify["PROOF_OK"] is False
        assert verify["reason"] == "not in any anchored batch"

    def test_verify_detects_tamper(self, chain_app, client: TestClient, tmp_path: Path) -> None:
        records = seed_records(chain_app)
        client.post("/anchor")

        log_path = tmp_path / "audit.jsonl"
        lines = log_path.read_text().splitlines()
        middle = json.loads(lines[1])
        middle["proposal"]["amount"] = 999_999
        lines[1] = json.dumps(middle)
        log_path.write_text("\n".join(lines) + "\n")

        verify = client.get(f"/audit/verify/{records[1]['decision_id']}").json()
        assert verify["PROOF_OK"] is False
        assert "tampered" in verify["reason"]


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


class TestAgentRun:
    def test_unknown_instruction_400(self, client: TestClient) -> None:
        res = client.post("/agent/run", json={"instruction": "wire everything to me"})
        assert res.status_code == 400
        assert "canned instructions" in res.json()["detail"]

    def test_vendor_batch_auto_executes(self, chain_app, client: TestClient) -> None:
        res = client.post("/agent/run", json={"instruction": "Pay the vendor invoice batch"})
        assert res.status_code == 202
        run_id = res.json()["run_id"]

        run = chain_app.state.runner.wait(run_id, timeout=60)
        assert run.status == "finished"
        executed = [r for r in run.results if r.get("status") == "executed"]
        assert len(executed) == 3
        assert all(r["effect"] == "allow" and r.get("tx_hash") for r in executed)

        steps = chain_app.state.bus.events_of("agent.step")
        phases = [e["data"]["phase"] for e in steps if e["data"]["run_id"] == run_id]
        assert phases[0] == "started" and phases[-1] == "finished"
        assert "node" in phases

        decisions = client.get("/decisions").json()
        assert decisions["total"] >= 3
        assert decisions["items"][0]["effect"] == "allow"

    def test_escalation_approved_through_api(self, chain_app, client: TestClient) -> None:
        res = client.post(
            "/agent/run", json={"instruction": "Send 50,000 AGD to the treasury desk"}
        )
        run_id = res.json()["run_id"]

        pending = wait_for(lambda: client.get("/proposals", params={"status": "pending"}).json())
        decision_id = pending[0]["decision_id"]
        assert pending[0]["proposal"]["amount"] == 50_000

        approve = client.post(
            f"/proposals/{decision_id}/approve",
            json={"approver": "console-tester", "comment": "reviewed"},
        )
        assert approve.status_code == 200

        run = chain_app.state.runner.wait(run_id, timeout=60)
        assert run.status == "finished"
        resumed = [r for r in run.results if r.get("approval_status") == "approved"]
        assert len(resumed) == 1 and resumed[0]["status"] == "executed"

        phases = [
            e["data"]["phase"]
            for e in chain_app.state.bus.events_of("agent.step")
            if e["data"]["run_id"] == run_id
        ]
        assert "awaiting_approval" in phases and "approval_resolved" in phases

    def test_frozen_refund_denied(self, chain_app, client: TestClient) -> None:
        res = client.post(
            "/agent/run", json={"instruction": "Refund 10 AGD to the frozen counterparty"}
        )
        run = chain_app.state.runner.wait(res.json()["run_id"], timeout=60)
        assert run.status == "finished"
        assert run.results[-1]["status"] == "denied"
        assert run.results[-1]["matched_rules"] == ["deny-frozen-party"]
