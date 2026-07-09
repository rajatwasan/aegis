"""M3 tests: hash chain, signatures, tamper detection, key management."""

import json
from pathlib import Path

import pytest

from aegis.audit import (
    GENESIS_HASH,
    AuditLog,
    AuditSigner,
    AuditVerificationError,
    canonical_json,
    verify_records,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEST_SEED = (FIXTURES / "audit_test_seed.hex").read_text().strip()
TEST_PUBLIC = (FIXTURES / "audit_test_public_key.hex").read_text().strip()


@pytest.fixture()
def signer() -> AuditSigner:
    return AuditSigner.from_seed_hex(TEST_SEED)


@pytest.fixture()
def log(tmp_path: Path, signer: AuditSigner) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl", signer)


def _append_n(log: AuditLog, n: int) -> None:
    for i in range(n):
        log.append(
            actor="agent",
            proposal={"operation": 1, "amount": i * 100, "to": "0x" + "b" * 40},
            policy_result={"effect": "allow", "matched_rules": ["r1"]},
            human_action={"approver": "ops"} if i % 2 else None,
        )


class TestChain:
    def test_first_record_uses_genesis_prev_hash(self, log: AuditLog) -> None:
        record = log.append(actor="agent", proposal={}, policy_result={})
        assert record["prev_hash"] == GENESIS_HASH

    def test_records_chain_by_hash(self, log: AuditLog) -> None:
        _append_n(log, 5)
        records = log.records()
        for prev, cur in zip(records, records[1:], strict=False):
            assert cur["prev_hash"] == prev["record_hash"]

    def test_verify_green_chain(self, log: AuditLog) -> None:
        _append_n(log, 7)
        assert log.verify(TEST_PUBLIC) == 7

    def test_verify_with_committed_public_key_fixture(self, log: AuditLog) -> None:
        """The committed public key verifies records produced by the seed's signer."""
        _append_n(log, 3)
        assert verify_records(log.records(), TEST_PUBLIC) == 3

    def test_records_have_required_fields(self, log: AuditLog) -> None:
        _append_n(log, 1)
        record = log.records()[0]
        for field in (
            "decision_id",
            "ts",
            "actor",
            "proposal",
            "policy_result",
            "human_action",
            "prev_hash",
            "record_hash",
            "signature",
        ):
            assert field in record

    def test_decision_ids_are_unique(self, log: AuditLog) -> None:
        _append_n(log, 10)
        ids = [r["decision_id"] for r in log.records()]
        assert len(set(ids)) == 10


class TestTamper:
    def test_mutated_middle_record_breaks_verification(self, log: AuditLog) -> None:
        _append_n(log, 5)
        lines = log.path.read_text().splitlines()
        middle = json.loads(lines[2])
        middle["proposal"]["amount"] = 999_999_999
        lines[2] = canonical_json(middle).decode()
        log.path.write_text("\n".join(lines) + "\n")

        with pytest.raises(AuditVerificationError, match="record 2"):
            log.verify(TEST_PUBLIC)

    def test_recomputed_hash_without_key_still_fails_signature(self, log: AuditLog) -> None:
        """An attacker who fixes up hashes cannot forge signatures without the key."""
        _append_n(log, 3)
        lines = log.path.read_text().splitlines()
        record = json.loads(lines[1])
        record["proposal"]["amount"] = 31337
        preimage = {k: v for k, v in record.items() if k not in ("record_hash", "signature")}
        from aegis.audit import sha256_hex

        record["record_hash"] = sha256_hex(canonical_json(preimage))
        lines[1] = canonical_json(record).decode()
        log.path.write_text("\n".join(lines) + "\n")

        with pytest.raises(AuditVerificationError):
            log.verify(TEST_PUBLIC)

    def test_deleted_record_breaks_chain(self, log: AuditLog) -> None:
        _append_n(log, 4)
        lines = log.path.read_text().splitlines()
        del lines[1]
        log.path.write_text("\n".join(lines) + "\n")
        with pytest.raises(AuditVerificationError, match="broken chain"):
            log.verify(TEST_PUBLIC)

    def test_wrong_public_key_fails(self, log: AuditLog) -> None:
        _append_n(log, 2)
        other = AuditSigner.from_seed_hex("bb" * 32)
        with pytest.raises(AuditVerificationError, match="bad signature"):
            log.verify(other.public_key_hex())


class TestSigner:
    def test_load_or_create_generates_then_reloads(self, tmp_path: Path) -> None:
        key_file = tmp_path / "keys" / "audit.key"
        first = AuditSigner.load_or_create(key_file)
        second = AuditSigner.load_or_create(key_file)
        assert first.public_key_hex() == second.public_key_hex()

    def test_sign_and_verify_roundtrip(self, signer: AuditSigner) -> None:
        sig = signer.sign_hex(b"payload")
        assert AuditSigner.verify_hex(signer.public_key_hex(), b"payload", sig)
        assert not AuditSigner.verify_hex(signer.public_key_hex(), b"other", sig)

    def test_fixture_seed_matches_committed_public_key(self) -> None:
        assert AuditSigner.from_seed_hex(TEST_SEED).public_key_hex() == TEST_PUBLIC


class TestCanonicalJson:
    def test_key_order_independent(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_compact_encoding(self) -> None:
        assert canonical_json({"a": [1, 2]}) == b'{"a":[1,2]}'
