"""SQLite (stdlib) persistence for guardian passkeys.

Lives in the same database file as the approval store: two new tables plus
one nullable ``passkey_assertion`` column on ``proposals`` for embedding the
verified assertion in later audits.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_credentials (
    credential_id TEXT PRIMARY KEY,
    public_key    BLOB NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pairing_codes (
    code       TEXT PRIMARY KEY,
    expires_at REAL NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);
"""


class GuardianStore:
    """Thread-safe wrapper around the passkey tables of the approval db."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(proposals)")]
            if cols and "passkey_assertion" not in cols:
                self._conn.execute("ALTER TABLE proposals ADD COLUMN passkey_assertion TEXT")

    # ---------------------------------------------------------- pairing codes

    def create_pairing_code(self, code: str, ttl_seconds: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO pairing_codes (code, expires_at, used) VALUES (?, ?, 0)",
                (code, time.time() + ttl_seconds),
            )

    def get_pairing_code(self, code: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM pairing_codes WHERE code = ?", (code,)).fetchone()
        return dict(row) if row is not None else None

    def mark_code_used(self, code: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE pairing_codes SET used = 1 WHERE code = ?", (code,))

    # ------------------------------------------------------------ credentials

    def add_credential(self, credential_id: str, public_key: bytes, sign_count: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO guardian_credentials"
                " (credential_id, public_key, sign_count, created_at) VALUES (?, ?, ?, ?)",
                (credential_id, public_key, sign_count, time.time()),
            )

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM guardian_credentials WHERE credential_id = ?", (credential_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_credentials(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM guardian_credentials ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE guardian_credentials SET sign_count = ? WHERE credential_id = ?",
                (sign_count, credential_id),
            )

    # -------------------------------------------------------------- proposals

    def set_proposal_assertion(self, decision_id: str, assertion_json: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE proposals SET passkey_assertion = ? WHERE decision_id = ?",
                (assertion_json, decision_id),
            )
