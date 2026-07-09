"""Guardian EIP-712 signer.

Signs the Authorization struct exactly as GuardianModule.sol hashes it:
domain {name "AegisGuardian", version "1", chainId, verifyingContract=token}.
"""

from __future__ import annotations

import hashlib
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

AUTHORIZATION_TYPES = {
    "Authorization": [
        {"name": "decisionId", "type": "bytes32"},
        {"name": "operation", "type": "uint8"},
        {"name": "token", "type": "address"},
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "id", "type": "uint256"},
        {"name": "amount", "type": "uint256"},
        {"name": "policyHash", "type": "bytes32"},
        {"name": "nonce", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
    ]
}


def decision_id_to_bytes32(decision_id: str) -> bytes:
    """Deterministic bytes32 for a decision-id string (sha256 of its UTF-8)."""
    return hashlib.sha256(decision_id.encode()).digest()


def build_authorization(
    *,
    decision_id: str,
    operation: int,
    token: str,
    from_addr: str,
    to: str,
    asset_class: int,
    amount: int,
    policy_hash: str,
    nonce: int,
    deadline: int,
) -> dict[str, Any]:
    """The message dict signed by the guardian and replayed on-chain verbatim."""
    return {
        "decisionId": decision_id_to_bytes32(decision_id),
        "operation": operation,
        "token": token,
        "from": from_addr,
        "to": to,
        "id": asset_class,
        "amount": amount,
        "policyHash": bytes.fromhex(policy_hash),
        "nonce": nonce,
        "deadline": deadline,
    }


def authorization_to_json(auth: dict[str, Any]) -> dict[str, Any]:
    """Hexify bytes fields so the struct can be stored and shipped as JSON."""
    out = dict(auth)
    for key in ("decisionId", "policyHash"):
        if isinstance(out[key], bytes):
            out[key] = "0x" + out[key].hex()
    return out


def authorization_from_json(auth: dict[str, Any]) -> dict[str, Any]:
    """Inverse of authorization_to_json."""
    out = dict(auth)
    for key in ("decisionId", "policyHash"):
        if isinstance(out[key], str):
            out[key] = bytes.fromhex(out[key].removeprefix("0x"))
    return out


class GuardianSigner:
    """Holds the guardian private key and signs Authorization structs."""

    def __init__(self, private_key: str, chain_id: int) -> None:
        self._account = Account.from_key(private_key)
        self.chain_id = chain_id

    @property
    def address(self) -> str:
        return self._account.address

    def sign_authorization(self, authorization: dict[str, Any]) -> str:
        """Return the 65-byte r||s||v signature as a 0x-hex string."""
        typed = encode_typed_data(
            domain_data={
                "name": "AegisGuardian",
                "version": "1",
                "chainId": self.chain_id,
                "verifyingContract": authorization["token"],
            },
            message_types=AUTHORIZATION_TYPES,
            message_data=authorization,
        )
        signed = self._account.sign_message(typed)
        return "0x" + signed.signature.hex().removeprefix("0x")
