"""F0 tests: Guardian Console API surface that needs no chain.

CORS, event emission on the bus, /decisions, /audit/records, /policy,
/metrics, error paths for chain-backed endpoints, and a real SSE consumption
test against a background uvicorn server.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from aegis.api import ApiConfig, create_api_app
from aegis.api.app import parse_eval_report
from aegis.approval import ApprovalConfig
from aegis.policy import load_policy
from tests.conftest import KEYS, bearer, register_approver

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "default.yaml"

TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def make_api_config(tmp_path: Path, **overrides) -> ApiConfig:
    approval = ApprovalConfig(
        db_path=str(tmp_path / "approvals.db"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        audit_key_file=str(tmp_path / "audit.key"),
        policy_path=str(POLICY_PATH),
        ttl_seconds=overrides.pop("ttl_seconds", 900.0),
        guardian_key=KEYS[9],  # W1: no default; tests say which dev key they sign with
    )
    defaults = dict(
        approval=approval,
        state_dir=str(tmp_path),
        evals_report_path=str(tmp_path / "missing-report.md"),
    )
    defaults.update(overrides)
    return ApiConfig(**defaults)


@pytest.fixture()
def app(tmp_path: Path):
    return create_api_app(make_api_config(tmp_path))


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


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


def seed_decision(app, effect: str = "allow", status: str = "executed", **extra) -> dict:
    """Append one agent gate decision straight into the audit log."""
    return app.state.audit.append(
        actor="agent",
        proposal={"operation": 1, "token": TOKEN, "from": ALICE, "to": BOB, "amount": 100},
        policy_result={"effect": effect, "matched_rules": ["r1"], "status": status, **extra},
    )


class TestCors:
    def test_preflight_allows_dev_origin(self, client: TestClient) -> None:
        res = client.options(
            "/proposals",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == "http://localhost:5173"

    def test_configurable_origins(self, tmp_path: Path) -> None:
        config = make_api_config(tmp_path, cors_origins=["http://example.test"])
        client = TestClient(create_api_app(config))
        res = client.get("/metrics", headers={"Origin": "http://example.test"})
        assert res.headers["access-control-allow-origin"] == "http://example.test"


class TestBusEvents:
    def test_proposal_lifecycle_emits_events(self, app, client: TestClient) -> None:
        bus = app.state.bus
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        assert [e["data"]["decision_id"] for e in bus.events_of("proposal.created")] == [
            decision_id
        ]

        ops1 = bearer(register_approver(app, "ops-1"))
        client.post(f"/proposals/{decision_id}/approve", json={}, headers=ops1)
        approved = bus.events_of("proposal.approved")
        assert approved and approved[-1]["data"]["status"] == "approved"
        # the resolution was audited, and the audit log emitted decision.recorded
        recorded = bus.events_of("decision.recorded")
        assert recorded and recorded[-1]["data"]["decision_id"] == decision_id

    def test_reject_and_expire_emit_events(self, app, client: TestClient, tmp_path) -> None:
        bus = app.state.bus
        decision_id = client.post("/proposals", json=proposal_body()).json()["decision_id"]
        ops1 = bearer(register_approver(app, "ops-1"))
        client.post(f"/proposals/{decision_id}/reject", json={}, headers=ops1)
        assert bus.events_of("proposal.rejected")

        expiring_app = create_api_app(make_api_config(tmp_path / "exp", ttl_seconds=0.0))
        expiring = TestClient(expiring_app)
        expiring.post("/proposals", json=proposal_body())
        expiring.get("/proposals")  # triggers the sweep
        assert expiring_app.state.bus.events_of("proposal.expired")

    def test_idempotent_resubmission_emits_once(self, app, client: TestClient) -> None:
        headers = {"Idempotency-Key": "same"}
        client.post("/proposals", json=proposal_body(), headers=headers)
        client.post("/proposals", json=proposal_body(), headers=headers)
        assert len(app.state.bus.events_of("proposal.created")) == 1


class TestDecisions:
    def test_empty(self, client: TestClient) -> None:
        body = client.get("/decisions").json()
        assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_projection_and_pagination(self, app, client: TestClient) -> None:
        for i in range(5):
            seed_decision(app, effect="allow", tx_hash=f"0x{i:02x}")
        seed_decision(app, effect="escalate", status="pending_approval")
        # non-gate records are excluded from the decision view
        app.state.audit.append(
            actor="approval-service", proposal={}, policy_result={}, human_action={"action": "x"}
        )

        body = client.get("/decisions", params={"limit": 3}).json()
        assert body["total"] == 6
        assert len(body["items"]) == 3
        assert body["items"][0]["effect"] == "escalate"  # newest first

        rest = client.get("/decisions", params={"limit": 10, "offset": 3}).json()
        assert len(rest["items"]) == 3
        assert rest["items"][-1]["tx_hash"] == "0x00"  # oldest last


class TestAuditRecords:
    def test_pagination_and_detail(self, app, client: TestClient) -> None:
        records = [seed_decision(app) for _ in range(4)]

        page = client.get("/audit/records", params={"limit": 2}).json()
        assert page["total"] == 4
        assert [r["index"] for r in page["items"]] == [3, 2]  # newest first
        assert page["items"][0]["record_hash"] == records[-1]["record_hash"]

        detail = client.get(f"/audit/records/{records[1]['decision_id']}").json()
        assert detail["record"]["index"] == 1
        assert detail["record"]["prev_hash"] == records[0]["record_hash"]
        assert [n["index"] for n in detail["neighbors"]] == [0, 1, 2, 3]

    def test_unknown_record_404(self, client: TestClient) -> None:
        assert client.get("/audit/records/nope").status_code == 404


class TestChainlessErrors:
    def test_verify_without_state_is_503(self, client: TestClient) -> None:
        assert client.get("/audit/verify/anything").status_code == 503

    def test_anchor_without_state_is_503(self, client: TestClient) -> None:
        assert client.post("/anchor").status_code == 503

    def test_agent_run_without_state_is_503(self, client: TestClient) -> None:
        res = client.post("/agent/run", json={"instruction": "Pay the vendor invoice batch"})
        assert res.status_code == 503

    def test_compliance_without_state_is_unknown(self, client: TestClient) -> None:
        body = client.get(f"/compliance/{ALICE}").json()
        assert body == {"address": ALICE, "known": False, "compliant": None, "frozen": None}

    def test_compliance_rejects_non_address(self, client: TestClient) -> None:
        assert client.get("/compliance/not-an-address").status_code == 400


class TestPolicy:
    def test_policy_roundtrip(self, client: TestClient) -> None:
        body = client.get("/policy").json()
        policy = load_policy(POLICY_PATH)
        assert body["policy_hash"] == policy.policy_hash
        assert body["yaml"] == POLICY_PATH.read_text()
        assert body["default"] == "escalate"
        rule_ids = [r["id"] for r in body["rules"]]
        assert "deny-frozen-party" in rule_ids and "allow-small-compliant-transfer" in rule_ids
        small = next(r for r in body["rules"] if r["id"] == "allow-small-compliant-transfer")
        assert "amount <= 10,000" in small["condition"]
        assert "destination on the allowlist" in small["condition"]


class TestMetrics:
    def test_counts_and_rates(self, app, client: TestClient) -> None:
        for _ in range(3):
            seed_decision(app, effect="allow")
        seed_decision(app, effect="escalate", status="pending_approval")
        client.post("/proposals", json=proposal_body())

        body = client.get("/metrics").json()
        assert body["total_decisions"] == 4
        assert body["counts_by_effect"] == {"allow": 3, "escalate": 1, "deny": 0}
        assert body["escalation_rate"] == pytest.approx(0.25)
        assert body["pending_count"] == 1
        assert body["last_anchor"] is None
        assert body["injections"] is None  # report path points nowhere in this fixture
        # no state.json: nothing is known about a chain, so every field is empty
        assert body["chain"] == {
            "configured": False,
            "connected": False,
            "rpc_url": None,
            "chain_id": None,
            "chain_name": None,
            "public": None,
            "explorer_url": None,
            "anchor_address": None,
            "anchor_url": None,
            # W1: no token to bind to, so the signer is unverified, not "verified by default"
            "guardian_address": None,
            "guardian_verified": False,
        }

    def test_parse_real_eval_report(self) -> None:
        stats = parse_eval_report(REPO_ROOT / "evals" / "report.md")
        assert stats is not None
        assert stats.attacks >= 49
        assert stats.bypasses == 0
        assert stats.blocked == stats.attacks


class TestAgentInstructions:
    def test_canned_instruction_chips(self, client: TestClient) -> None:
        body = client.get("/agent/instructions").json()
        chips = [c["instruction"] for c in body["instructions"]]
        assert len(chips) == 3
        assert "Send 50,000 AGD to the treasury desk" in chips


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live_server(tmp_path: Path):
    """A real uvicorn server for SSE consumption; terminated in teardown."""
    app = create_api_app(make_api_config(tmp_path))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start in 10s")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class TestSseStream:
    def test_events_stream_delivers_proposal_created(self, live_server: str) -> None:
        with (
            httpx.Client(base_url=live_server, timeout=10) as http,
            http.stream("GET", "/events") as stream,
        ):
            lines = stream.iter_lines()
            assert next(lines).startswith(": connected")  # subscribed

            created = http.post("/proposals", json=proposal_body())
            assert created.status_code == 201
            decision_id = created.json()["decision_id"]

            event = None
            for line in lines:
                if line.startswith("data: "):
                    event = json.loads(line[len("data: ") :])
                    break
            assert event is not None
            assert event["type"] == "proposal.created"
            assert event["data"]["decision_id"] == decision_id
