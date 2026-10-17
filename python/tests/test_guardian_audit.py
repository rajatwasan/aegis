"""Proof-of-human embedding: guardian-decided audit records carry
human_presence and the untouched verification stack still proves them."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aegis import anchoring
from aegis.approval import create_app
from aegis.audit import MerkleTree
from aegis.audit.canonical import canonical_json
from aegis.guardian_touch import GuardianTouchConfig, mount_guardian_touch
from tests.helpers import bearer, dev_approval_config

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
CRED_ID = "dGVzdC1jcmVkZW50aWFs"

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


def test_guardian_record_carries_human_presence_and_still_proves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = dev_approval_config(tmp_path)
    app = create_app(config)
    mount_guardian_touch(
        app, GuardianTouchConfig(rp_id="localhost", expected_origin="http://localhost:5173")
    )
    client = TestClient(app)
    app.state.guardian_store.add_credential(CRED_ID, b"cose-key", 0)

    # the passkey layer is tested elsewhere; here we stub the verification to
    # drive the real /guardian/decide -> approve -> audit-append pipeline
    monkeypatch.setattr(
        "aegis.guardian_touch.routes.verify_authentication_response",
        lambda **_: SimpleNamespace(new_sign_count=7),
    )

    guardian_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
    res = client.post(
        f"/guardian/decide/{guardian_id}",
        json={
            "action": "approve",
            "comment": "from the phone",
            "credential": {
                "id": CRED_ID,
                "response": {
                    "signature": "c2ln",
                    "authenticatorData": "YXV0aA",
                    "clientDataJSON": "Y2xpZW50",
                },
            },
        },
    )
    assert res.status_code == 200
    assert res.json()["human_presence"]["credential_id"] == CRED_ID
    # W4: the principal is derived from the verified credential, never a body field
    assert res.json()["approvals"][0]["approver"] == f"passkey:{CRED_ID[:8]}"
    assert res.json()["approvals"][0]["auth"] == "passkey"

    # a console-path decision in the same log must simply omit the field
    console_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
    client.post(
        f"/proposals/{console_id}/approve",
        json={"comment": "from the desk"},
        headers=bearer("ops-1"),
    )

    records = app.state.audit.records()
    by_id = {r["decision_id"]: r for r in records}
    assert by_id[guardian_id]["human_presence"] == {
        "credential_id": CRED_ID,
        "sign_count": 7,
        "signature": "c2ln",
        "authenticator_data": "YXV0aA",
        "client_data_json": "Y2xpZW50",
    }
    assert "human_presence" not in by_id[console_id]
    assert by_id[guardian_id]["human_action"]["auth"] == "passkey"
    assert by_id[console_id]["human_action"]["auth"] == "token"

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
