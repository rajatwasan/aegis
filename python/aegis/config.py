"""Shared configuration primitives: the error type and the key validators.

Every ``from_env`` in the codebase raises :class:`ConfigError` with the name of
the variable that is missing or malformed. Nothing here reads the environment
on its own; callers pass values in so the validators stay pure and testable.
"""

from __future__ import annotations

import os
import re

_HEX_KEY = re.compile(r"^0x[0-9a-fA-F]{64}$")


class ConfigError(RuntimeError):
    """A required setting is missing or malformed. The message names it."""


def require_env(name: str) -> str:
    """Return ``os.environ[name]`` or raise :class:`ConfigError` naming it."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required and is not set")
    return value


def optional_env(name: str) -> str | None:
    """Return the trimmed value or ``None`` when unset or blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def validate_hex_key(value: str, name: str) -> str:
    """A 32 byte private key as ``0x`` plus 64 hex characters, or ConfigError."""
    if not isinstance(value, str) or not _HEX_KEY.match(value.strip()):
        raise ConfigError(f"{name} must be a 0x prefixed 64 hex character private key")
    return value.strip()


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean flag; only ``true``/``false`` (any case) are accepted."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")
