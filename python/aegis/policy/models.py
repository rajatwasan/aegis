"""Typed boundary models for the policy engine."""

from __future__ import annotations

import hashlib
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Operation(IntEnum):
    """Operation discriminators, matching GuardianModule on-chain constants."""

    TRANSFER = 1
    MINT = 2
    BURN = 3
    FREEZE = 4


class Effect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


def _normalize_address(value: str) -> str:
    return value.lower()


class Proposal(BaseModel):
    """A token operation proposed by the agent."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    operation: Operation
    token: str
    from_addr: str = Field(alias="from")
    to: str
    asset_class: int = 0
    amount: int = Field(ge=0)

    _norm_token = field_validator("token")(_normalize_address)
    _norm_from = field_validator("from_addr")(_normalize_address)
    _norm_to = field_validator("to")(_normalize_address)


class Context(BaseModel):
    """World state the evaluator may consult. Assembled by the caller so the
    evaluator itself stays pure (no clock, no I/O)."""

    model_config = ConfigDict(frozen=True)

    compliant: frozenset[str] = frozenset()
    frozen: frozenset[str] = frozenset()
    daily_spent: dict[str, int] = {}

    @field_validator("compliant", "frozen", mode="before")
    @classmethod
    def _normalize_addresses(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(str(v).lower() for v in value)
        return value

    @field_validator("daily_spent", mode="before")
    @classmethod
    def _normalize_spent_keys(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(k).lower(): v for k, v in value.items()}
        return value


class Match(BaseModel):
    """Structural match conditions. Unset fields match anything."""

    model_config = ConfigDict(frozen=True)

    operation: tuple[Operation, ...] | None = None
    token: tuple[str, ...] | None = None
    asset_class: tuple[int, ...] | None = None

    @field_validator("operation", mode="before")
    @classmethod
    def _parse_operations(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(
                Operation[str(v).upper()] if isinstance(v, str) else Operation(v) for v in value
            )
        return value

    @field_validator("token", mode="before")
    @classmethod
    def _normalize_tokens(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(str(v).lower() for v in value)
        return value

    @field_validator("asset_class", mode="before")
    @classmethod
    def _tuple_classes(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class Predicates(BaseModel):
    """Value predicates. Unset fields hold vacuously; a rule fires only when
    every set predicate holds."""

    model_config = ConfigDict(frozen=True)

    amount_at_most: int | None = None
    amount_above: int | None = None
    destination_known: bool | None = None  # destination in the policy allowlist
    compliant_parties: bool | None = None  # required compliance state of both parties
    frozen_party: bool | None = None  # whether either party is frozen
    within_daily_limit: int | None = None  # spent-so-far + amount <= limit


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    effect: Effect
    match: Match = Match()
    when: Predicates = Predicates()


class Policy(BaseModel):
    """A parsed policy file plus the sha256 of its exact source bytes."""

    model_config = ConfigDict(frozen=True)

    version: int
    allowlist: frozenset[str] = frozenset()
    rules: tuple[Rule, ...]
    default: Effect
    policy_hash: str  # hex sha256 of the raw file bytes

    @field_validator("allowlist", mode="before")
    @classmethod
    def _normalize_allowlist(cls, value: object) -> object:
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(str(v).lower() for v in value)
        return value


class Decision(BaseModel):
    """The evaluator's verdict on one proposal."""

    model_config = ConfigDict(frozen=True)

    effect: Effect
    matched_rules: tuple[str, ...]
    policy_hash: str
    reasons: tuple[str, ...] = ()


def hash_policy_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
