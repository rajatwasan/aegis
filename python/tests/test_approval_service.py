"""M4 tests: approval service API — idempotency, TTL expiry, dual control."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.approval import ApprovalConfig, create_app
from aegis.audit import AuditLog, AuditSigner
from tests.helpers import bearer, dev_approval_config

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_config(tmp_path: Path, **overrides) -> ApprovalConfig:
    return dev_approval_config(tmp_path, **overrides)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_config(tmp_path)))


def proposal_body(**overrides) -> dict:
    base = {
        "operation": 1,
        "token": TOKEN,
        "from": ALICE,
        "to": BOB,
        "asset_class": 0,
        "amount": 50_000,
        "policy_result": {"effect": "escalate", "matched_rules": ["escalate-large-transfer"]},
    }
    base.update(overrides)
    return base


class TestSubmission:
    def test_submit_creates_pending(self, client: TestClient) -> None:
        res = client.post("/proposals", json=proposal_body())
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "pending"
        assert body["decision_id"]

    def test_idempotent_resubmission_returns_same_proposal(self, client: TestClient) -> None:
        headers = {"Idempotency-Key": "req-1"}
        first = client.post("/proposals", json=proposal_body(), headers=headers)
        second = client.post("/proposals", json=proposal_body(), headers=headers)
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["decision_id"] == first.json()["decision_id"]
        assert len(client.get("/proposals").json()) == 1

    def test_different_keys_create_distinct_proposals(self, client: TestClient) -> None:
        a = client.post("/proposals", json=proposal_body(), headers={"Idempotency-Key": "a"})
        b = client.post("/proposals", json=proposal_body(), headers={"Idempotency-Key": "b"})
        assert a.json()["decision_id"] != b.json()["decision_id"]

    def test_get_unknown_id_404(self, client: TestClient) -> None:
        assert client.get("/proposals/nope").status_code == 404

    def test_list_filters_by_status(self, client: TestClient) -> None:
        client.post("/proposals", json=proposal_body())
        assert len(client.get("/proposals", params={"status": "pending"}).json()) == 1
        assert len(client.get("/proposals", params={"status": "approved"}).json()) == 0


class TestApproval:
    def test_approve_signs_authorization(self, client: TestClient, tmp_path: Path) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(
            f"/proposals/{decision_id}/approve",
            json={"comment": "looks fine"},
            headers=bearer("ops-1"),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "approved"
        assert body["signature"].startswith("0x") and len(body["signature"]) == 132
        auth = body["authorization"]
        assert auth["from"] == ALICE and auth["to"] == BOB and auth["amount"] == 50_000
        assert auth["deadline"] > 0

        # resolution landed in the audit log, chained and signed
        signer = AuditSigner.load_or_create(tmp_path / "audit.key")
        log = AuditLog(tmp_path / "audit.jsonl", signer)
        assert log.verify(signer.public_key_hex()) == 1
        record = log.records()[0]
        assert record["decision_id"] == decision_id
        assert record["human_action"]["action"] == "approved"

    def test_reject(self, client: TestClient) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(
            f"/proposals/{decision_id}/reject", json={"comment": "no"}, headers=bearer("ops-1")
        )
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"
        assert res.json()["signature"] is None

    def test_approve_after_reject_conflicts(self, client: TestClient) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        client.post(f"/proposals/{decision_id}/reject", json={}, headers=bearer("ops-1"))
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-2"))
        assert res.status_code == 409

    def test_nonces_increment(self, client: TestClient) -> None:
        ids = [client.post("/proposals", json=proposal_body()).json()["decision_id"] for _ in "ab"]
        nonces = []
        for decision_id in ids:
            client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
            nonces.append(client.get(f"/proposals/{decision_id}").json()["authorization"]["nonce"])
        assert nonces[0] != nonces[1]


class TestExpiry:
    def test_pending_proposal_expires_after_ttl(self, tmp_path: Path) -> None:
        client = TestClient(create_app(make_config(tmp_path, ttl_seconds=0.0)))
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.get(f"/proposals/{decision_id}")
        assert res.json()["status"] == "expired"

    def test_expired_proposal_cannot_be_approved(self, tmp_path: Path) -> None:
        client = TestClient(create_app(make_config(tmp_path, ttl_seconds=0.0)))
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        assert res.status_code == 409

    def test_expiry_writes_audit_record(self, tmp_path: Path) -> None:
        client = TestClient(create_app(make_config(tmp_path, ttl_seconds=0.0)))
        client.post("/proposals", json=proposal_body())
        client.get("/proposals")  # triggers sweep
        signer = AuditSigner.load_or_create(tmp_path / "audit.key")
        log = AuditLog(tmp_path / "audit.jsonl", signer)
        records = log.records()
        assert len(records) == 1
        assert records[0]["human_action"]["action"] == "expired"


class TestDualControl:
    @pytest.fixture()
    def dual_client(self, tmp_path: Path) -> TestClient:
        return TestClient(create_app(make_config(tmp_path, dual_control=True)))

    def test_first_approval_keeps_pending(self, dual_client: TestClient) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = dual_client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1")
        )
        assert res.json()["status"] == "pending"
        assert res.json()["signature"] is None

    def test_same_approver_twice_rejected(self, dual_client: TestClient) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        res = dual_client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1")
        )
        assert res.status_code == 409

    def test_two_distinct_approvers_sign(self, dual_client: TestClient) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        res = dual_client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-2")
        )
        assert res.json()["status"] == "approved"
        assert res.json()["signature"] is not None
        assert res.json()["resolution"]["approvers"] == [
            {"approver": "ops-1", "auth": "token"},
            {"approver": "ops-2", "auth": "token"},
        ]


class TestHtmlPage:
    def test_index_serves_page(self, client: TestClient) -> None:
        res = client.get("/")
        assert res.status_code == 200
        assert "pending approvals" in res.text
