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
from aegis.errors import GuardianMismatch, GuardianUnverified
from tests.conftest import ACCOUNTS, GUARDIAN, KEYS, OPERATOR, bearer, register_approver

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"


def write_state(deployment, tmp_path: Path, **overrides) -> dict:
    """state.json pointing at the shared anvil deployment (plus a fresh anchor)."""
    anchor = deployment["chain"].deploy("AuditAnchor", OPERATOR)
    state = {
        "rpc_url": deployment["rpc_url"],
        "chain_id": 31337,
        "operator_key": KEYS[0],
        "guardian": GUARDIAN,
        "anchor_address": anchor.address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "audit_key_file": str(tmp_path / "audit.key"),
    }
    state.update(overrides)
    (tmp_path / "state.json").write_text(json.dumps(state))
    return state


def chain_config(tmp_path: Path, guardian_key: str = KEYS[9]) -> ApiConfig:
    return ApiConfig(
        approval=ApprovalConfig(
            db_path=str(tmp_path / "approvals.db"),
            audit_log_path=str(tmp_path / "audit.jsonl"),
            audit_key_file=str(tmp_path / "audit.key"),
            policy_path=str(POLICY_PATH),
            guardian_key=guardian_key,
        ),
        state_dir=str(tmp_path),
        evals_report_path=str(tmp_path / "none.md"),
        approval_wait_seconds=30.0,
        approval_poll_seconds=0.05,
    )


@pytest.fixture()
def chain_app(deployment, tmp_path: Path):
    """API app whose state.json points at the shared anvil deployment."""
    write_state(deployment, tmp_path)
    return create_api_app(chain_config(tmp_path))


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

        # metrics now report the anchor and the live chain
        metrics = client.get("/metrics").json()
        assert metrics["last_anchor"]["batch_id"] == 0
        assert metrics["chain"]["configured"] is True
        assert metrics["chain"]["connected"] is True
        assert metrics["chain"]["chain_id"] == 31337

    def test_anchor_records_where_to_find_the_tx(self, chain_app, client: TestClient) -> None:
        """The batch carries chain/block coordinates; anvil has no explorer."""
        records = seed_records(chain_app)
        batch = client.post("/anchor").json()["batch"]

        assert batch["chain_id"] == 31337
        assert batch["chain_name"] == "anvil"
        assert batch["block_number"] > 0
        assert batch["anchored_at"].startswith("20")
        assert batch["tx_hash"].startswith("0x")
        assert batch["anchor_address"]
        assert batch["tx_url"] is None  # a dev chain has nothing to link to

        # verifying reports the same batch, so the console can link from a proof
        verify = client.get(f"/audit/verify/{records[0]['decision_id']}").json()
        assert verify["anchor"]["tx_hash"] == batch["tx_hash"]
        assert verify["anchor"]["block_number"] == batch["block_number"]

        chain = client.get("/metrics").json()["chain"]
        assert chain["chain_name"] == "anvil"
        assert chain["public"] is False
        assert chain["explorer_url"] is None
        assert chain["anchor_url"] is None

    def test_explorer_links_appear_when_the_chain_has_one(
        self, chain_app, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A public chain (or an explorer override) makes anchors trackable."""
        records = seed_records(chain_app, n=1)
        monkeypatch.setenv("AEGIS_EXPLORER_URL", "https://sepolia.basescan.org")

        batch = client.post("/anchor").json()["batch"]
        assert batch["tx_url"] == f"https://sepolia.basescan.org/tx/{batch['tx_hash']}"
        assert batch["anchor_url"] == (
            f"https://sepolia.basescan.org/address/{batch['anchor_address']}"
        )

        verify = client.get(f"/audit/verify/{records[0]['decision_id']}").json()
        assert verify["PROOF_OK"] is True
        assert verify["anchor"]["tx_url"] == batch["tx_url"]

        chain = client.get("/metrics").json()["chain"]
        assert chain["explorer_url"] == "https://sepolia.basescan.org"
        assert chain["anchor_url"] == batch["anchor_url"]

    def test_unanchored_verify_has_no_anchor_block(self, chain_app, client: TestClient) -> None:
        records = seed_records(chain_app, n=1)
        verify = client.get(f"/audit/verify/{records[0]['decision_id']}").json()
        assert verify["anchor"] is None

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


class TestGuardianBinding:
    """W1: the API binds its signer to the token's on chain guardian at startup (C8)."""

    def test_api_starts_when_guardian_matches(self, client: TestClient) -> None:
        chain = client.get("/metrics").json()["chain"]
        assert chain["guardian_verified"] is True
        assert chain["guardian_address"].lower() == GUARDIAN.lower()

    def test_api_refuses_start_on_guardian_mismatch(self, deployment, tmp_path: Path) -> None:
        """The token was deployed with account 9 as guardian; signing with key 0 is dead."""
        write_state(deployment, tmp_path)
        with pytest.raises(GuardianMismatch) as excinfo:
            create_api_app(chain_config(tmp_path, guardian_key=KEYS[0]))
        assert excinfo.value.expected.lower() == GUARDIAN.lower()
        assert excinfo.value.actual.lower() == ACCOUNTS[0].lower()
        assert "AEGIS_GUARDIAN_KEY" in str(excinfo.value)

    def test_api_refuses_start_when_chain_unreachable(self, deployment, tmp_path: Path) -> None:
        """Unreadable is not "no guardian": the service does not come up (C1, I5)."""
        write_state(deployment, tmp_path, rpc_url="http://127.0.0.1:9")  # discard port, closed
        with pytest.raises(GuardianUnverified) as excinfo:
            create_api_app(chain_config(tmp_path))
        assert "will not start" in str(excinfo.value)

    def test_api_refuses_start_when_token_has_no_code(self, deployment, tmp_path: Path) -> None:
        write_state(deployment, tmp_path, token_address=OPERATOR)  # an EOA, no contract
        with pytest.raises(GuardianUnverified, match="no contract code"):
            create_api_app(chain_config(tmp_path))

    def test_no_chain_state_means_nothing_to_bind(self, tmp_path: Path) -> None:
        """Without state.json there is no token; the API serves the chainless routes."""
        app = create_api_app(chain_config(tmp_path))
        chain = TestClient(app).get("/metrics").json()["chain"]
        assert chain["configured"] is False
        assert chain["guardian_verified"] is False
        assert chain["guardian_address"] is None


class TestCompliance:
    def test_party_status_reads_the_chain(self, client: TestClient) -> None:
        compliant = client.get(f"/compliance/{ACCOUNTS[1]}").json()
        assert compliant == {
            "address": ACCOUNTS[1],
            "known": True,
            "compliant": True,
            "frozen": False,
        }

        frozen = client.get(f"/compliance/{ACCOUNTS[4]}").json()
        assert frozen["known"] is True
        assert frozen["compliant"] is False
        assert frozen["frozen"] is True


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

        tester = bearer(register_approver(chain_app, "console-tester"))
        approve = client.post(
            f"/proposals/{decision_id}/approve", json={"comment": "reviewed"}, headers=tester
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
