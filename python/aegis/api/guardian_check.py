"""Startup check: the configured signer must be the token's on chain guardian.

The approval service signs EIP 712 authorizations with ``AEGIS_GUARDIAN_KEY``.
``GuardedToken`` accepts signatures only from its ``guardian()``. If the two
disagree, every approval the service produces is dead on arrival and the
humans approving them are working for nothing. The check runs once at API
startup whenever chain state exists, and the API refuses to start on either a
mismatch or an unreadable chain (AGENTS.md C8, I5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from web3 import Web3

from aegis.agent.chain import load_artifact
from aegis.errors import GuardianMismatch, GuardianUnverified

_READ_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class GuardianBinding:
    """Result of a successful binding check, surfaced on ``/metrics.chain``."""

    token_address: str
    guardian_address: str
    verified: bool = True


def read_onchain_guardian(rpc_url: str, token_address: str) -> str:
    """Return ``GuardedToken.guardian()`` for ``token_address`` over ``rpc_url``.

    Raises :class:`GuardianUnverified` when the chain cannot be read or the
    address holds no token contract. An unreadable guardian is never treated
    as "no guardian".
    """
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": _READ_TIMEOUT_SECONDS}))
        checksummed = Web3.to_checksum_address(token_address)
        if w3.eth.get_code(checksummed) in (b"", None):
            raise GuardianUnverified("no contract code at the token address", token_address)
        token: Any = w3.eth.contract(address=checksummed, abi=load_artifact("GuardedToken")["abi"])
        return str(token.functions.guardian().call())
    except GuardianUnverified:
        raise
    except Exception as exc:  # noqa: BLE001 - every RPC failure means "could not verify"
        raise GuardianUnverified(f"{type(exc).__name__}: {exc}", token_address) from exc


def verify_guardian_binding(state: dict[str, Any], signer_address: str) -> GuardianBinding:
    """Check the signer against the chain described by ``state`` (state.json).

    Raises :class:`GuardianMismatch` when the on chain guardian differs from
    ``signer_address`` and :class:`GuardianUnverified` when the chain cannot
    be read. Returns the binding on success.
    """
    token_address = state.get("token_address")
    rpc_url = state.get("rpc_url")
    if not token_address or not rpc_url:
        raise GuardianUnverified("state.json has no token_address or rpc_url", str(token_address))
    onchain = read_onchain_guardian(rpc_url, token_address)
    if onchain.lower() != signer_address.lower():
        raise GuardianMismatch(expected=onchain, actual=signer_address, token_address=token_address)
    return GuardianBinding(token_address=token_address, guardian_address=onchain)
