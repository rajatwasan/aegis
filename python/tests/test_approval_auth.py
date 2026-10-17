"""W3: every approve and reject carries an authenticated principal (SPEC.md 4.5).

Each case fails on the parent commit, where ``approver`` was free text in the
request body and nothing checked a credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.approval import create_app
from aegis.approval.auth import (
    MIN_TOKEN_LENGTH,
    ApproverRegistry,
    Principal,
    bearer_token,
    parse_approver_tokens,
)
from aegis.audit import AuditLog, AuditSigner
from aegis.config import ConfigError
from tests.helpers import TOKENS, bearer, dev_approval_config

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def proposal_body() -> dict:
    return {
        "operation": 1,
        "token": TOKEN,
        "from": ALICE,
        "to": BOB,
        "asset_class": 0,
        "amount": 50_000,
        "policy_result": {"effect": "escalate", "matched_rules": ["escalate-large-transfer"]},
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(dev_approval_config(tmp_path)))


@pytest.fixture()
def dual_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(dev_approval_config(tmp_path, dual_control=True)))


def submit(client: TestClient) -> str:
    return client.post("/proposals", json=proposal_body()).json()["decision_id"]


class TestRegistryParsing:
    def test_registry_parses_pairs(self) -> None:
        parsed = parse_approver_tokens(" ops-1:" + "a" * 24 + " , ops.2:" + "b" * 30)
        assert parsed == {"ops-1": "a" * 24, "ops.2": "b" * 30}

    def test_registry_rejects_short_token_without_echoing_it(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            parse_approver_tokens("ops-1:short")
        message = str(excinfo.value)
        assert "entry 1" in message and str(MIN_TOKEN_LENGTH) in message
        assert "short" not in message.replace("shorter", "")

    def test_registry_rejects_duplicate_id(self) -> None:
        with pytest.raises(ConfigError, match="duplicate id ops-1"):
            parse_approver_tokens("ops-1:" + "a" * 24 + ",ops-1:" + "b" * 24)

    @pytest.mark.parametrize("raw", ["", " , ", "nocolon", "Bad Id:" + "a" * 24, "x:" + "a:b" * 12])
    def test_registry_rejects_malformed_entries(self, raw: str) -> None:
        with pytest.raises(ConfigError) as excinfo:
            parse_approver_tokens(raw)
        assert "AEGIS_APPROVER_TOKENS" in str(excinfo.value)

    def test_model_validates_tokens_too(self, tmp_path: Path) -> None:
        with pytest.raises(Exception) as excinfo:
            dev_approval_config(tmp_path, approver_tokens={"ops-1": "short"})
        assert "shorter than" in str(excinfo.value)


class TestRegistryLookup:
    def test_lookup_scans_every_entry(self, monkeypatch) -> None:
        """No early exit: the number of comparisons is the registry size, always."""
        import aegis.approval.auth as auth_module

        calls: list[int] = []
        real = auth_module.hmac.compare_digest

        def counting(a, b):
            calls.append(1)
            return real(a, b)

        monkeypatch.setattr(auth_module.hmac, "compare_digest", counting)
        registry = ApproverRegistry(TOKENS)
        assert registry.lookup(TOKENS["ops-1"]) == Principal("ops-1", "token")
        first = len(calls)
        assert registry.lookup(TOKENS["ops-2"]) == Principal("ops-2", "token")
        assert registry.lookup("nope") is None
        assert first == len(TOKENS)
        assert len(calls) == 3 * len(TOKENS)

    def test_bearer_token_parsing(self) -> None:
        assert bearer_token("Bearer abc") == "abc"
        assert bearer_token("bearer   abc ") == "abc"
        assert bearer_token("Basic abc") is None
        assert bearer_token("Bearer") is None
        assert bearer_token(None) is None


class TestHandlers:
    def test_missing_header_401_with_challenge(self, client: TestClient) -> None:
        decision_id = submit(client)
        res = client.post(f"/proposals/{decision_id}/approve", json={"comment": "x"})
        assert res.status_code == 401
        assert res.headers["WWW-Authenticate"] == "Bearer"
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_unknown_token_401(self, client: TestClient) -> None:
        decision_id = submit(client)
        res = client.post(
            f"/proposals/{decision_id}/reject",
            json={},
            headers={"Authorization": "Bearer " + "z" * 40},
        )
        assert res.status_code == 401
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_no_approvers_configured_401(self, tmp_path: Path) -> None:
        client = TestClient(create_app(dev_approval_config(tmp_path, approver_tokens={})))
        decision_id = submit(client)
        res = client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        assert res.status_code == 401
        assert "AEGIS_APPROVER_TOKENS" in res.json()["detail"]

    def test_body_approver_field_422(self, client: TestClient) -> None:
        """An old client naming its own approver fails loudly instead of being trusted."""
        decision_id = submit(client)
        res = client.post(
            f"/proposals/{decision_id}/approve",
            json={"approver": "ops-2", "comment": "x"},
            headers=bearer("ops-1"),
        )
        assert res.status_code == 422
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_principal_recorded_in_approvals_and_audit(self, client: TestClient, tmp_path) -> None:
        decision_id = submit(client)
        res = client.post(
            f"/proposals/{decision_id}/approve", json={"comment": "ok"}, headers=bearer("ops-1")
        )
        assert res.status_code == 200
        body = res.json()
        assert body["approvals"][0]["approver"] == "ops-1"
        assert body["approvals"][0]["auth"] == "token"
        assert body["resolution"]["approver"] == "ops-1"
        assert body["resolution"]["auth"] == "token"

        log = AuditLog(tmp_path / "audit.jsonl", AuditSigner.load_or_create(tmp_path / "audit.key"))
        record = log.records()[-1]
        assert record["human_action"]["approver"] == "ops-1"
        assert record["human_action"]["auth"] == "token"

    def test_reject_records_principal(self, client: TestClient) -> None:
        decision_id = submit(client)
        res = client.post(f"/proposals/{decision_id}/reject", json={}, headers=bearer("ops-2"))
        assert res.json()["resolution"] == {
            "action": "rejected",
            "approver": "ops-2",
            "auth": "token",
            "comment": "",
        }

    def test_dual_control_same_principal_409(self, dual_client: TestClient) -> None:
        decision_id = submit(dual_client)
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        res = dual_client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1")
        )
        assert res.status_code == 409
        assert dual_client.get(f"/proposals/{decision_id}").json()["signature"] is None

    def test_dual_control_two_principals_approves(self, dual_client: TestClient) -> None:
        decision_id = submit(dual_client)
        dual_client.post(f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-1"))
        res = dual_client.post(
            f"/proposals/{decision_id}/approve", json={}, headers=bearer("ops-2")
        )
        assert res.json()["status"] == "approved"
        assert res.json()["resolution"]["approvers"] == [
            {"approver": "ops-1", "auth": "token"},
            {"approver": "ops-2", "auth": "token"},
        ]

    def test_expired_audit_record_has_no_principal(self, tmp_path: Path) -> None:
        client = TestClient(create_app(dev_approval_config(tmp_path, ttl_seconds=0.0)))
        decision_id = submit(client)
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "expired"
        log = AuditLog(tmp_path / "audit.jsonl", AuditSigner.load_or_create(tmp_path / "audit.key"))
        assert log.records()[-1]["human_action"] == {
            "action": "expired",
            "approver": None,
            "auth": None,
            "comment": "ttl",
        }

    def test_approval_page_sends_bearer_not_body_approver(self, client: TestClient) -> None:
        page = client.get("/").text
        assert "Authorization" in page and "Bearer" in page
        assert 'id="approver"' not in page
