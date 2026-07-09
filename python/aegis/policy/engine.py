"""Deterministic policy evaluator.

`evaluate` is a pure function: same (proposal, context, policy) always yields
the same Decision. Rules are checked in file order; the first rule whose match
conditions and predicates all hold decides the effect. If none match, the
policy's explicit default applies.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from aegis.policy.models import (
    Context,
    Decision,
    Match,
    Policy,
    Predicates,
    Proposal,
    hash_policy_bytes,
)


def load_policy(path: str | Path) -> Policy:
    """Parse a YAML policy file, binding the sha256 of its exact bytes."""
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    return Policy(
        version=data["version"],
        allowlist=data.get("allowlist", []),
        rules=tuple(data.get("rules", [])),
        default=data["default"],
        policy_hash=hash_policy_bytes(raw),
    )


def _matches_structure(match: Match, proposal: Proposal) -> bool:
    if match.operation is not None and proposal.operation not in match.operation:
        return False
    if match.token is not None and proposal.token not in match.token:
        return False
    return not (match.asset_class is not None and proposal.asset_class not in match.asset_class)


def _predicates_hold(
    when: Predicates, proposal: Proposal, context: Context, policy: Policy
) -> bool:
    if when.amount_at_most is not None and proposal.amount > when.amount_at_most:
        return False
    if when.amount_above is not None and proposal.amount <= when.amount_above:
        return False
    if when.destination_known is not None:
        known = proposal.to in policy.allowlist
        if known != when.destination_known:
            return False
    if when.compliant_parties is not None:
        both = proposal.from_addr in context.compliant and proposal.to in context.compliant
        if both != when.compliant_parties:
            return False
    if when.frozen_party is not None:
        any_frozen = proposal.from_addr in context.frozen or proposal.to in context.frozen
        if any_frozen != when.frozen_party:
            return False
    if when.within_daily_limit is not None:
        spent = context.daily_spent.get(proposal.from_addr, 0)
        if spent + proposal.amount > when.within_daily_limit:
            return False
    return True


def evaluate(proposal: Proposal, context: Context, policy: Policy) -> Decision:
    """Evaluate one proposal. First matching rule wins; explicit default otherwise."""
    for rule in policy.rules:
        if _matches_structure(rule.match, proposal) and _predicates_hold(
            rule.when, proposal, context, policy
        ):
            return Decision(
                effect=rule.effect,
                matched_rules=(rule.id,),
                policy_hash=policy.policy_hash,
                reasons=(f"rule '{rule.id}' matched",),
            )
    return Decision(
        effect=policy.default,
        matched_rules=(),
        policy_hash=policy.policy_hash,
        reasons=("no rule matched; policy default applied",),
    )
