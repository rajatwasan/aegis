"""Property tests: determinism and first-match-wins ordering."""

import random

from aegis.policy import (
    Context,
    Effect,
    Match,
    Operation,
    Policy,
    Predicates,
    Proposal,
    Rule,
    evaluate,
    load_policy,
)
from tests.test_policy_engine import ALICE, BOB, CAROL, DEFAULT_POLICY_PATH, TOKEN


def random_proposal(rng: random.Random) -> Proposal:
    addresses = [ALICE, BOB, CAROL, "0x" + "d" * 40]
    return Proposal(
        operation=rng.choice(list(Operation)),
        token=TOKEN,
        **{"from": rng.choice(addresses)},
        to=rng.choice(addresses),
        asset_class=rng.choice([0, 1, 2]),
        amount=rng.randrange(0, 100_000),
    )


def random_context(rng: random.Random) -> Context:
    addresses = [ALICE, BOB, CAROL]
    return Context(
        compliant={a for a in addresses if rng.random() < 0.5},
        frozen={a for a in addresses if rng.random() < 0.2},
        daily_spent={a: rng.randrange(0, 60_000) for a in addresses if rng.random() < 0.5},
    )


def test_determinism_over_random_inputs() -> None:
    """Same inputs always produce the identical decision."""
    policy = load_policy(DEFAULT_POLICY_PATH)
    rng = random.Random(1337)
    for _ in range(500):
        prop = random_proposal(rng)
        ctx = random_context(rng)
        first = evaluate(prop, ctx, policy)
        second = evaluate(prop, ctx, policy)
        assert first == second


def test_every_decision_is_exhaustive_and_hashed() -> None:
    """Every random input decides to exactly one effect and carries the policy hash."""
    policy = load_policy(DEFAULT_POLICY_PATH)
    rng = random.Random(42)
    for _ in range(500):
        decision = evaluate(random_proposal(rng), random_context(rng), policy)
        assert decision.effect in (Effect.ALLOW, Effect.DENY, Effect.ESCALATE)
        assert decision.policy_hash == policy.policy_hash


def _two_rule_policy(order: list[Rule]) -> Policy:
    return Policy(version=1, rules=tuple(order), default=Effect.ESCALATE, policy_hash="x")


def test_first_match_wins_ordering() -> None:
    """When two rules both match, file order decides the effect."""
    allow_small = Rule(id="allow-small", effect=Effect.ALLOW, when=Predicates(amount_at_most=100))
    deny_transfers = Rule(
        id="deny-transfers", effect=Effect.DENY, match=Match(operation=[Operation.TRANSFER])
    )
    prop = Proposal(operation=Operation.TRANSFER, token=TOKEN, **{"from": ALICE}, to=BOB, amount=50)
    ctx = Context()

    first = evaluate(prop, ctx, _two_rule_policy([allow_small, deny_transfers]))
    swapped = evaluate(prop, ctx, _two_rule_policy([deny_transfers, allow_small]))
    assert first.effect == Effect.ALLOW
    assert first.matched_rules == ("allow-small",)
    assert swapped.effect == Effect.DENY
    assert swapped.matched_rules == ("deny-transfers",)


def test_matched_rule_is_always_earliest_matching() -> None:
    """The reported rule id is always the first rule that structurally matches."""
    rules = [
        Rule(id=f"amount-le-{limit}", effect=Effect.ALLOW, when=Predicates(amount_at_most=limit))
        for limit in (10, 100, 1_000, 10_000)
    ]
    policy = _two_rule_policy(rules)
    rng = random.Random(7)
    for _ in range(200):
        amount = rng.randrange(0, 20_000)
        prop = Proposal(
            operation=Operation.TRANSFER, token=TOKEN, **{"from": ALICE}, to=BOB, amount=amount
        )
        decision = evaluate(prop, Context(), policy)
        expected = next(
            (r.id for r, lim in zip(rules, (10, 100, 1_000, 10_000), strict=True) if amount <= lim),
            None,
        )
        if expected is None:
            assert decision.effect == Effect.ESCALATE
        else:
            assert decision.matched_rules == (expected,)
