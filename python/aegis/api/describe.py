"""Human-readable renderings of policy rules for the console UI."""

from __future__ import annotations

from aegis.policy.models import Rule


def describe_rule(rule: Rule) -> str:
    """One-line, human-readable condition under which this rule fires."""
    parts: list[str] = []
    if rule.match.operation is not None:
        names = "/".join(op.name.lower() for op in rule.match.operation)
        parts.append(f"operation is {names}")
    if rule.match.token is not None:
        parts.append(f"token in {sorted(rule.match.token)}")
    if rule.match.asset_class is not None:
        classes = ", ".join(str(c) for c in rule.match.asset_class)
        parts.append(f"asset class in [{classes}]")

    when = rule.when
    if when.amount_at_most is not None:
        parts.append(f"amount <= {when.amount_at_most:,}")
    if when.amount_above is not None:
        parts.append(f"amount > {when.amount_above:,}")
    if when.destination_known is True:
        parts.append("destination on the allowlist")
    if when.destination_known is False:
        parts.append("destination not on the allowlist")
    if when.compliant_parties is True:
        parts.append("both parties compliant")
    if when.compliant_parties is False:
        parts.append("a party is non-compliant")
    if when.frozen_party is True:
        parts.append("a party is frozen")
    if when.frozen_party is False:
        parts.append("no party is frozen")
    if when.within_daily_limit is not None:
        parts.append(f"sender's daily total stays <= {when.within_daily_limit:,}")

    return " and ".join(parts) if parts else "always"
