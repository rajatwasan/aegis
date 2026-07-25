"""Chain identity and block-explorer links.

An anchored Merkle root is only useful to a third party if they can inspect the
transaction that carried it, so every network the runtime can be pointed at is
described here: a human name plus the explorer base used to build tx and
address links for the console. Unknown chain ids degrade gracefully (name
``chain <id>``, no links) and ``AEGIS_EXPLORER_URL`` overrides the table for
forks and private networks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ChainMeta:
    """What the console needs to describe a chain to a human."""

    chain_id: int | None
    name: str
    explorer_url: str | None = None
    #: False for dev chains (anvil): no public explorer, state is disposable
    public: bool = True


# Networks Aegis is expected to run against. Testnets first — the demo anchors
# to Base Sepolia; mainnets are listed so a production deploy still labels
# itself correctly rather than falling back to "chain 8453".
CHAINS: dict[int, ChainMeta] = {
    31337: ChainMeta(31337, "anvil", None, public=False),
    1337: ChainMeta(1337, "local", None, public=False),
    84532: ChainMeta(84532, "base-sepolia", "https://sepolia.basescan.org"),
    8453: ChainMeta(8453, "base", "https://basescan.org"),
    11155111: ChainMeta(11155111, "sepolia", "https://sepolia.etherscan.io"),
    1: ChainMeta(1, "ethereum", "https://etherscan.io"),
    421614: ChainMeta(421614, "arbitrum-sepolia", "https://sepolia.arbiscan.io"),
    42161: ChainMeta(42161, "arbitrum", "https://arbiscan.io"),
    11155420: ChainMeta(11155420, "optimism-sepolia", "https://sepolia-optimism.etherscan.io"),
    80002: ChainMeta(80002, "polygon-amoy", "https://amoy.polygonscan.com"),
}

UNKNOWN = ChainMeta(None, "unknown chain", None, public=False)


def explorer_from_env() -> str | None:
    """``AEGIS_EXPLORER_URL`` override, for forks and unlisted networks."""
    value = os.environ.get("AEGIS_EXPLORER_URL", "").strip()
    return value.rstrip("/") or None


def chain_meta(chain_id: int | None, explorer_url: str | None = None) -> ChainMeta:
    """Describe a chain id, letting an explicit explorer url win over the table."""
    if chain_id is None:
        base = UNKNOWN
    else:
        base = CHAINS.get(chain_id, ChainMeta(chain_id, f"chain {chain_id}", None))
    override = (explorer_url or "").strip().rstrip("/") or None
    if override is None:
        return base
    return ChainMeta(base.chain_id, base.name, override, public=True)


def hex0x(value: str | bytes | None) -> str | None:
    """Normalize a hash to ``0x``-prefixed hex (anchors.json predates the prefix)."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.hex()
    value = value.strip()
    if not value:
        return None
    return value if value.startswith("0x") else f"0x{value}"


def tx_url(
    chain_id: int | None, tx_hash: str | bytes | None, explorer_url: str | None = None
) -> str | None:
    """Explorer link for one transaction, or None when the chain has no explorer."""
    meta = chain_meta(chain_id, explorer_url)
    digest = hex0x(tx_hash)
    if meta.explorer_url is None or digest is None:
        return None
    return f"{meta.explorer_url}/tx/{digest}"


def address_url(
    chain_id: int | None, address: str | None, explorer_url: str | None = None
) -> str | None:
    """Explorer link for a contract/account, or None when there is no explorer."""
    meta = chain_meta(chain_id, explorer_url)
    if meta.explorer_url is None or not address:
        return None
    return f"{meta.explorer_url}/address/{address}"


def redact_rpc_url(rpc_url: str | None) -> str | None:
    """Strip the path from an RPC url so hosted-provider API keys never ship.

    ``/metrics`` is public and provider urls carry the key in the path
    (``https://host/v2/<key>``). Loopback urls are left intact — they are the
    dev stack's own anvil and the path is empty anyway.
    """
    if not rpc_url:
        return None
    parts = urlsplit(rpc_url)
    if not parts.scheme or not parts.netloc:
        return rpc_url
    if parts.path.strip("/") == "" and not parts.query:
        return f"{parts.scheme}://{parts.netloc}"
    return f"{parts.scheme}://{parts.netloc}/…"
