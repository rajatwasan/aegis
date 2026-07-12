"""Background agent runs for POST /agent/run.

Each run drives the M5 LangGraph agent in a worker thread, emitting an
``agent.step`` event on the bus for every node the graph executes. With the
default MockLLM, a small set of canned instructions maps to scripted tool
plans so the whole loop works without any model key; when the graph escalates,
the runner polls the approval store until a human resolves the proposal (the
Guardian Console's approve button), then resumes the thread.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from langgraph.types import Command

from aegis.agent import AegisRuntime, ChainClient, MockLLM, build_graph
from aegis.anchoring import StateError
from aegis.api.config import ApiConfig, load_chain_state
from aegis.events import EventBus

# anvil's fixed dev accounts, matching the demo/dev deployment
_ACCOUNTS = {
    1: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    2: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    3: "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    4: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
}
FROZEN_ACCOUNT = _ACCOUNTS[4]


def _transfer(token: str, operator: str, to: str, amount: int) -> dict[str, Any]:
    return {
        "tool": "propose_transfer",
        "args": {"token": token, "from": operator, "to": to, "amount": amount},
    }


def canned_plans(token: str, operator: str) -> dict[str, dict[str, Any]]:
    """The MockLLM's scripted plans, keyed by normalized instruction."""
    plans = {
        "pay the vendor invoice batch": {
            "description": "Three small compliant transfers that auto-execute under policy",
            "plan": [
                {"tool": "check_compliance", "args": {"address": _ACCOUNTS[1]}},
                _transfer(token, operator, _ACCOUNTS[1], 1_200),
                _transfer(token, operator, _ACCOUNTS[2], 2_500),
                _transfer(token, operator, _ACCOUNTS[3], 3_400),
            ],
        },
        "send 50,000 agd to the treasury desk": {
            "description": "A large transfer that escalates to a human guardian",
            "plan": [
                {"tool": "check_compliance", "args": {"address": _ACCOUNTS[1]}},
                _transfer(token, operator, _ACCOUNTS[1], 50_000),
            ],
        },
        "refund 10 agd to the frozen counterparty": {
            "description": "A transfer to a frozen address the policy denies outright",
            "plan": [_transfer(token, operator, FROZEN_ACCOUNT, 10)],
        },
    }
    return plans


def canned_instructions() -> list[dict[str, str]]:
    """Instruction chips for the console (plan bodies need live addresses)."""
    placeholder = canned_plans(token="0x0", operator="0x0")
    return [
        {"instruction": _title(key), "description": value["description"]}
        for key, value in placeholder.items()
    ]


def _title(normalized: str) -> str:
    # present the canonical chip text with its original capitalization
    return normalized[0].upper() + normalized[1:].replace("agd", "AGD")


def _normalize(instruction: str) -> str:
    return " ".join(instruction.split()).casefold()


@dataclass
class AgentRun:
    run_id: str
    instruction: str
    status: str = "running"
    thread: threading.Thread | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class AgentRunner:
    """Owns the shared runtime and one worker thread per run (serialized)."""

    def __init__(self, config: ApiConfig, bus: EventBus, app: Any) -> None:
        self.config = config
        self.bus = bus
        self.app = app
        self.runs: dict[str, AgentRun] = {}
        self._runtime: AegisRuntime | None = None
        self._chain_state: dict[str, Any] | None = None
        self._lock = threading.Lock()  # one run at a time: shared operator nonce

    # ------------------------------------------------------------ runtime

    def _ensure_runtime(self) -> tuple[AegisRuntime, dict[str, Any]]:
        if self._runtime is not None and self._chain_state is not None:
            return self._runtime, self._chain_state
        state = load_chain_state(Path(self.config.state_dir))
        if state is None:
            raise StateError(
                f"no chain state at {self.config.state_dir}/state.json;"
                " start the dev stack (make dev) or run scripts/demo.sh first"
            )
        chain = ChainClient(state["rpc_url"], state["operator_key"])
        self._runtime = AegisRuntime(
            policy=self.app.state.policy,
            audit=self.app.state.audit,  # the emitting log: decisions hit the bus
            chain=chain,
            token=chain.at("GuardedToken", state["token_address"]),
            registry=chain.at("ComplianceRegistry", state["registry_address"]),
            approval_client=TestClient(self.app),
        )
        self._chain_state = state
        return self._runtime, self._chain_state

    # ------------------------------------------------------------ public

    def runtime(self) -> AegisRuntime:
        """The shared runtime (compliance/frozen reads); StateError if no chain."""
        runtime, _ = self._ensure_runtime()
        return runtime

    def start(self, instruction: str) -> AgentRun:
        """Validate the instruction, then run the agent in a worker thread."""
        runtime, state = self._ensure_runtime()
        plans = canned_plans(state["token_address"], runtime.chain.operator_address)
        entry = plans.get(_normalize(instruction))
        if entry is None:
            known = ", ".join(f"'{_title(k)}'" for k in plans)
            raise UnknownInstructionError(
                f"the keyless MockLLM only understands the canned instructions: {known}"
            )

        run = AgentRun(run_id=str(uuid.uuid4()), instruction=instruction)
        self.runs[run.run_id] = run
        run.thread = threading.Thread(
            target=self._run, args=(run, runtime, list(entry["plan"])), daemon=True
        )
        run.thread.start()
        return run

    def wait(self, run_id: str, timeout: float = 60.0) -> AgentRun:
        """Block until a run's worker thread finishes (test helper)."""
        run = self.runs[run_id]
        assert run.thread is not None
        run.thread.join(timeout)
        return run

    # ------------------------------------------------------------ worker

    def _step(self, run: AgentRun, phase: str, **data: Any) -> None:
        self.bus.publish(
            "agent.step",
            {"run_id": run.run_id, "instruction": run.instruction, "phase": phase, **data},
        )

    def _run(self, run: AgentRun, runtime: AegisRuntime, plan: list[dict[str, Any]]) -> None:
        with self._lock:
            try:
                self._drive(run, runtime, plan)
                run.status = "finished"
            except Exception as exc:  # noqa: BLE001 - surfaced as an event
                run.status = "failed"
                run.error = str(exc)
                self._step(run, "failed", error=str(exc))
                return
            self._step(run, "finished", results=run.results)

    def _drive(self, run: AgentRun, runtime: AegisRuntime, plan: list[dict[str, Any]]) -> None:
        graph = build_graph(MockLLM(script=plan), runtime)
        graph_config = {"configurable": {"thread_id": run.run_id}}
        self._step(run, "started", steps_planned=len(plan))

        payload: Any = {
            "instructions": [f"{run.instruction} [step {i + 1}]" for i in range(len(plan))],
            "results": [],
        }
        while True:
            pending_decision: str | None = None
            for chunk in graph.stream(payload, graph_config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        pending_decision = update[0].value["decision_id"]
                        self._step(run, "awaiting_approval", decision_id=pending_decision)
                    else:
                        self._emit_node_step(run, node, update)
            if pending_decision is None:
                break
            status = self._await_human(run, pending_decision)
            if status == "pending":  # timed out waiting; leave the thread parked
                self._step(run, "abandoned", decision_id=pending_decision)
                return
            payload = Command(resume=status)

        state = graph.get_state(graph_config)
        run.results = list(state.values.get("results", []))

    def _emit_node_step(self, run: AgentRun, node: str, update: dict[str, Any] | None) -> None:
        update = update or {}
        data: dict[str, Any] = {"node": node}
        if node == "supervisor":
            data["action"] = update.get("action")
        elif node in ("act", "await_approval"):
            results = update.get("results") or []
            if results:
                data["result"] = results[-1]
                run.results = list(results)
        self._step(run, "node", **data)

    def _await_human(self, run: AgentRun, decision_id: str) -> str:
        """Poll the approval store until the human resolves (or we time out)."""
        deadline = time.monotonic() + self.config.approval_wait_seconds
        store = self.app.state.store
        while time.monotonic() < deadline:
            row = store.get(decision_id)
            status = row["status"] if row is not None else "pending"
            if status != "pending":
                self._step(run, "approval_resolved", decision_id=decision_id, status=status)
                return status
            time.sleep(self.config.approval_poll_seconds)
        return "pending"


class UnknownInstructionError(ValueError):
    """The MockLLM has no scripted plan for this instruction."""
