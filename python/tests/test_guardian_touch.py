"""Guardian passkey tests: challenge determinism, wrong-challenge rejection."""

import base64
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from aegis.approval import create_app
from aegis.audit.canonical import canonical_json
from aegis.guardian_touch import GuardianTouchConfig, decision_challenge, mount_guardian_touch
from tests.helpers import bearer, dev_approval_config

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

REPO_ROOT = Path(__file__).resolve().parents[2]
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
CRED_ID = "dGVzdC1jcmVkZW50aWFs"  # base64url("test-credential")
ADMIN_TOKEN = "test-admin-token-0000000000000000"


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
    config = dev_approval_config(tmp_path, admin_token=ADMIN_TOKEN)
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


class TestPairingIsOperatorOnly:
    def test_pair_start_requires_admin_token(self, client: TestClient) -> None:
        """W4: an open pairing endpoint would let anyone enrol a passkey and approve."""
        assert client.post("/guardian/pair/start").status_code == 401
        wrong = {"Authorization": "Bearer " + "z" * 40}
        assert client.post("/guardian/pair/start", headers=wrong).status_code == 401
        ok = client.post("/guardian/pair/start", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert ok.status_code == 200
        assert len(ok.json()["code"]) == 6

    def test_pair_start_without_configured_admin_token_is_401(self, tmp_path: Path) -> None:
        app = create_app(dev_approval_config(tmp_path))
        mount_guardian_touch(app, GuardianTouchConfig(rp_id=RP_ID, expected_origin=ORIGIN))
        res = TestClient(app).post(
            "/guardian/pair/start", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
        )
        assert res.status_code == 401
        assert "AEGIS_ADMIN_TOKEN" in res.json()["detail"]


class TestGuardianConfig:
    def test_public_chain_requires_rp_settings(self, monkeypatch) -> None:
        from aegis.config import ConfigError

        monkeypatch.delenv("AEGIS_RP_ID", raising=False)
        monkeypatch.delenv("AEGIS_EXPECTED_ORIGIN", raising=False)
        with pytest.raises(ConfigError, match="AEGIS_RP_ID, AEGIS_EXPECTED_ORIGIN"):
            GuardianTouchConfig.from_env(84532)
        assert GuardianTouchConfig.from_env(31337).rp_id == "localhost"
        monkeypatch.setenv("AEGIS_RP_ID", "console.example.org")
        monkeypatch.setenv("AEGIS_EXPECTED_ORIGIN", "https://console.example.org")
        assert GuardianTouchConfig.from_env(84532).rp_id == "console.example.org"


def test_cli_pair_code_mints_a_live_code(client: TestClient, tmp_path: Path, capsys) -> None:
    from aegis import cli

    assert cli.main(["guardian", "pair-code", "--db", str(tmp_path / "approvals.db")]) == 0
    code = capsys.readouterr().out.strip()
    assert len(code) == 6
    options = client.post("/guardian/pair/options", json={"code": code})
    assert options.status_code == 200


ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _code(client: TestClient) -> str:
    return client.post("/guardian/pair/start", headers=ADMIN).json()["code"]


class TestPairingLifecycle:
    """Every refusal path of pairing and deciding has its own status code (R14)."""

    def test_unknown_code_404(self, client: TestClient) -> None:
        assert client.post("/guardian/pair/options", json={"code": "ZZZZZZ"}).status_code == 404

    def test_expired_code_410(self, client: TestClient, monkeypatch) -> None:
        code = _code(client)
        import aegis.guardian_touch.routes as routes

        real_time = routes.time.time
        monkeypatch.setattr(routes.time, "time", lambda: real_time() + 3600)
        assert client.post("/guardian/pair/options", json={"code": code}).status_code == 410

    def test_options_then_complete_then_code_is_used(self, client: TestClient, monkeypatch) -> None:
        code = _code(client)
        options = client.post("/guardian/pair/options", json={"code": code.lower()})
        assert options.status_code == 200 and options.json()["rp"]["id"] == RP_ID

        monkeypatch.setattr(
            "aegis.guardian_touch.routes.verify_registration_response",
            lambda **_: SimpleNamespace(
                credential_id=b"new-credential", credential_public_key=b"cose", sign_count=0
            ),
        )
        done = client.post("/guardian/pair/complete", json={"code": code, "credential": {}})
        assert done.status_code == 200
        assert client.app.state.guardian_store.get_credential(done.json()["credential_id"])
        # single use: the same code cannot pair a second device
        again = client.post("/guardian/pair/options", json={"code": code})
        assert again.status_code == 409

    def test_complete_with_bad_registration_400(self, client: TestClient) -> None:
        code = _code(client)
        res = client.post("/guardian/pair/complete", json={"code": code, "credential": {}})
        assert res.status_code == 400
        assert "registration verification failed" in res.json()["detail"]
        # a failed ceremony does not burn the code
        assert client.post("/guardian/pair/options", json={"code": code}).status_code == 200

    def test_auth_options_unknown_decision_404_and_no_passkey_409(self, client: TestClient) -> None:
        assert client.post("/guardian/auth-options/nope").status_code == 404
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(f"/guardian/auth-options/{decision_id}")
        assert res.status_code == 409 and "no guardian passkey" in res.json()["detail"]

    def test_decide_refusals(self, client: TestClient) -> None:
        body = {"action": "approve", "comment": "", "credential": make_assertion(b"x" * 32)}
        assert client.post("/guardian/decide/nope", json=body).status_code == 404

        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        no_id = {"action": "approve", "comment": "", "credential": {"response": {}}}
        assert client.post(f"/guardian/decide/{decision_id}", json=no_id).status_code == 400
        unknown = client.post(f"/guardian/decide/{decision_id}", json=body)
        assert unknown.status_code == 404 and "unknown credential" in unknown.json()["detail"]

        client.post(f"/proposals/{decision_id}/reject", json={}, headers=bearer("ops-1"))
        settled = client.post(f"/guardian/decide/{decision_id}", json=body)
        assert settled.status_code == 409

    def test_passkey_reject_records_principal(self, client: TestClient, monkeypatch) -> None:
        client.app.state.guardian_store.add_credential(CRED_ID, cose_public_key(), 0)
        monkeypatch.setattr(
            "aegis.guardian_touch.routes.verify_authentication_response",
            lambda **_: SimpleNamespace(new_sign_count=3),
        )
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        res = client.post(
            f"/guardian/decide/{decision_id}",
            json={"action": "reject", "comment": "no", "credential": make_assertion(b"y" * 32)},
        )
        assert res.status_code == 200
        assert res.json()["resolution"]["auth"] == "passkey"
        assert client.app.state.guardian_store.get_credential(CRED_ID)["sign_count"] == 3
