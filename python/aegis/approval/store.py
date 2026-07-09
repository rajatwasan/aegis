"""SQLite (stdlib) persistence for proposals."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    decision_id     TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    status          TEXT NOT NULL,
    created_at      REAL NOT NULL,
    expires_at      REAL NOT NULL,
    proposal        TEXT NOT NULL,
    approvals       TEXT NOT NULL DEFAULT '[]',
    resolution      TEXT,
    authorization   TEXT,
    signature       TEXT,
    nonce           INTEGER
);
CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"


class ProposalStore:
    """Thread-safe wrapper around one SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def create(
        self, proposal: dict[str, Any], ttl_seconds: float, idempotency_key: str | None
    ) -> tuple[dict[str, Any], bool]:
        """Insert a pending proposal. Returns (row, created). With a known
        idempotency key the existing row is returned and created is False."""
        with self._lock, self._conn:
            if idempotency_key is not None:
                row = self._conn.execute(
                    "SELECT * FROM proposals WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if row is not None:
                    return self._to_dict(row), False
            decision_id = str(uuid.uuid4())
            now = time.time()
            self._conn.execute(
                "INSERT INTO proposals (decision_id, idempotency_key, status, created_at,"
                " expires_at, proposal) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    idempotency_key,
                    PENDING,
                    now,
                    now + ttl_seconds,
                    json.dumps(proposal),
                ),
            )
            return self.get(decision_id), True

    def get(self, decision_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return self._to_dict(row) if row is not None else None

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM proposals ORDER BY created_at").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY created_at", (status,)
            ).fetchall()
        return [self._to_dict(r) for r in rows]

    def add_approval(self, decision_id: str, approver: str, comment: str) -> dict[str, Any]:
        with self._lock, self._conn:
            row = self.get(decision_id)
            assert row is not None
            approvals = row["approvals"] + [
                {"approver": approver, "comment": comment, "ts": time.time()}
            ]
            self._conn.execute(
                "UPDATE proposals SET approvals = ? WHERE decision_id = ?",
                (json.dumps(approvals), decision_id),
            )
        return self.get(decision_id)  # type: ignore[return-value]

    def resolve(
        self,
        decision_id: str,
        status: str,
        resolution: dict[str, Any],
        *,
        authorization: dict[str, Any] | None = None,
        signature: str | None = None,
        nonce: int | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE proposals SET status = ?, resolution = ?, authorization = ?,"
                " signature = ?, nonce = ? WHERE decision_id = ?",
                (
                    status,
                    json.dumps(resolution),
                    json.dumps(authorization) if authorization is not None else None,
                    signature,
                    nonce,
                    decision_id,
                ),
            )
        return self.get(decision_id)  # type: ignore[return-value]

    def expire_older_than(self, now: float) -> list[dict[str, Any]]:
        """Mark overdue pending proposals expired; return the affected rows."""
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT decision_id FROM proposals WHERE status = ? AND expires_at <= ?",
                (PENDING, now),
            ).fetchall()
            ids = [r["decision_id"] for r in rows]
            self._conn.execute(
                "UPDATE proposals SET status = ?, resolution = ? WHERE status = ?"
                " AND expires_at <= ?",
                (EXPIRED, json.dumps({"action": "expired", "reason": "ttl"}), PENDING, now),
            )
        return [self.get(i) for i in ids]  # type: ignore[misc]

    def next_nonce(self) -> int:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO counters (name, value) VALUES ('nonce', 0)"
                " ON CONFLICT(name) DO UPDATE SET value = value + 1"
            )
            row = self._conn.execute("SELECT value FROM counters WHERE name = 'nonce'").fetchone()
            return int(row["value"])

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["proposal"] = json.loads(d["proposal"])
        d["approvals"] = json.loads(d["approvals"])
        for key in ("resolution", "authorization"):
            if d[key] is not None:
                d[key] = json.loads(d[key])
        return d
