"""Resolve the two operational private keys from the environment.

``AEGIS_GUARDIAN_KEY`` signs authorizations inside the approval service.
``AEGIS_OPERATOR_KEY`` (alias ``AEGIS_DEPLOYER_KEY``) deploys, pays for
anchors and performs the agent's plain transfers.

Both follow the same rule (SPEC.md section 5, AGENTS.md R2 and R3): an
explicit value is validated and refused if it is a publicly known anvil key on
a public chain; an unset value is substituted with the anvil dev key only on a
dev chain, announced once on stderr; on a public chain an unset value is a
:class:`ConfigError` naming the variable. Private keys never live in
``state.json`` or any other file this package writes.
"""

from __future__ import annotations

import sys

from aegis import devchain
from aegis.config import ConfigError, optional_env, validate_hex_key


def _resolve(
    *, names: tuple[str, ...], role: str, chain_id: int | None, dev_key: str
) -> tuple[str, bool]:
    """Return (key, substituted). ``names`` are tried in order; the first set wins."""
    explicit: str | None = None
    used: str = names[0]
    for name in names:
        value = optional_env(name)
        if value is not None:
            explicit = validate_hex_key(value, name)
            used = name
            break
    try:
        key = devchain.resolve_key(explicit, role=role, chain_id=chain_id, dev_key=dev_key)
    except ConfigError as exc:
        raise ConfigError(f"{used}: {exc}") from exc
    return key, explicit is None


def _announce(role: str, chain_id: int | None, variable: str) -> None:
    print(
        f"notice: {variable} unset; using the anvil dev {role} key"
        f" because chain {chain_id} is a dev chain",
        file=sys.stderr,
    )


def guardian_key_from_env(chain_id: int | None) -> str:
    """The guardian key for ``chain_id`` from ``AEGIS_GUARDIAN_KEY``."""
    key, substituted = _resolve(
        names=("AEGIS_GUARDIAN_KEY",),
        role="guardian",
        chain_id=chain_id,
        dev_key=devchain.dev_guardian_key(),
    )
    if substituted:
        _announce("guardian", chain_id, "AEGIS_GUARDIAN_KEY")
    return key


def operator_key_from_env(chain_id: int | None) -> str:
    """The operator key for ``chain_id`` from ``AEGIS_OPERATOR_KEY`` or its alias."""
    key, substituted = _resolve(
        names=("AEGIS_OPERATOR_KEY", "AEGIS_DEPLOYER_KEY"),
        role="operator",
        chain_id=chain_id,
        dev_key=devchain.dev_operator_key(),
    )
    if substituted:
        _announce("operator", chain_id, "AEGIS_OPERATOR_KEY")
    return key


DEV_POLICY_PATH = "policies/dev.yaml"


def policy_path_from_env(chain_id: int | None) -> str:
    """``AEGIS_POLICY_PATH``, or the dev policy on a dev chain (announced).

    The dev policy allowlists anvil's accounts; on a public chain that would
    pre-approve destinations anyone controls, so the path is required there.
    """
    explicit = optional_env("AEGIS_POLICY_PATH")
    if explicit is not None:
        return explicit
    if devchain.is_dev_chain(chain_id):
        print(
            f"notice: AEGIS_POLICY_PATH unset; using {DEV_POLICY_PATH} because chain"
            f" {chain_id} is a dev chain",
            file=sys.stderr,
        )
        return DEV_POLICY_PATH
    raise ConfigError(
        f"AEGIS_POLICY_PATH is required on chain {chain_id}: the dev policy allowlists"
        " anvil accounts"
    )
