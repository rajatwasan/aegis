"""AegisRuntime: policy gate + execution + audit for one operator agent.

The runtime is the trusted layer between the (untrusted) LLM and the chain.
Every proposal passes through the deterministic policy engine; only ALLOW
executes directly, ESCALATE goes to the human approval service, DENY stops
dead. Every decision is written to the hash-chained audit log.
"""

from __future__ import annotations

from typing import Any

import httpx

from aegis.agent.chain import ChainClient
from aegis.audit import AuditLog
from aegis.policy import Context, Decision, Effect, Operation, Policy, Proposal, evaluate


class AegisRuntime:
    def __init__(
        self,
        *,
        policy: Policy,
        audit: AuditLog,
        chain: ChainClient,
        token: Any,
        registry: Any,
        approval_client: httpx.Client,
    ) -> None:
        self.policy = policy
        self.audit = audit
        self.chain = chain
        self.token = token
        self.registry = registry
        self.approval = approval_client
        self.daily_spent: dict[str, int] = {}

    # ------------------------------------------------------------- read tools

    def check_compliance(self, address: str) -> bool:
        return self.registry.functions.isCompliant(
            self.chain.w3.to_checksum_address(address)
        ).call()

    def get_balance(self, address: str) -> int:
        return self.token.functions.balanceOf(self.chain.w3.to_checksum_address(address)).call()

    def is_frozen(self, address: str) -> bool:
        return self.token.functions.frozen(self.chain.w3.to_checksum_address(address)).call()

    # ------------------------------------------------------------ policy gate

    def build_context(self, proposal: Proposal) -> Context:
        parties = {proposal.from_addr, proposal.to}
        compliant = {p for p in parties if self.check_compliance(p)}
        frozen = {p for p in parties if self.is_frozen(p)}
        return Context(compliant=compliant, frozen=frozen, daily_spent=dict(self.daily_spent))

    def decide(self, proposal: Proposal) -> Decision:
        return evaluate(proposal, self.build_context(proposal), self.policy)

    # -------------------------------------------------------------- lifecycle

    def handle(self, proposal: Proposal) -> dict[str, Any]:
        """Gate a proposal; execute, deny, or submit for human approval."""
        decision = self.decide(proposal)
        result: dict[str, Any] = {
            "proposal": proposal.model_dump(by_alias=True, mode="json"),
            "effect": decision.effect.value,
            "matched_rules": list(decision.matched_rules),
        }

        if decision.effect == Effect.ALLOW:
            receipt = self.chain.transfer(self.token, proposal.to, proposal.amount)
            self.daily_spent[proposal.from_addr] = (
                self.daily_spent.get(proposal.from_addr, 0) + proposal.amount
            )
            result["tx_hash"] = receipt["transactionHash"].hex()
            result["status"] = "executed"
            self._audit("agent", result)
        elif decision.effect == Effect.DENY:
            result["status"] = "denied"
            self._audit("agent", result)
        else:  # ESCALATE
            response = self.approval.post(
                "/proposals",
                json={
                    **proposal.model_dump(by_alias=True, mode="json"),
                    "policy_result": {
                        "effect": decision.effect.value,
                        "matched_rules": list(decision.matched_rules),
                        "policy_hash": decision.policy_hash,
                    },
                },
            )
            response.raise_for_status()
            result["status"] = "pending_approval"
            result["decision_id"] = response.json()["decision_id"]
            self._audit("agent", result)
        return result

    def resume(self, decision_id: str) -> dict[str, Any]:
        """After the human acted: execute if approved, report otherwise."""
        response = self.approval.get(f"/proposals/{decision_id}")
        response.raise_for_status()
        row = response.json()
        result: dict[str, Any] = {"decision_id": decision_id, "approval_status": row["status"]}

        if row["status"] == "approved":
            operation = row["proposal"]["operation"]
            if operation == Operation.MINT:
                receipt = self.chain.mint_with_authorization(
                    self.token, row["authorization"], row["signature"]
                )
            else:
                receipt = self.chain.transfer_with_authorization(
                    self.token, row["authorization"], row["signature"]
                )
            result["tx_hash"] = receipt["transactionHash"].hex()
            result["status"] = "executed"
        else:
            result["status"] = row["status"]

        self._audit("agent", result)
        return result

    def _audit(self, actor: str, result: dict[str, Any]) -> None:
        self.audit.append(
            actor=actor,
            proposal=result.get("proposal", {"decision_id": result.get("decision_id")}),
            policy_result={
                "effect": result.get("effect"),
                "matched_rules": result.get("matched_rules", []),
                "status": result["status"],
                "tx_hash": result.get("tx_hash"),
            },
        )
