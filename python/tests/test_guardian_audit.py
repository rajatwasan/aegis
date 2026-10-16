"""Proof-of-human embedding: guardian-decided audit records carry
human_presence and the untouched verification stack still proves them."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from aegis import anchoring
from aegis.approval import ApprovalConfig, create_app
from aegis.audit import MerkleTree
from aegis.audit.canonical import canonical_json
from aegis.guardian_touch import GuardianTouchConfig, decision_challenge, mount_guardian_touch
from aegis.guardian_touch.challenge import pairing_challenge
from tests.conftest import KEYS, bearer, register_approver
from tests.passkeys import SoftwarePasskey

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeAnchorContract:
    """Just enough contract surface for verify_decision: rootOf(batch).call()."""

    def __init__(self, root: bytes) -> None:
        self.functions = SimpleNamespace(rootOf=lambda batch_id: SimpleNamespace(call=lambda: root))


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


def test_guardian_record_carries_human_presence_and_still_proves(tmp_path: Path) -> None:
    config = ApprovalConfig(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(REPO_ROOT / "policies" / "default.yaml"),
        guardian_key=KEYS[9],
    )
    app = create_app(config)
    mount_guardian_touch(app, GuardianTouchConfig(rp_id=RP_ID, expected_origin=ORIGIN))
    client = TestClient(app)

    # one human, two credentials: the token pairs the phone, the phone decides
    casey = register_approver(app, "casey", "Casey")
    passkey = SoftwarePasskey(rp_id=RP_ID, origin=ORIGIN)
    code = client.post("/guardian/pair/start", headers=bearer(casey)).json()["code"]
    paired = client.post(
        "/guardian/pair/complete",
        json={"code": code, "credential": passkey.registration(pairing_challenge(code))},
    )
    assert paired.status_code == 200, paired.text

    guardian_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
    row = client.get(f"/proposals/{guardian_id}").json()
    assertion = passkey.assertion(decision_challenge(guardian_id, row["proposal"]), 7)
    res = client.post(
        f"/guardian/decide/{guardian_id}",
        json={"action": "approve", "comment": "from the phone", "credential": assertion},
    )
    assert res.status_code == 200, res.text
    assert res.json()["human_presence"]["credential_id"] == passkey.credential_id_b64

    # a console-path decision in the same log must simply omit the field
    console_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
    desk = client.post(
        f"/proposals/{console_id}/approve",
        json={"comment": "from the desk"},
        headers=bearer(casey),
    )
    assert desk.status_code == 200, desk.text

    records = app.state.audit.records()
    by_id = {r["decision_id"]: r for r in records}
    assert by_id[guardian_id]["human_presence"] == {
        "credential_id": passkey.credential_id_b64,
        "sign_count": 7,
        "signature": assertion["response"]["signature"],
        "authenticator_data": assertion["response"]["authenticatorData"],
        "client_data_json": assertion["response"]["clientDataJSON"],
    }
    assert by_id[guardian_id]["human_action"]["auth_methods"] == ["passkey"]
    assert "human_presence" not in by_id[console_id]
    assert by_id[console_id]["human_action"]["auth_methods"] == ["token"]

    # the untouched verifiers cover the embedded evidence: hash chain +
    # Ed25519 over every record...
    assert app.state.audit.verify(app.state.audit.signer.public_key_hex()) == len(records)

    # ...and the Merkle inclusion proof (PROOF OK path) for the guardian record
    tree = MerkleTree([canonical_json(r) for r in records])
    anchors = [
        {
            "batch_id": 0,
            "root": tree.root.hex(),
            "decision_ids": [r["decision_id"] for r in records],
        }
    ]
    result = anchoring.verify_decision(anchors, FakeAnchorContract(tree.root), by_id, guardian_id)
    assert result["proof_ok"] is True
    assert result["reason"] is None

    # tampering with the embedded evidence must break the proof
    by_id[guardian_id]["human_presence"]["sign_count"] = 8
    tampered = anchoring.verify_decision(anchors, FakeAnchorContract(tree.root), by_id, guardian_id)
    assert tampered["proof_ok"] is False
