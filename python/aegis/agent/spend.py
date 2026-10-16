"""Per sender spend over a rolling window, derived from the audit log.

The policy predicate ``within_daily_limit`` needs to know how much a sender has
already moved through the auto allowed path. That number used to live in a
dict on the runtime: it reset on every restart and never rolled within the
day, so a limit was only ever enforced against what one process happened to
have seen (AGENTS.md C7). The audit log already records every executed
transfer, signed and chained, so it is the single source of truth here: a
restart cannot forget spend, and the window actually rolls.

Only auto allowed executions count. An escalated transfer that a human
approved is recorded as a resumed execution without a proposal payload and is
by design not charged against the automatic budget: a human looked at it.

Spec: docs/specs/2026-10-hardening.md W4, decision D5.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Callable
from typing import Any

from aegis.audit import AuditLog
from aegis.policy import Operation

DEFAULT_WINDOW_SECONDS = 86_400
WINDOW_ENV = "AEGIS_DAILY_WINDOW_SECONDS"


def window_seconds_from_env(environ: dict[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    raw = env.get(WINDOW_ENV, "").strip()
    if not raw:
        return DEFAULT_WINDOW_SECONDS
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{WINDOW_ENV} must be a positive number of seconds")
    return value


def _record_epoch(record: dict[str, Any]) -> float | None:
    """Epoch seconds for a record's ISO 8601 timestamp, None if it is unusable."""
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


class SpendLedger:
    """Sums executed, auto allowed transfers per sender inside a trailing window."""

    def __init__(
        self,
        audit: AuditLog,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.audit = audit
        self.window_seconds = window_seconds
        self.clock = clock

    def spent_by(self, sender: str, at: float | None = None) -> int:
        """Amount ``sender`` moved through executed, auto allowed transfers in the window.

        A record counts when: actor is ``agent``, the policy effect was ``allow``
        and the status ``executed``, the proposal is a transfer from ``sender``,
        and ``at - window < ts <= at``. Records that cannot be read (no
        timestamp, no amount) are skipped as unreadable, never as zero spend
        that silently frees budget: they are counted as an error by raising.
        """
        now = self.clock() if at is None else at
        start = now - self.window_seconds
        sender = sender.lower()
        total = 0
        for record in self.audit.records():
            if record.get("actor") != "agent":
                continue
            policy_result = record.get("policy_result") or {}
            if policy_result.get("effect") != "allow" or policy_result.get("status") != "executed":
                continue
            proposal = record.get("proposal") or {}
            if proposal.get("operation") != Operation.TRANSFER:
                continue
            if str(proposal.get("from", "")).lower() != sender:
                continue
            epoch = _record_epoch(record)
            if epoch is None:
                raise ValueError(f"audit record {record.get('decision_id')} has no usable ts")
            if not (start < epoch <= now):
                continue
            amount = proposal.get("amount")
            if not isinstance(amount, int):
                raise ValueError(f"audit record {record.get('decision_id')} has no usable amount")
            total += amount
        return total

    def spent_for(self, senders: set[str], at: float | None = None) -> dict[str, int]:
        return {sender.lower(): self.spent_by(sender, at) for sender in senders}
