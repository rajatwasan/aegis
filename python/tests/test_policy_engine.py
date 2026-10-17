"""Unit tests for the policy evaluator: every branch of engine.py."""

from pathlib import Path

import pytest

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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / "policies" / "dev.yaml"

ALICE = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BOB = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"  # allowlisted in dev.yaml
CAROL = "0xcccccccccccccccccccccccccccccccccccccccc"
TOKEN = "0x5fbdb2315678afecb367f032d93f642f64180aa3"


def proposal(**overrides) -> Proposal:
    base = {
        "operation": Operation.TRANSFER,
        "token": TOKEN,
        "from": ALICE,
        "to": BOB,
        "asset_class": 0,
        "amount": 100,
    }
    base.update(overrides)
    return Proposal(**base)


def make_policy(rules: list[Rule], default: Effect = Effect.ESCALATE, **kw) -> Policy:
    return Policy(
        version=1,
        rules=tuple(rules),
        default=default,
        policy_hash="deadbeef",
        **kw,
    )


COMPLIANT_CTX = Context(compliant={ALICE, BOB})


class TestLoadPolicy:
    def test_loads_default_policy_with_hash(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        assert policy.version == 1
        assert len(policy.rules) == 5
        assert policy.default == Effect.ESCALATE
        assert len(policy.policy_hash) == 64
        assert BOB in policy.allowlist

    def test_hash_tracks_exact_bytes(self, tmp_path: Path) -> None:
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text("version: 1\nrules: []\ndefault: deny\n")
        b.write_text("version: 1\nrules: []\ndefault: deny\n# comment\n")
        assert load_policy(a).policy_hash != load_policy(b).policy_hash

    def test_missing_optional_sections(self, tmp_path: Path) -> None:
        p = tmp_path / "min.yaml"
        p.write_text("version: 1\ndefault: allow\n")
        policy = load_policy(p)
        assert policy.rules == ()
        assert policy.allowlist == frozenset()


class TestStructuralMatch:
    def test_unconstrained_rule_matches_everything(self) -> None:
        rules = [Rule(id="all", effect=Effect.DENY)]
        decision = evaluate(proposal(), COMPLIANT_CTX, make_policy(rules))
        assert decision.effect == Effect.DENY
        assert decision.matched_rules == ("all",)

    def test_operation_match_and_mismatch(self) -> None:
        rules = [Rule(id="mints", effect=Effect.DENY, match=Match(operation=[Operation.MINT]))]
        policy = make_policy(rules, default=Effect.ALLOW)
        assert evaluate(proposal(operation=Operation.MINT), COMPLIANT_CTX, policy).effect == (
            Effect.DENY
        )
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.ALLOW

    def test_token_match_and_mismatch(self) -> None:
        rules = [Rule(id="tok", effect=Effect.DENY, match=Match(token=[TOKEN.upper()]))]
        policy = make_policy(rules, default=Effect.ALLOW)
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.DENY
        assert evaluate(proposal(token="0x" + "1" * 40), COMPLIANT_CTX, policy).effect == (
            Effect.ALLOW
        )

    def test_asset_class_match_and_mismatch(self) -> None:
        rules = [Rule(id="cls", effect=Effect.DENY, match=Match(asset_class=[7]))]
        policy = make_policy(rules, default=Effect.ALLOW)
        assert evaluate(proposal(asset_class=7), COMPLIANT_CTX, policy).effect == Effect.DENY
        assert evaluate(proposal(asset_class=1), COMPLIANT_CTX, policy).effect == Effect.ALLOW


class TestPredicates:
    def test_amount_at_most(self) -> None:
        rules = [Rule(id="small", effect=Effect.ALLOW, when=Predicates(amount_at_most=100))]
        policy = make_policy(rules, default=Effect.DENY)
        assert evaluate(proposal(amount=100), COMPLIANT_CTX, policy).effect == Effect.ALLOW
        assert evaluate(proposal(amount=101), COMPLIANT_CTX, policy).effect == Effect.DENY

    def test_amount_above(self) -> None:
        rules = [Rule(id="big", effect=Effect.ESCALATE, when=Predicates(amount_above=100))]
        policy = make_policy(rules, default=Effect.ALLOW)
        assert evaluate(proposal(amount=101), COMPLIANT_CTX, policy).effect == Effect.ESCALATE
        assert evaluate(proposal(amount=100), COMPLIANT_CTX, policy).effect == Effect.ALLOW

    def test_destination_known(self) -> None:
        rules = [Rule(id="known", effect=Effect.ALLOW, when=Predicates(destination_known=True))]
        policy = make_policy(rules, default=Effect.DENY, allowlist=[BOB])
        assert evaluate(proposal(to=BOB), COMPLIANT_CTX, policy).effect == Effect.ALLOW
        assert evaluate(proposal(to=CAROL), COMPLIANT_CTX, policy).effect == Effect.DENY

    def test_destination_unknown_predicate(self) -> None:
        rules = [
            Rule(id="unknown", effect=Effect.ESCALATE, when=Predicates(destination_known=False))
        ]
        policy = make_policy(rules, default=Effect.ALLOW, allowlist=[BOB])
        assert evaluate(proposal(to=CAROL), COMPLIANT_CTX, policy).effect == Effect.ESCALATE
        assert evaluate(proposal(to=BOB), COMPLIANT_CTX, policy).effect == Effect.ALLOW

    def test_compliant_parties(self) -> None:
        rules = [Rule(id="kyc", effect=Effect.ALLOW, when=Predicates(compliant_parties=True))]
        policy = make_policy(rules, default=Effect.DENY)
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.ALLOW
        assert evaluate(proposal(to=CAROL), COMPLIANT_CTX, policy).effect == Effect.DENY

    def test_non_compliance_predicate(self) -> None:
        rules = [Rule(id="nokyc", effect=Effect.DENY, when=Predicates(compliant_parties=False))]
        policy = make_policy(rules, default=Effect.ALLOW)
        assert evaluate(proposal(to=CAROL), COMPLIANT_CTX, policy).effect == Effect.DENY
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.ALLOW

    def test_frozen_party(self) -> None:
        rules = [Rule(id="ice", effect=Effect.DENY, when=Predicates(frozen_party=True))]
        policy = make_policy(rules, default=Effect.ALLOW)
        frozen_ctx = Context(compliant={ALICE, BOB}, frozen={BOB})
        assert evaluate(proposal(), frozen_ctx, policy).effect == Effect.DENY
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.ALLOW

    def test_frozen_party_false_predicate(self) -> None:
        rules = [Rule(id="warm", effect=Effect.ALLOW, when=Predicates(frozen_party=False))]
        policy = make_policy(rules, default=Effect.DENY)
        frozen_ctx = Context(frozen={ALICE})
        assert evaluate(proposal(), COMPLIANT_CTX, policy).effect == Effect.ALLOW
        assert evaluate(proposal(), frozen_ctx, policy).effect == Effect.DENY

    def test_within_daily_limit(self) -> None:
        rules = [Rule(id="rate", effect=Effect.ALLOW, when=Predicates(within_daily_limit=1000))]
        policy = make_policy(rules, default=Effect.ESCALATE)
        ctx_spent = Context(daily_spent={ALICE: 950})
        assert evaluate(proposal(amount=50), ctx_spent, policy).effect == Effect.ALLOW
        assert evaluate(proposal(amount=51), ctx_spent, policy).effect == Effect.ESCALATE

    def test_daily_limit_defaults_to_zero_spent(self) -> None:
        rules = [Rule(id="rate", effect=Effect.ALLOW, when=Predicates(within_daily_limit=1000))]
        policy = make_policy(rules, default=Effect.ESCALATE)
        assert evaluate(proposal(amount=1000), Context(), policy).effect == Effect.ALLOW


class TestDefaultAndOrdering:
    def test_explicit_default_when_no_rule_matches(self) -> None:
        rules = [Rule(id="mints", effect=Effect.DENY, match=Match(operation=[Operation.MINT]))]
        decision = evaluate(proposal(), COMPLIANT_CTX, make_policy(rules))
        assert decision.effect == Effect.ESCALATE
        assert decision.matched_rules == ()

    def test_decision_carries_policy_hash(self) -> None:
        decision = evaluate(proposal(), COMPLIANT_CTX, make_policy([]))
        assert decision.policy_hash == "deadbeef"


class TestDefaultPolicyFile:
    @pytest.fixture()
    def policy(self) -> Policy:
        return load_policy(DEFAULT_POLICY_PATH)

    def test_small_compliant_transfer_allowed(self, policy: Policy) -> None:
        decision = evaluate(proposal(amount=500), COMPLIANT_CTX, policy)
        assert decision.effect == Effect.ALLOW
        assert decision.matched_rules == ("allow-small-compliant-transfer",)

    def test_large_transfer_escalates(self, policy: Policy) -> None:
        decision = evaluate(proposal(amount=10_001), COMPLIANT_CTX, policy)
        assert decision.effect == Effect.ESCALATE
        assert decision.matched_rules == ("escalate-large-transfer",)

    def test_unknown_destination_escalates(self, policy: Policy) -> None:
        ctx = Context(compliant={ALICE, CAROL})
        decision = evaluate(proposal(to=CAROL, amount=5), ctx, policy)
        assert decision.effect == Effect.ESCALATE
        assert decision.matched_rules == ("escalate-unknown-destination",)

    def test_frozen_address_denied(self, policy: Policy) -> None:
        ctx = Context(compliant={ALICE, BOB}, frozen={ALICE})
        decision = evaluate(proposal(amount=5), ctx, policy)
        assert decision.effect == Effect.DENY
        assert decision.matched_rules == ("deny-frozen-party",)

    def test_mint_escalates(self, policy: Policy) -> None:
        decision = evaluate(proposal(operation=Operation.MINT, amount=5), COMPLIANT_CTX, policy)
        assert decision.effect == Effect.ESCALATE
        assert decision.matched_rules == ("escalate-supply-and-freeze",)

    def test_daily_limit_breach_escalates(self, policy: Policy) -> None:
        ctx = Context(compliant={ALICE, BOB}, daily_spent={ALICE: 49_000})
        decision = evaluate(proposal(amount=2_000), ctx, policy)
        assert decision.effect == Effect.ESCALATE

    def test_non_compliant_small_transfer_not_allowed(self, policy: Policy) -> None:
        ctx = Context(compliant={ALICE})  # bob lacks kyc
        decision = evaluate(proposal(amount=5), ctx, policy)
        assert decision.effect == Effect.ESCALATE
