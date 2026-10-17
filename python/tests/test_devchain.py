"""aegis.devchain: the one place that knows the anvil accounts (AGENTS.md R3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from eth_account import Account

from aegis import devchain
from aegis.config import ConfigError
from tests.helpers import fresh_key

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_keys_derive_their_accounts() -> None:
    for index, key in devchain.KEYS.items():
        assert Account.from_key(key).address == devchain.ACCOUNTS[index]


def test_is_dev_key_and_address_are_case_insensitive() -> None:
    assert devchain.is_dev_key(devchain.KEYS[9].upper().replace("0X", "0x"))
    assert devchain.is_dev_address(devchain.ACCOUNTS[4].lower())
    assert not devchain.is_dev_key(fresh_key())
    assert not devchain.is_dev_address(Account.create().address)


def test_dev_chain_ids() -> None:
    assert devchain.is_dev_chain(31337)
    assert devchain.is_dev_chain(1337)
    assert not devchain.is_dev_chain(84532)
    assert not devchain.is_dev_chain(None)


def test_require_not_dev_key_messages_name_role_and_chain_only() -> None:
    devchain.require_not_dev_key(devchain.KEYS[0], "operator", 31337)  # allowed
    with pytest.raises(ConfigError) as excinfo:
        devchain.require_not_dev_key(devchain.KEYS[0], "operator", 8453)
    message = str(excinfo.value)
    assert "operator" in message and "8453" in message
    assert devchain.KEYS[0] not in message


def test_resolve_key_prefers_explicit_and_falls_back_only_on_dev_chain() -> None:
    fresh = fresh_key()
    assert devchain.resolve_key(fresh, role="guardian", chain_id=8453, dev_key="x") == fresh
    assert devchain.resolve_key(None, role="guardian", chain_id=31337, dev_key="x") == "x"
    with pytest.raises(ConfigError):
        devchain.resolve_key(None, role="guardian", chain_id=8453, dev_key="x")
    with pytest.raises(ConfigError):
        devchain.resolve_key(devchain.KEYS[9], role="guardian", chain_id=8453, dev_key="x")


def test_dev_private_keys_appear_nowhere_else_in_the_package() -> None:
    """The hygiene rule, enforced from inside the suite as well as in CI."""
    package = REPO_ROOT / "python" / "aegis"
    pattern = re.compile("|".join(k[2:] for k in devchain.KEYS.values()), re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in package.rglob("*.py")
        if path.name != "devchain.py" and pattern.search(path.read_text())
    ]
    assert offenders == []
