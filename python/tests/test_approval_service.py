"""M4 tests: approval service API — idempotency, TTL expiry, dual control.

W2 (spec docs/specs/2026-10-hardening.md): approve and reject require an
approver token; the identity on approvals and audit records comes from the
token, never from the body.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.approval import ApprovalConfig, create_app
from aegis.audit import AuditLog, AuditSigner
from tests.conftest import KEYS, bearer, register_approver

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_config(tmp_path: Path, **overrides) -> ApprovalConfig:
    defaults = dict(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(REPO_ROOT / "policies" / "default.yaml"),
        ttl_seconds=900.0,
        guardian_key=KEYS[9],  # W1: no default; tests say which dev key they sign with
    )
    defaults.update(overrides)
    return ApprovalConfig(**defaults)


@pytest.fixture()
def app(tmp_path: Path):
    return create_app(make_config(tmp_path))


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def ops1(app) -> dict[str, str]:
    """Bearer headers for approver ops-1 (W2: identity comes from the token)."""
    return bearer(register_approver(app, "ops-1", "Ops One"))


@pytest.fixture()
def ops2(app) -> dict[str, str]:
    return bearer(register_approver(app, "ops-2", "Ops Two"))


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


def audit_log(tmp_path: Path) -> tuple[AuditLog, AuditSigner]:
    signer = AuditSigner.load_or_create(tmp_path / "audit.key")
    return AuditLog(tmp_path / "audit.jsonl", signer), signer


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
    def test_approve_signs_authorization(
        self, client: TestClient, tmp_path: Path, ops1: dict
    ) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(
            f"/proposals/{decision_id}/approve", json={"comment": "looks fine"}, headers=ops1
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "approved"
        assert body["signature"].startswith("0x") and len(body["signature"]) == 132
        auth = body["authorization"]
        assert auth["from"] == ALICE and auth["to"] == BOB and auth["amount"] == 50_000
        assert auth["deadline"] > 0

        # resolution landed in the audit log, chained and signed
        log, signer = audit_log(tmp_path)
        assert log.verify(signer.public_key_hex()) == 1
        record = log.records()[0]
        assert record["decision_id"] == decision_id
        assert record["human_action"]["action"] == "approved"

    def test_reject(self, client: TestClient, ops1: dict) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(f"/proposals/{decision_id}/reject", json={"comment": "no"}, headers=ops1)
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"
        assert res.json()["signature"] is None

    def test_approve_after_reject_conflicts(
        self, client: TestClient, ops1: dict, ops2: dict
    ) -> None:
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        client.post(f"/proposals/{decision_id}/reject", json={}, headers=ops1)
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops2)
        assert res.status_code == 409

    def test_nonces_increment(self, client: TestClient, ops1: dict) -> None:
        ids = [client.post("/proposals", json=proposal_body()).json()["decision_id"] for _ in "ab"]
        nonces = []
        for decision_id in ids:
            client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
            nonces.append(client.get(f"/proposals/{decision_id}").json()["authorization"]["nonce"])
        assert nonces[0] != nonces[1]


class TestApproverIdentity:
    """W2: who approved is established by the credential, and nothing moves without one."""

    def _pending(self, client: TestClient) -> str:
        return client.post("/proposals", json=proposal_body()).json()["decision_id"]

    def _assert_nothing_happened(self, client: TestClient, decision_id: str, tmp_path: Path):
        row = client.get(f"/proposals/{decision_id}").json()
        assert row["status"] == "pending"
        assert row["approvals"] == []
        assert row["signature"] is None
        log, _ = audit_log(tmp_path)
        assert log.records() == []

    def test_approve_without_token_401(self, client: TestClient, tmp_path: Path) -> None:
        decision_id = self._pending(client)
        res = client.post(f"/proposals/{decision_id}/approve", json={"comment": "x"})
        assert res.status_code == 401
        assert res.headers["www-authenticate"].startswith("Bearer")
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_approve_with_unknown_token_401(self, client: TestClient, tmp_path: Path) -> None:
        decision_id = self._pending(client)
        res = client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("not-a-real-token")
        )
        assert res.status_code == 401
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_approve_with_revoked_token_401(self, app, client: TestClient, tmp_path: Path) -> None:
        token = register_approver(app, "ops-gone")
        app.state.store.revoke_approver("ops-gone")
        decision_id = self._pending(client)
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer(token))
        assert res.status_code == 401
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_malformed_authorization_header_401(self, client: TestClient, tmp_path: Path) -> None:
        decision_id = self._pending(client)
        for value in ("Basic abc", "Bearer", "Bearer    ", "token abc"):
            res = client.post(
                f"/proposals/{decision_id}/approve", json={}, headers={"Authorization": value}
            )
            assert res.status_code == 401, value
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_reject_requires_token(self, client: TestClient, tmp_path: Path) -> None:
        decision_id = self._pending(client)
        assert client.post(f"/proposals/{decision_id}/reject", json={}).status_code == 401
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_approve_identity_comes_from_token(
        self, client: TestClient, tmp_path: Path, ops1: dict
    ) -> None:
        decision_id = self._pending(client)
        res = client.post(f"/proposals/{decision_id}/approve", json={"comment": "ok"}, headers=ops1)
        assert res.status_code == 200
        approval = res.json()["approvals"][0]
        assert approval["approver"] == "ops-1"
        assert approval["display_name"] == "Ops One"
        assert approval["auth_method"] == "token"
        assert res.json()["resolution"]["approvers"] == ["ops-1"]
        log, _ = audit_log(tmp_path)
        human = log.records()[0]["human_action"]
        assert human["approvers"] == ["ops-1"]
        assert human["auth_methods"] == ["token"]

    def test_body_approver_field_is_rejected(
        self, client: TestClient, tmp_path: Path, ops1: dict
    ) -> None:
        """The pre W2 body shape is refused loudly, not silently ignored (C4)."""
        decision_id = self._pending(client)
        res = client.post(
            f"/proposals/{decision_id}/approve",
            json={"approver": "someone-else", "comment": "ok"},
            headers=ops1,
        )
        assert res.status_code == 422
        assert "approver" in res.text
        self._assert_nothing_happened(client, decision_id, tmp_path)

    def test_whoami(self, client: TestClient, ops1: dict) -> None:
        assert client.get("/approvers/me").status_code == 401
        me = client.get("/approvers/me", headers=ops1).json()
        assert me == {"id": "ops-1", "display_name": "Ops One", "auth_method": "token"}

    def test_store_holds_hashes_not_tokens(self, app) -> None:
        token = register_approver(app, "ops-hash")
        row = app.state.store.get_approver("ops-hash")
        assert row["token_hash"] != token
        assert len(row["token_hash"]) == 64
        assert all("token_hash" not in r for r in app.state.store.list_approvers())


class TestExpiry:
    def test_pending_proposal_expires_after_ttl(self, tmp_path: Path) -> None:
        client = TestClient(create_app(make_config(tmp_path, ttl_seconds=0.0)))
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.get(f"/proposals/{decision_id}")
        assert res.json()["status"] == "expired"

    def test_expired_proposal_cannot_be_approved(self, tmp_path: Path) -> None:
        app = create_app(make_config(tmp_path, ttl_seconds=0.0))
        client = TestClient(app)
        headers = bearer(register_approver(app, "ops-1"))
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=headers)
        assert res.status_code == 409

    def test_expiry_writes_audit_record(self, tmp_path: Path) -> None:
        client = TestClient(create_app(make_config(tmp_path, ttl_seconds=0.0)))
        client.post("/proposals", json=proposal_body())
        client.get("/proposals")  # triggers sweep
        log, _ = audit_log(tmp_path)
        records = log.records()
        assert len(records) == 1
        assert records[0]["human_action"]["action"] == "expired"


class TestDualControl:
    @pytest.fixture()
    def dual_app(self, tmp_path: Path):
        return create_app(make_config(tmp_path, dual_control=True))

    @pytest.fixture()
    def dual_client(self, dual_app) -> TestClient:
        return TestClient(dual_app)

    @pytest.fixture()
    def ops1(self, dual_app) -> dict[str, str]:
        return bearer(register_approver(dual_app, "ops-1", "Ops One"))

    @pytest.fixture()
    def ops2(self, dual_app) -> dict[str, str]:
        return bearer(register_approver(dual_app, "ops-2", "Ops Two"))

    def test_first_approval_keeps_pending(self, dual_client: TestClient, ops1: dict) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        assert res.json()["status"] == "pending"
        assert res.json()["signature"] is None

    def test_same_approver_twice_rejected(self, dual_client: TestClient, ops1: dict) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        res = dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        assert res.status_code == 409

    def test_dual_control_requires_two_distinct_identities(
        self, dual_app, dual_client: TestClient, ops1: dict
    ) -> None:
        """A second token for the SAME approver id must not count as a second human."""
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        # no second token can exist for ops-1 (id is the primary key), and a
        # display name collision is not an identity: register ops-3 named "Ops One"
        same_name = bearer(register_approver(dual_app, "ops-3", "Ops One"))
        res = dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=same_name)
        assert res.json()["status"] == "approved"
        assert res.json()["resolution"]["approvers"] == ["ops-1", "ops-3"]

    def test_two_distinct_approvers_sign(
        self, dual_client: TestClient, ops1: dict, ops2: dict
    ) -> None:
        decision_id = dual_client.post("/proposals", json=proposal_body()).json()["decision_id"]
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        res = dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops2)
        assert res.json()["status"] == "approved"
        assert res.json()["signature"] is not None
        assert res.json()["resolution"]["approvers"] == ["ops-1", "ops-2"]


class TestHtmlPage:
    def test_index_serves_page(self, client: TestClient) -> None:
        res = client.get("/")
        assert res.status_code == 200
        assert "pending approvals" in res.text
