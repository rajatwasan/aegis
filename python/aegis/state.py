"""The deployment state file ``<state_dir>/state.json`` and its rules.

Written by ``aegis.demo`` and ``aegis.devstack``; read by the API, the
anchoring library and the CLI. It carries chain coordinates and addresses only.
A private key in this file is refused on load (AGENTS.md R1, SPEC.md D5):
earlier revisions wrote ``operator_key`` here, and a funded key on disk is
exactly what this file must not be.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis.config import ConfigError

#: keys that must never appear in a state file
FORBIDDEN_STATE_KEYS: tuple[str, ...] = ("operator_key", "guardian_key", "deployer_key")


def validate_state(state: dict[str, Any], path: Path) -> dict[str, Any]:
    present = [k for k in FORBIDDEN_STATE_KEYS if k in state]
    if present:
        raise ConfigError(
            f"{path} contains a private key field ({', '.join(present)}); remove it and"
            " set AEGIS_OPERATOR_KEY in the environment instead"
        )
    return state


def load_chain_state(state_dir: Path) -> dict[str, Any] | None:
    """Read ``state.json`` if the dev/demo stack wrote one; ``None`` when absent."""
    path = state_dir / "state.json"
    if not path.exists():
        return None
    return validate_state(json.loads(path.read_text()), path)
