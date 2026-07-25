"""Append-only, hash-chained, Ed25519-signed JSONL audit log.

Each record embeds the hash of its predecessor, so any mutation breaks every
subsequent link. record_hash covers the canonical JSON of the record minus the
hash and signature fields; the signature covers record_hash.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from aegis.audit.canonical import canonical_json, sha256_hex
from aegis.audit.signing import AuditSigner

GENESIS_HASH = "0" * 64

# fields excluded from the hash preimage (derived afterwards)
_DERIVED_FIELDS = ("record_hash", "signature")


class AuditVerificationError(Exception):
    """Raised when the chain, a hash, or a signature does not verify."""


def _hash_record(record: dict[str, Any]) -> str:
    preimage = {k: v for k, v in record.items() if k not in _DERIVED_FIELDS}
    return sha256_hex(canonical_json(preimage))


class AuditLog:
    """Append-only JSONL log bound to one signer."""

    def __init__(self, path: str | Path, signer: AuditSigner) -> None:
        self.path = Path(path)
        self.signer = signer

    def append(
        self,
        *,
        actor: str,
        proposal: dict[str, Any],
        policy_result: dict[str, Any],
        human_action: dict[str, Any] | None = None,
        decision_id: str | None = None,
        ts: str | None = None,
        human_presence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write one record, chaining it to the current tail. Returns the record.

        ``human_presence`` is optional passkey evidence (verified once at
        decide time). When present it joins the payload BEFORE hashing and
        signing, so the chain, Ed25519 signature, and Merkle proofs cover it
        without any change to verification; records without it are unchanged.
        """
        records = self.records()
        prev_hash = records[-1]["record_hash"] if records else GENESIS_HASH
        record: dict[str, Any] = {
            "decision_id": decision_id or str(uuid.uuid4()),
            "ts": ts or dt.datetime.now(dt.UTC).isoformat(),
            "actor": actor,
            "proposal": proposal,
            "policy_result": policy_result,
            "human_action": human_action,
            "prev_hash": prev_hash,
        }
        if human_presence is not None:
            record["human_presence"] = human_presence
        record["record_hash"] = _hash_record(record)
        record["signature"] = self.signer.sign_hex(record["record_hash"].encode())
        with self.path.open("a") as fh:
            fh.write(canonical_json(record).decode() + "\n")
        return record

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def verify(self, public_key_hex: str) -> int:
        """Verify hashes, chain links, and signatures. Returns the record count."""
        return verify_records(self.records(), public_key_hex)


def verify_records(records: list[dict[str, Any]], public_key_hex: str) -> int:
    """Standalone verification of a record list. Raises AuditVerificationError."""
    prev_hash = GENESIS_HASH
    for i, record in enumerate(records):
        if record["prev_hash"] != prev_hash:
            raise AuditVerificationError(f"record {i}: broken chain link")
        if _hash_record(record) != record["record_hash"]:
            raise AuditVerificationError(f"record {i}: record_hash mismatch")
        if not AuditSigner.verify_hex(
            public_key_hex, record["record_hash"].encode(), record["signature"]
        ):
            raise AuditVerificationError(f"record {i}: bad signature")
        prev_hash = record["record_hash"]
    return len(records)
