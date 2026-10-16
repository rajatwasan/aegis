"""W4 tests: the spend ledger reads executed transfers back from the audit log.

Clock and timestamps are injected (AGENTS.md T4): records are written with
explicit ``ts`` values around a fixed "now".
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from aegis.agent.spend import SpendLedger, window_seconds_from_env
from aegis.audit import AuditLog, AuditSigner

ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
NOW = 1_800_000_000.0  # fixed epoch for every test
DAY = 86_400


def iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat()


def make_log(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl", AuditSigner.load_or_create(tmp_path / "audit.key"))


def executed_transfer(log: AuditLog, sender: str, amount: int, at: float, **overrides) -> dict:
    policy_result = {"effect": "allow", "status": "executed", "matched_rules": ["allow-small"]}
    policy_result.update(overrides.pop("policy_result", {}))
    proposal = {"operation": 1, "token": "0xT", "from": sender, "to": BOB, "amount": amount}
    proposal.update(overrides.pop("proposal", {}))
    return log.append(
        actor=overrides.pop("actor", "agent"),
        proposal=proposal,
        policy_result=policy_result,
        ts=iso(at),
    )


class TestSpendLedger:
    def test_spend_ledger_sums_only_executed_transfers_in_window(self, tmp_path: Path) -> None:
        log = make_log(tmp_path)
        executed_transfer(log, ALICE, 1_000, NOW - 10)  # in window
        executed_transfer(log, ALICE, 2_000, NOW - DAY + 1)  # just inside the window edge
        executed_transfer(log, ALICE, 4_000, NOW - DAY)  # exactly one window ago: out
        executed_transfer(log, ALICE, 8_000, NOW - DAY - 5)  # older: out
        executed_transfer(log, ALICE, 16_000, NOW + 60)  # in the future: out
        executed_transfer(log, BOB, 32_000, NOW - 10)  # another sender
        # not auto allowed executions: escalated and pending, denied, mint, service record
        executed_transfer(
            log,
            ALICE,
            64_000,
            NOW - 10,
            policy_result={"effect": "escalate", "status": "pending_approval"},
        )
        executed_transfer(log, ALICE, 128_000, NOW - 10, policy_result={"status": "denied"})
        executed_transfer(log, ALICE, 256_000, NOW - 10, proposal={"operation": 2})
        executed_transfer(log, ALICE, 512_000, NOW - 10, actor="approval-service")

        ledger = SpendLedger(log, window_seconds=DAY, clock=lambda: NOW)
        assert ledger.spent_by(ALICE) == 3_000
        assert ledger.spent_by(ALICE.lower()) == 3_000  # case insensitive
        assert ledger.spent_by(BOB) == 32_000
        assert ledger.spent_for({ALICE, BOB}) == {ALICE.lower(): 3_000, BOB.lower(): 32_000}

    def test_window_rolls_with_the_clock(self, tmp_path: Path) -> None:
        log = make_log(tmp_path)
        executed_transfer(log, ALICE, 5_000, NOW - 100)
        ledger = SpendLedger(log, window_seconds=DAY, clock=lambda: NOW)
        assert ledger.spent_by(ALICE) == 5_000
        assert ledger.spent_by(ALICE, at=NOW + DAY - 150) == 5_000  # window start NOW-150: inside
        assert ledger.spent_by(ALICE, at=NOW + DAY - 50) == 0  # window start NOW-50: rolled out

    def test_a_new_ledger_over_the_same_log_sees_the_spend(self, tmp_path: Path) -> None:
        """Restart safety: the log is the state, not the object (C7)."""
        log = make_log(tmp_path)
        executed_transfer(log, ALICE, 7_000, NOW - 1)
        fresh = SpendLedger(make_log(tmp_path), window_seconds=DAY, clock=lambda: NOW)
        assert fresh.spent_by(ALICE) == 7_000

    def test_unreadable_record_is_an_error_not_zero(self, tmp_path: Path) -> None:
        """A record the ledger cannot read never silently frees budget (C1)."""
        log = make_log(tmp_path)
        executed_transfer(log, ALICE, 1_000, NOW - 10, proposal={"amount": "lots"})
        ledger = SpendLedger(log, window_seconds=DAY, clock=lambda: NOW)
        with pytest.raises(ValueError, match="no usable amount"):
            ledger.spent_by(ALICE)

    def test_window_configuration(self) -> None:
        assert window_seconds_from_env({}) == DAY
        assert window_seconds_from_env({"AEGIS_DAILY_WINDOW_SECONDS": "3600"}) == 3600
        with pytest.raises(ValueError):
            window_seconds_from_env({"AEGIS_DAILY_WINDOW_SECONDS": "0"})
        with pytest.raises(ValueError):
            SpendLedger(make_log(Path("/tmp")), window_seconds=0)
