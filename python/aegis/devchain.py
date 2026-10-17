"""The anvil dev chain accounts, in exactly one place.

anvil derives ten funded accounts from a fixed, publicly documented mnemonic.
They are convenient for a local demo and useless as secrets: anyone who has
read the anvil docs holds every one of these keys. This module exists so that

* the demo, the dev stack, the evals and the tests share one definition,
* the rest of ``aegis`` never spells a dev key or address, and
* code that targets a public chain can refuse them (AGENTS.md R3).

``scripts/check_hygiene.sh`` fails the build if a dev private key appears
anywhere outside this module and ``python/tests/``.
"""

from __future__ import annotations

from aegis.config import ConfigError

#: anvil's default accounts (``anvil`` prints them at startup)
ACCOUNTS: dict[int, str] = {
    0: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    1: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    2: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    3: "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    4: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    5: "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
    6: "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    7: "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
    8: "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f",
    9: "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720",
}

#: the two dev keys the demo world needs: account 0 operates, account 9 guards
KEYS: dict[int, str] = {
    0: "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    9: "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",
}

#: chain ids that are disposable local chains; everything else is public
DEV_CHAIN_IDS: frozenset[int] = frozenset({31337, 1337})

#: the roles the demo world assigns to anvil accounts
OPERATOR_INDEX = 0
GUARDIAN_INDEX = 9
COMPLIANT_INDICES = (0, 1, 2, 3)
FROZEN_INDEX = 4

_DEV_KEYS_LOWER = frozenset(k.lower() for k in KEYS.values())
_DEV_ADDRESSES_LOWER = frozenset(a.lower() for a in ACCOUNTS.values())


def is_dev_chain(chain_id: int | None) -> bool:
    """True for anvil and other throwaway local chain ids."""
    return chain_id is not None and chain_id in DEV_CHAIN_IDS


def is_dev_key(private_key: str) -> bool:
    """True when ``private_key`` is one of anvil's publicly known keys."""
    return private_key.strip().lower() in _DEV_KEYS_LOWER


def is_dev_address(address: str) -> bool:
    """True when ``address`` is one of anvil's ten default accounts."""
    return address.strip().lower() in _DEV_ADDRESSES_LOWER


def dev_guardian_key() -> str:
    return KEYS[GUARDIAN_INDEX]


def dev_operator_key() -> str:
    return KEYS[OPERATOR_INDEX]


def require_not_dev_key(private_key: str, role: str, chain_id: int | None) -> None:
    """Refuse a publicly known key for ``role`` unless the chain is a dev chain.

    Raises :class:`ConfigError` naming the role and the chain id, never the key.
    """
    if is_dev_key(private_key) and not is_dev_chain(chain_id):
        raise ConfigError(
            f"the {role} key is a publicly known anvil dev key and chain {chain_id}"
            " is not a dev chain; generate a real key for this deployment"
        )


def resolve_key(explicit: str | None, *, role: str, chain_id: int | None, dev_key: str) -> str:
    """Pick the key for ``role``: the explicit value, or the dev key on a dev chain.

    On a public chain the explicit value is mandatory and must not be a dev key.
    Callers print the substitution once so a dev default never passes unnoticed.
    """
    if explicit:
        require_not_dev_key(explicit, role, chain_id)
        return explicit
    if is_dev_chain(chain_id):
        return dev_key
    raise ConfigError(
        f"no {role} key configured and chain {chain_id} is not a dev chain;"
        f" set the {role} key explicitly"
    )
