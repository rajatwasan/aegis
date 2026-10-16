"""A software passkey for tests: produces registration and assertion payloads
that py_webauthn verifies for real (no stubbed verifier, AGENTS.md V4).

The authenticator is one P-256 key. ``registration`` builds a ``none``
attestation (the format browsers return by default), ``assertion`` signs
``authenticator_data || sha256(client_data_json)`` the way a platform
authenticator does. Only the inputs a test cares about are parameters: the
challenge, the origin and the sign count.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass, field

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_ATTESTED_CREDENTIAL = 0x40
AAGUID = bytes(16)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class SoftwarePasskey:
    rp_id: str
    origin: str
    credential_id: bytes = b"test-credential"
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )

    @property
    def credential_id_b64(self) -> str:
        return b64url(self.credential_id)

    def cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind: str, challenge: bytes) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": b64url(challenge), "origin": self.origin}
        ).encode()

    def registration(self, challenge: bytes) -> dict:
        """A ``navigator.credentials.create`` result with ``none`` attestation."""
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([FLAG_USER_PRESENT | FLAG_USER_VERIFIED | FLAG_ATTESTED_CREDENTIAL])
            + struct.pack(">I", 0)
            + AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self.cose_public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", challenge)),
                "attestationObject": b64url(attestation),
            },
        }

    def assertion(self, challenge: bytes, sign_count: int = 1, *, valid: bool = True) -> dict:
        """A ``navigator.credentials.get`` result asserting over ``challenge``.

        ``valid=False`` keeps the payload well formed but signs with a key the
        server never saw, so only the signature check can refuse it.
        """
        client_data = self._client_data("webauthn.get", challenge)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([FLAG_USER_PRESENT | FLAG_USER_VERIFIED])
            + struct.pack(">I", sign_count)
        )
        signer = self.key if valid else ec.generate_private_key(ec.SECP256R1())
        signature = signer.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
            },
        }
