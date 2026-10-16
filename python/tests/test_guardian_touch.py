"""Guardian passkey tests (W10): pairing is started by an authenticated
approver and binds the passkey to that approver; a decision from the passkey
resolves as that approver with ``auth_method`` passkey, through the same
``resolve_decision`` path the console uses.

Every registration and assertion here is verified by py_webauthn for real
(tests/passkeys.py is a software authenticator); nothing is stubbed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.approval import ApprovalConfig, create_app
from aegis.audit.canonical import canonical_json
from aegis.guardian_touch import GuardianTouchConfig, decision_challenge, mount_guardian_touch
from aegis.guardian_touch.challenge import pairing_challenge
from tests.conftest import KEYS, bearer, register_approver
from tests.passkeys import SoftwarePasskey, b64url

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

REPO_ROOT = Path(__file__).resolve().parents[2]
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
NOW = 1_800_000_000.0


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


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def client(tmp_path: Path, clock: Clock) -> TestClient:
    config = ApprovalConfig(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(REPO_ROOT / "policies" / "default.yaml"),
        guardian_key=KEYS[9],
    )
    app = create_app(config)
    mount_guardian_touch(app, GuardianTouchConfig(rp_id=RP_ID, expected_origin=ORIGIN, clock=clock))
    return TestClient(app)


@pytest.fixture()
def casey_token(client: TestClient) -> str:
    return register_approver(client.app, "casey", "Casey")


@pytest.fixture()
def passkey() -> SoftwarePasskey:
    return SoftwarePasskey(rp_id=RP_ID, origin=ORIGIN)


def pair(client: TestClient, token: str, passkey: SoftwarePasskey) -> dict:
    """Run the whole pairing flow as the approver holding ``token``."""
    started = client.post("/guardian/pair/start", headers=bearer(token))
    assert started.status_code == 200, started.text
    code = started.json()["code"]
    options = client.post("/guardian/pair/options", json={"code": code})
    assert options.status_code == 200, options.text
    done = client.post(
        "/guardian/pair/complete",
        json={"code": code, "credential": passkey.registration(pairing_challenge(code))},
    )
    assert done.status_code == 200, done.text
    return done.json()


def submit(client: TestClient) -> str:
    return client.post("/proposals", json=proposal_body()).json()["decision_id"]


def decide(client: TestClient, passkey: SoftwarePasskey, decision_id: str, action: str, **kw):
    row = client.get(f"/proposals/{decision_id}").json()
    challenge = decision_challenge(decision_id, row["proposal"])
    credential = passkey.assertion(challenge, kw.pop("sign_count", 1), **kw)
    return client.post(
        f"/guardian/decide/{decision_id}",
        json={"action": action, "comment": "from the phone", "credential": credential},
    )


class TestChallengeDerivation:
    def test_deterministic_and_key_order_independent(self) -> None:
        proposal = proposal_body()
        reordered = dict(reversed(list(proposal.items())))
        expected = hashlib.sha256(b"decision-1" + canonical_json(proposal)).digest()
        assert decision_challenge("decision-1", proposal) == expected
        assert decision_challenge("decision-1", reordered) == expected

    def test_auth_options_carry_the_decision_challenge(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        first = client.post(f"/guardian/auth-options/{decision_id}").json()
        second = client.post(f"/guardian/auth-options/{decision_id}").json()
        row = client.get(f"/proposals/{decision_id}").json()
        expected = decision_challenge(decision_id, row["proposal"])
        assert first["challenge"] == second["challenge"] == b64url(expected)


class TestPairing:
    def test_pair_start_requires_an_approver_token(self, client: TestClient) -> None:
        assert client.post("/guardian/pair/start").status_code == 401
        assert client.post("/guardian/pair/start", headers=bearer("nope")).status_code == 401

    def test_code_is_bound_to_the_signed_in_approver(
        self, client: TestClient, casey_token: str, clock: Clock
    ) -> None:
        res = client.post("/guardian/pair/start", headers=bearer(casey_token))
        assert res.status_code == 200
        body = res.json()
        assert body["approver_id"] == "casey"
        assert len(body["code"]) == 6 and body["code"] == body["code"].upper()
        assert body["expires_at"] == clock.now + 300
        stored = client.app.state.guardian_store.get_pairing_code(body["code"])
        assert stored["approver_id"] == "casey"

    def test_options_enroll_under_the_approver_name(
        self, client: TestClient, casey_token: str
    ) -> None:
        code = client.post("/guardian/pair/start", headers=bearer(casey_token)).json()["code"]
        options = client.post("/guardian/pair/options", json={"code": code.lower()}).json()
        assert options["user"]["name"] == "casey"
        assert options["user"]["displayName"] == "Casey"
        assert options["rp"]["id"] == RP_ID

    def test_complete_binds_the_credential_and_spends_the_code(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        code = client.post("/guardian/pair/start", headers=bearer(casey_token)).json()["code"]
        registration = passkey.registration(pairing_challenge(code))
        done = client.post(
            "/guardian/pair/complete", json={"code": code, "credential": registration}
        )
        assert done.status_code == 200, done.text
        assert done.json() == {
            "credential_id": passkey.credential_id_b64,
            "sign_count": 0,
            "approver_id": "casey",
            "display_name": "Casey",
        }
        stored = client.app.state.guardian_store.get_credential(passkey.credential_id_b64)
        assert stored["approver_id"] == "casey"
        # the code is single use
        again = client.post(
            "/guardian/pair/complete", json={"code": code, "credential": registration}
        )
        assert again.status_code == 409
        assert client.post("/guardian/pair/options", json={"code": code}).status_code == 409

    def test_expired_code_is_refused(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey, clock: Clock
    ) -> None:
        code = client.post("/guardian/pair/start", headers=bearer(casey_token)).json()["code"]
        clock.now += 300
        assert client.post("/guardian/pair/options", json={"code": code}).status_code == 410
        res = client.post(
            "/guardian/pair/complete",
            json={"code": code, "credential": passkey.registration(pairing_challenge(code))},
        )
        assert res.status_code == 410
        assert client.app.state.guardian_store.list_credentials() == []

    def test_unknown_code_is_refused(self, client: TestClient) -> None:
        assert client.post("/guardian/pair/options", json={"code": "ZZZZZZ"}).status_code == 404

    def test_wrong_origin_registration_is_refused(
        self, client: TestClient, casey_token: str
    ) -> None:
        elsewhere = SoftwarePasskey(rp_id=RP_ID, origin="https://evil.example")
        code = client.post("/guardian/pair/start", headers=bearer(casey_token)).json()["code"]
        res = client.post(
            "/guardian/pair/complete",
            json={"code": code, "credential": elsewhere.registration(pairing_challenge(code))},
        )
        assert res.status_code == 400
        assert "registration verification failed" in res.json()["detail"]
        assert client.app.state.guardian_store.list_credentials() == []

    def test_revoked_approver_cannot_finish_pairing(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        code = client.post("/guardian/pair/start", headers=bearer(casey_token)).json()["code"]
        client.app.state.store.revoke_approver("casey")
        res = client.post(
            "/guardian/pair/complete",
            json={"code": code, "credential": passkey.registration(pairing_challenge(code))},
        )
        assert res.status_code == 401
        assert client.app.state.guardian_store.list_credentials() == []


class TestDecide:
    def test_assertion_for_different_challenge_is_rejected(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        wrong_challenge = hashlib.sha256(b"a different decision entirely").digest()
        body = {
            "action": "approve",
            "comment": "",
            "credential": passkey.assertion(wrong_challenge),
        }
        res = client.post(f"/guardian/decide/{decision_id}", json=body)
        assert res.status_code == 400
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_bad_signature_is_rejected(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        res = decide(client, passkey, decision_id, "approve", valid=False)
        assert res.status_code == 400
        assert "assertion verification failed" in res.json()["detail"]
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_unknown_credential_is_rejected(self, client: TestClient) -> None:
        stranger = SoftwarePasskey(rp_id=RP_ID, origin=ORIGIN, credential_id=b"stranger")
        decision_id = submit(client)
        res = decide(client, stranger, decision_id, "approve")
        assert res.status_code == 404
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"

    def test_approve_resolves_as_the_bound_approver(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        res = decide(client, passkey, decision_id, "approve", sign_count=7)
        assert res.status_code == 200, res.text
        row = res.json()
        assert row["status"] == "approved"
        assert row["signature"] is not None
        [approval] = row["approvals"]
        assert approval["approver"] == "casey"
        assert approval["display_name"] == "Casey"
        assert approval["auth_method"] == "passkey"
        assert approval["comment"] == "from the phone"
        assert approval["evidence"]["credential_id"] == passkey.credential_id_b64
        assert row["resolution"]["approvers"] == ["casey"]
        assert row["resolution"]["auth_methods"] == ["passkey"]
        assert row["human_presence"]["credential_id"] == passkey.credential_id_b64
        assert row["human_presence"]["sign_count"] == 7
        # the signed audit record names the approver and the method
        [record] = client.app.state.audit.records()
        assert record["human_action"]["approvers"] == ["casey"]
        assert record["human_action"]["auth_methods"] == ["passkey"]
        assert record["human_presence"]["credential_id"] == passkey.credential_id_b64
        # the authenticator counter moved forward
        stored = client.app.state.guardian_store.get_credential(passkey.credential_id_b64)
        assert stored["sign_count"] == 7

    def test_reject_carries_the_assertion_as_evidence(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        res = decide(client, passkey, decision_id, "reject")
        assert res.status_code == 200, res.text
        row = res.json()
        assert row["status"] == "rejected"
        assert row["resolution"]["approver"] == "casey"
        assert row["resolution"]["auth_method"] == "passkey"
        assert row["human_presence"]["credential_id"] == passkey.credential_id_b64
        [record] = client.app.state.audit.records()
        assert record["human_action"]["approver"] == "casey"
        assert record["human_presence"]["sign_count"] == 1

    def test_replayed_sign_count_is_rejected(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        """A cloned authenticator replaying an old counter is refused (WebAuthn 6.1.1)."""
        pair(client, casey_token, passkey)
        first = submit(client)
        assert decide(client, passkey, first, "approve", sign_count=5).status_code == 200
        second = submit(client)
        res = decide(client, passkey, second, "approve", sign_count=5)
        assert res.status_code == 400
        assert client.get(f"/proposals/{second}").json()["status"] == "pending"

    def test_revoked_approver_passkey_is_refused(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        client.app.state.store.revoke_approver("casey")
        res = decide(client, passkey, decision_id, "approve")
        assert res.status_code == 401
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"
        assert client.app.state.audit.records() == []

    def test_passkey_and_token_are_the_same_approver(
        self, client: TestClient, casey_token: str, passkey: SoftwarePasskey
    ) -> None:
        """One human, two credentials: the passkey cannot double as a second
        approver, so under dual control it does not count twice."""
        client.app.state.config.dual_control = True
        pair(client, casey_token, passkey)
        decision_id = submit(client)
        first = client.post(
            f"/proposals/{decision_id}/approve",
            json={"comment": "desk"},
            headers=bearer(casey_token),
        )
        assert first.status_code == 200 and first.json()["status"] == "pending"
        res = decide(client, passkey, decision_id, "approve")
        assert res.status_code == 409
        assert client.get(f"/proposals/{decision_id}").json()["status"] == "pending"
