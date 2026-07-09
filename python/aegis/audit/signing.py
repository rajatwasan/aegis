"""Ed25519 signing for audit records.

The private key lives in a git-ignored local file (see AEGIS_AUDIT_KEY_FILE);
only the public key is shared. Tests use a committed fixture keypair.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


class AuditSigner:
    """Wraps an Ed25519 private key with hex-string ergonomics."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key

    @classmethod
    def from_seed_hex(cls, seed_hex: str) -> AuditSigner:
        return cls(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex)))

    @classmethod
    def load_or_create(cls, path: str | Path) -> AuditSigner:
        """Load the key file, generating it (0600) on first use."""
        key_path = Path(path)
        if key_path.exists():
            seed = bytes.fromhex(key_path.read_text().strip())
            return cls(Ed25519PrivateKey.from_private_bytes(seed))
        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.touch(mode=0o600)
        key_path.write_text(seed.hex())
        return cls(key)

    def sign_hex(self, data: bytes) -> str:
        return self._key.sign(data).hex()

    def public_key_hex(self) -> str:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    @staticmethod
    def verify_hex(public_key_hex: str, data: bytes, signature_hex: str) -> bool:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        try:
            key.verify(bytes.fromhex(signature_hex), data)
        except Exception:
            return False
        return True
