"""M4 tests: the guardian signer produces recoverable EIP-712 signatures."""

from eth_account import Account
from eth_account.messages import encode_typed_data

from aegis.approval.signer import (
    AUTHORIZATION_TYPES,
    GuardianSigner,
    authorization_from_json,
    authorization_to_json,
    build_authorization,
    decision_id_to_bytes32,
)

GUARDIAN_KEY = "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6"
TOKEN = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ALICE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def _auth(**overrides):
    base = dict(
        decision_id="4dfc1696-8a5e-4d4f-9091-1cb02d4f00e1",
        operation=1,
        token=TOKEN,
        from_addr=ALICE,
        to=BOB,
        asset_class=0,
        amount=50_000,
        policy_hash="ab" * 32,
        nonce=1,
        deadline=2_000_000_000,
    )
    base.update(overrides)
    return build_authorization(**base)


def test_decision_id_to_bytes32_deterministic() -> None:
    a = decision_id_to_bytes32("abc")
    assert a == decision_id_to_bytes32("abc")
    assert len(a) == 32
    assert a != decision_id_to_bytes32("abd")


def test_signature_recovers_to_guardian_address() -> None:
    signer = GuardianSigner(GUARDIAN_KEY, chain_id=31337)
    auth = _auth()
    signature = signer.sign_authorization(auth)

    typed = encode_typed_data(
        domain_data={
            "name": "AegisGuardian",
            "version": "1",
            "chainId": 31337,
            "verifyingContract": TOKEN,
        },
        message_types=AUTHORIZATION_TYPES,
        message_data=auth,
    )
    assert Account.recover_message(typed, signature=signature) == signer.address


def test_signature_changes_with_fields() -> None:
    signer = GuardianSigner(GUARDIAN_KEY, chain_id=31337)
    assert signer.sign_authorization(_auth()) != signer.sign_authorization(_auth(amount=1))


def test_authorization_json_roundtrip() -> None:
    auth = _auth()
    encoded = authorization_to_json(auth)
    assert isinstance(encoded["decisionId"], str) and encoded["decisionId"].startswith("0x")
    assert authorization_from_json(encoded) == auth
