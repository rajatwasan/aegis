"""LangGraph agent: supervisor -> policy gate -> (execute | interrupt -> resume).

The graph pauses (LangGraph interrupt) whenever the policy escalates; resuming
the thread makes the runtime fetch the human's verdict and, if approved,
execute on-chain with the guardian-signed authorization.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from aegis.agent.llm import LLMProvider
from aegis.agent.runtime import AegisRuntime
from aegis.agent.tools import UnknownToolError, validate_action
from aegis.policy import Operation, Proposal

ZERO_ADDRESS = "0x" + "0" * 40


class AgentState(TypedDict, total=False):
    instructions: list[str]
    results: list[dict[str, Any]]
    action: dict[str, Any] | None
    pending_decision_id: str | None


def build_graph(llm: LLMProvider, runtime: AegisRuntime) -> Any:
    def supervisor(state: AgentState) -> AgentState:
        instructions = list(state.get("instructions", []))
        if not instructions:
            return {"action": None}
        instruction = instructions.pop(0)
        action = llm.next_action(instruction, {"operator": runtime.chain.operator_address})
        return {"instructions": instructions, "action": action}

    def act(state: AgentState) -> AgentState:
        action = state.get("action") or {}
        results = list(state.get("results", []))
        try:
            tool, args = validate_action(action)
        except UnknownToolError as exc:
            results.append({"status": "refused", "reason": str(exc)})
            return {"results": results, "pending_decision_id": None}

        if tool == "done":
            return {"results": results, "pending_decision_id": None}
        if tool == "check_compliance":
            results.append(
                {"status": "ok", "tool": tool, "value": runtime.check_compliance(args.address)}
            )
            return {"results": results, "pending_decision_id": None}
        if tool == "get_balance":
            results.append(
                {"status": "ok", "tool": tool, "value": runtime.get_balance(args.address)}
            )
            return {"results": results, "pending_decision_id": None}

        operation = Operation.TRANSFER if tool == "propose_transfer" else Operation.MINT
        proposal = Proposal(
            operation=operation,
            token=args.token,
            **{"from": args.from_addr if tool == "propose_transfer" else ZERO_ADDRESS},
            to=args.to,
            asset_class=args.asset_class,
            amount=args.amount,
        )
        outcome = runtime.handle(proposal)
        results.append(outcome)
        pending = outcome.get("decision_id") if outcome["status"] == "pending_approval" else None
        return {"results": results, "pending_decision_id": pending}

    def await_approval(state: AgentState) -> AgentState:
        decision_id = state["pending_decision_id"]
        interrupt({"decision_id": decision_id, "reason": "policy escalated; human required"})
        outcome = runtime.resume(decision_id)  # runs after the thread is resumed
        results = [*state.get("results", []), outcome]
        return {"results": results, "pending_decision_id": None}

    def route_after_supervisor(state: AgentState) -> str:
        return "act" if state.get("action") else END

    def route_after_act(state: AgentState) -> str:
        return "await_approval" if state.get("pending_decision_id") else "supervisor"

    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("act", act)
    graph.add_node("await_approval", await_approval)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor, {"act": "act", END: END})
    graph.add_conditional_edges(
        "act", route_after_act, {"await_approval": "await_approval", "supervisor": "supervisor"}
    )
    graph.add_edge("await_approval", "supervisor")
    return graph.compile(checkpointer=MemorySaver())
