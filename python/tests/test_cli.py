"""M8 CLI tests: anchor a batch on-chain and verify Merkle inclusion proofs.

Uses the deployed AuditAnchor from the shared fixture. Builds a small audit log,
anchors it via ``aegis anchor``, checks ``aegis verify`` passes for a real
record, and that tampering with a record makes verification fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from aegis import cli
from aegis.audit import AuditLog, AuditSigner
from tests.conftest import KEYS, OPERATOR


def _seed_state(deployment, tmp_path: Path) -> tuple[dict, list[dict]]:
    # a fresh anchor per test so batch ids don't collide on the shared chain
    anchor = deployment["chain"].deploy("AuditAnchor", OPERATOR)
    signer = AuditSigner.load_or_create(tmp_path / "audit.key")
    audit = AuditLog(tmp_path / "audit.jsonl", signer)
    records = [
        audit.append(
            actor="agent",
            proposal={"to": f"0xdest{i}", "amount": 100 * i},
            policy_result={"effect": "allow", "status": "executed"},
        )
        for i in range(3)
    ]
    state = {
        "rpc_url": deployment["rpc_url"],
        "chain_id": 31337,
        "operator_key": KEYS[0],
        "anchor_address": anchor.address,
        "token_address": deployment["token"].address,
        "registry_address": deployment["registry"].address,
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "audit_key_file": str(tmp_path / "audit.key"),
        "audit_public_key": signer.public_key_hex(),
        "decision_ids": [r["decision_id"] for r in records],
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    return state, records


def test_anchor_then_verify_ok(deployment, tmp_path: Path, capsys) -> None:
    _, records = _seed_state(deployment, tmp_path)

    assert cli.cmd_anchor(tmp_path) == 0
    anchors = json.loads((tmp_path / "anchors.json").read_text())
    assert len(anchors) == 1 and len(anchors[0]["decision_ids"]) == 3

    # a second anchor finds nothing new
    assert cli.cmd_anchor(tmp_path) == 0
    assert "nothing to anchor" in capsys.readouterr().out

    # every record verifies against the on-chain root
    assert cli.cmd_verify(tmp_path, None, verify_all=True) == 0
    out = capsys.readouterr().out
    assert out.count("PROOF OK") == 3

    # a single decision id verifies too
    assert cli.cmd_verify(tmp_path, records[1]["decision_id"], verify_all=False) == 0
    assert "PROOF OK" in capsys.readouterr().out


def test_verify_fails_on_tamper(deployment, tmp_path: Path, capsys) -> None:
    _, records = _seed_state(deployment, tmp_path)
    assert cli.cmd_anchor(tmp_path) == 0
    capsys.readouterr()

    # tamper: rewrite a record's proposal amount, leaving its stored hash intact
    log_path = tmp_path / "audit.jsonl"
    lines = log_path.read_text().splitlines()
    middle = json.loads(lines[1])
    middle["proposal"]["amount"] = 999_999
    lines[1] = json.dumps(middle)
    log_path.write_text("\n".join(lines) + "\n")

    assert cli.cmd_verify(tmp_path, records[1]["decision_id"], verify_all=False) == 1
    assert "PROOF FAIL" in capsys.readouterr().out


def test_verify_without_anchor_reports(deployment, tmp_path: Path, capsys) -> None:
    _seed_state(deployment, tmp_path)
    assert cli.cmd_verify(tmp_path, "whatever", verify_all=False) == 1
    assert "run `aegis anchor` first" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# approver (W2): tokens are printed once and stored only as hashes
# --------------------------------------------------------------------------- #


def test_cli_approver_add_prints_token_once_and_stores_hash(tmp_path: Path, capsys) -> None:
    from aegis.approval.identity import hash_token
    from aegis.approval.store import ProposalStore

    args = ["--state-dir", str(tmp_path), "approver", "add", "ops-1", "--name", "Ops"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out.strip().splitlines()
    token = out[-1]
    assert len(token) >= 32 and "token" not in token  # the last line is the token itself

    row = ProposalStore(str(tmp_path / "approvals.db")).get_approver("ops-1")
    assert row is not None
    assert row["token_hash"] == hash_token(token)
    assert token not in json.dumps(row)  # never persisted in the clear

    # list never shows the token or its hash
    assert cli.main(["--state-dir", str(tmp_path), "approver", "list"]) == 0
    listing = capsys.readouterr().out
    assert "ops-1" in listing and "active" in listing
    assert token not in listing and row["token_hash"] not in listing

    # a second add with the same id is refused
    assert cli.main(["--state-dir", str(tmp_path), "approver", "add", "ops-1"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_approver_revoke_disables_the_token(tmp_path: Path, capsys) -> None:
    from fastapi.testclient import TestClient

    from aegis.approval import ApprovalConfig, create_app

    assert cli.main(["--state-dir", str(tmp_path), "approver", "add", "ops-2"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli.main(["--state-dir", str(tmp_path), "approver", "revoke", "ops-2"]) == 0
    assert "revoked" in capsys.readouterr().out
    assert cli.main(["--state-dir", str(tmp_path), "approver", "revoke", "nobody"]) == 1

    app = create_app(
        ApprovalConfig(
            db_path=str(tmp_path / "approvals.db"),
            audit_log_path=str(tmp_path / "audit.jsonl"),
            audit_key_file=str(tmp_path / "audit.key"),
            policy_path=str(Path(__file__).resolve().parents[2] / "policies" / "default.yaml"),
            guardian_key=KEYS[9],
        )
    )
    res = TestClient(app).get("/approvers/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
