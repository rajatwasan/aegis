"""Hash-chained, signed audit log with Merkle inclusion proofs."""

from aegis.audit.canonical import canonical_json, sha256_hex
from aegis.audit.log import (
    GENESIS_HASH,
    AuditLog,
    AuditVerificationError,
    verify_records,
)
from aegis.audit.merkle import MerkleTree
from aegis.audit.signing import AuditSigner

__all__ = [
    "GENESIS_HASH",
    "AuditLog",
    "AuditSigner",
    "AuditVerificationError",
    "MerkleTree",
    "canonical_json",
    "sha256_hex",
    "verify_records",
]
