"""Guardian passkey tests: challenge determinism, wrong-challenge rejection."""

import base64
import hashlib
import json
import struct
from pathlib import Path

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from aegis.approval import ApprovalConfig, create_app
from aegis.audit.canonical import canonical_json
from aegis.guardian_touch import GuardianTouchConfig, decision_challenge, mount_guardian_touch

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

REPO_ROOT = Path(__file__).resolve().parents[2]
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
CRED_ID = "dGVzdC1jcmVkZW50aWFs"  # base64url("test-credential")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def cose_public_key() -> bytes:
    """A structurally valid ES256 COSE key (EC2, P-256)."""
    numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    return cbor2.dumps(
        {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
    )


def make_assertion(challenge: bytes) -> dict:
    """A well-formed authentication credential asserting over ``challenge``."""
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": b64url(challenge), "origin": ORIGIN}
    ).encode()
    auth_data = hashlib.sha256(RP_ID.encode()).digest() + b"\x05" + struct.pack(">I", 1)
    return {
        "id": CRED_ID,
        "rawId": CRED_ID,
        "type": "public-key",
        "clientExtensionResults": {},
        "response": {
            "clientDataJSON": b64url(client_data),
            "authenticatorData": b64url(auth_data),
            "signature": b64url(b"\x30\x06\x02\x01\x00\x02\x01\x00"),
        },
    }


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
    config = ApprovalConfig(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(REPO_ROOT / "policies" / "default.yaml"),
    )
    app = create_app(config)
    mount_guardian_touch(app, GuardianTouchConfig(rp_id=RP_ID, expected_origin=ORIGIN))
    return TestClient(app)


class TestChallengeDerivation:
    def test_deterministic_and_key_order_independent(self) -> None:
        proposal = proposal_body()
        reordered = dict(reversed(list(proposal.items())))
        expected = hashlib.sha256(b"decision-1" + canonical_json(proposal)).digest()
        assert decision_challenge("decision-1", proposal) == expected
        assert decision_challenge("decision-1", reordered) == expected

    def test_auth_options_carry_the_decision_challenge(self, client: TestClient) -> None:
        client.app.state.guardian_store.add_credential(CRED_ID, cose_public_key(), 0)
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        first = client.post(f"/guardian/auth-options/{decision_id}").json()
        second = client.post(f"/guardian/auth-options/{decision_id}").json()
        row = client.get(f"/proposals/{decision_id}").json()
        expected = decision_challenge(decision_id, row["proposal"])
        assert first["challenge"] == second["challenge"] == b64url(expected)


class TestDecide:
    def test_assertion_for_different_challenge_is_rejected(self, client: TestClient) -> None:
        client.app.state.guardian_store.add_credential(CRED_ID, cose_public_key(), 0)
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]

        wrong_challenge = hashlib.sha256(b"a different decision entirely").digest()
        body = {"action": "approve", "comment": "", "credential": make_assertion(wrong_challenge)}
        res = client.post(f"/guardian/decide/{decision_id}", json=body)
        assert 400 <= res.status_code < 500
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"
