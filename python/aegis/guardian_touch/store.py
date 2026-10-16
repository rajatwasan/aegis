"""SQLite (stdlib) persistence for guardian passkeys.

Lives in the same database file as the approval store: two tables of its own
and nothing else. A pairing code is minted by an authenticated approver and a
credential enrolled with that code is bound to the same approver id, so a
passkey is a second credential of an existing approver, never an identity of
its own (spec W10, decision D9).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

from aegis.errors import ConfigError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_credentials (
    credential_id TEXT PRIMARY KEY,
    approver_id   TEXT NOT NULL,
    public_key    BLOB NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pairing_codes (
    code        TEXT PRIMARY KEY,
    approver_id TEXT NOT NULL,
    expires_at  REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
"""


class GuardianStore:
    """Thread-safe wrapper around the passkey tables of the approval db.

    Reads and writes share one connection across threads, so every statement
    runs under ``_lock`` (see ``ProposalStore``).
    """

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            self._refuse_unbound_tables(db_path)

    def _refuse_unbound_tables(self, db_path: str) -> None:
        """Passkeys enrolled before credentials were bound to an approver have
        nobody to attribute a decision to, so they are not honored. The fix is
        explicit, never a silent re-enrollment (AGENTS.md C9)."""
        for table in ("guardian_credentials", "pairing_codes"):
            columns = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "approver_id" not in columns:
                raise ConfigError(
                    f"{db_path}: table {table} predates approver bound passkeys; delete the"
                    " database (the dev stack recreates it) or drop the guardian_credentials"
                    " and pairing_codes tables, then pair the phone again"
                )

    # ---------------------------------------------------------- pairing codes

    def create_pairing_code(self, code: str, approver_id: str, expires_at: float) -> None:
        """Mint ``code`` for ``approver_id``, dead after the ``expires_at`` epoch."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO pairing_codes (code, approver_id, expires_at, used)"
                " VALUES (?, ?, ?, 0)",
                (code, approver_id, expires_at),
            )

    def get_pairing_code(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pairing_codes WHERE code = ?", (code,)
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_code_used(self, code: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE pairing_codes SET used = 1 WHERE code = ?", (code,))

    # ------------------------------------------------------------ credentials

    def add_credential(
        self, credential_id: str, public_key: bytes, sign_count: int, approver_id: str
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO guardian_credentials"
                " (credential_id, approver_id, public_key, sign_count, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (credential_id, approver_id, public_key, sign_count, time.time()),
            )

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM guardian_credentials WHERE credential_id = ?", (credential_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_credentials(self) -> list[dict[str, Any]]:
        with self._lock:
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
