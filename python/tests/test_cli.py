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
