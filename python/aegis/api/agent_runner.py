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
from aegis.agent.llm import AnthropicLLM, provider_from_env
from aegis.anchoring import StateError
from aegis.api.config import ApiConfig, load_chain_state
from aegis.events import EventBus


def _transfer(token: str, operator: str, to: str, amount: int) -> dict[str, Any]:
    return {
        "tool": "propose_transfer",
        "args": {"token": token, "from": operator, "to": to, "amount": amount},
    }


def canned_plans(
    token: str, operator: str, parties: dict[str, list[str]]
) -> dict[str, dict[str, Any]]:
    """The scripted demo plans, keyed by normalized instruction.

    Destinations come from ``state.json["parties"]``, the world the deployer
    actually seeded, not from addresses spelled here. A state file without
    parties cannot run the demo plans and says so (AGENTS.md R11).
    """
    compliant = list(parties.get("compliant") or [])
    frozen = list(parties.get("frozen") or [])
    if len(compliant) < 3 or not frozen:
        raise StateError(
            "state.json has no seeded parties (need 3 compliant, 1 frozen) for the"
            " scripted demo plans; redeploy with make dev or set AEGIS_LLM=anthropic"
        )
    a, b, c = compliant[:3]
    return {
        "pay the vendor invoice batch": {
            "description": "Three small compliant transfers that auto-execute under policy",
            "plan": [
                {"tool": "check_compliance", "args": {"address": a}},
                _transfer(token, operator, a, 1_200),
                _transfer(token, operator, b, 2_500),
                _transfer(token, operator, c, 3_400),
            ],
        },
        "send 50,000 agd to the treasury desk": {
            "description": "A large transfer that escalates to a human guardian",
            "plan": [
                {"tool": "check_compliance", "args": {"address": a}},
                _transfer(token, operator, a, 50_000),
            ],
        },
        "refund 10 agd to the frozen counterparty": {
            "description": "A transfer to a frozen address the policy denies outright",
            "plan": [_transfer(token, operator, frozen[0], 10)],
        },
    }


_PLACEHOLDER_PARTIES = {"compliant": ["0x0", "0x0", "0x0"], "frozen": ["0x0"]}


def canned_instructions() -> list[dict[str, str]]:
    """Instruction chips for the console (plan bodies need live addresses)."""
    placeholder = canned_plans(token="0x0", operator="0x0", parties=_PLACEHOLDER_PARTIES)
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
        if self.config.operator_key is None:
            raise StateError("no operator key configured; set AEGIS_OPERATOR_KEY")
        chain = ChainClient(state["rpc_url"], self.config.operator_key)
        check_operator_matches(chain, state)
        token = chain.at("GuardedToken", state["token_address"])
        check_guardian_matches(token, self.app.state.signer.address)
        self._runtime = AegisRuntime(
            policy=self.app.state.policy,
            audit=self.app.state.audit,  # the emitting log: decisions hit the bus
            chain=chain,
            token=token,
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
        """Validate the instruction, then run the agent in a worker thread.

        With AEGIS_LLM=anthropic the configured model reads the instruction and
        proposes one action through the same gate. Otherwise the scripted
        MockLLM runs a canned plan, and anything else is a 400 naming the set.
        """
        runtime, state = self._ensure_runtime()
        provider = provider_from_env()
        if isinstance(provider, MockLLM):
            plans = canned_plans(
                state["token_address"], runtime.chain.operator_address, state.get("parties") or {}
            )
            entry = plans.get(_normalize(instruction))
            if entry is None:
                known = ", ".join(f"'{_title(k)}'" for k in plans)
                raise UnknownInstructionError(
                    f"the scripted demo provider only runs the canned instructions: {known};"
                    " set AEGIS_LLM=anthropic to run any instruction through a model"
                )
            plan = list(entry["plan"])
            llm: Any = MockLLM(script=plan)
            instructions = [f"{instruction} [step {i + 1}]" for i in range(len(plan))]
        else:
            llm = provider
            # one model action per run: the gate, not the model, decides what moves
            instructions = [
                f"{instruction}\n(token: {state['token_address']},"
                f" operator: {runtime.chain.operator_address})"
            ]

        run = AgentRun(run_id=str(uuid.uuid4()), instruction=instruction)
        self.runs[run.run_id] = run
        run.thread = threading.Thread(
            target=self._run, args=(run, runtime, llm, instructions), daemon=True
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

    def _run(self, run: AgentRun, runtime: AegisRuntime, llm: Any, instructions: list[str]) -> None:
        with self._lock:
            try:
                self._drive(run, runtime, llm, instructions)
                run.status = "finished"
            except Exception as exc:  # noqa: BLE001 - surfaced as an event
                run.status = "failed"
                run.error = str(exc)
                self._step(run, "failed", error=str(exc))
                return
            self._step(run, "finished", results=run.results)

    def _drive(
        self, run: AgentRun, runtime: AegisRuntime, llm: Any, instructions: list[str]
    ) -> None:
        graph = build_graph(llm, runtime)
        graph_config = {"configurable": {"thread_id": run.run_id}}
        self._step(run, "started", steps_planned=len(instructions))

        payload: Any = {"instructions": list(instructions), "results": []}
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


def check_operator_matches(chain: ChainClient, state: dict[str, Any]) -> None:
    """Refuse an operator key that is not the operator state.json records.

    The recorded operator owns the registry, holds the supply and has
    ANCHOR_ROLE; a different key would fail every write with an opaque revert.
    """
    recorded = state.get("operator_address")
    if recorded and recorded.lower() != chain.operator_address.lower():
        raise StateError(
            f"operator key mismatch: AEGIS_OPERATOR_KEY derives {chain.operator_address} but"
            f" state.json records operator {recorded}"
        )


def check_guardian_matches(token: Any, signer_address: str) -> None:
    """Refuse to serve a token whose on-chain guardian is not our signer.

    A mismatch means every approval this service signs will revert on chain
    with ``InvalidGuardianSignature``; better to fail at startup, naming both
    addresses, than to hand out signatures that cannot execute (AGENTS.md R5).
    """
    try:
        onchain = token.functions.guardian().call()
    except Exception as exc:  # noqa: BLE001 - any RPC failure: refuse, naming the cause
        raise StateError(f"cannot read the guardian of token {token.address}: {exc}") from exc
    if onchain.lower() != signer_address.lower():
        raise StateError(
            f"guardian key mismatch: the configured signer {signer_address} is not the"
            f" guardian of token {token.address} (on-chain guardian is {onchain});"
            " set AEGIS_GUARDIAN_KEY to the key that deployed this token, or redeploy"
        )


def provider_info() -> dict[str, str | None]:
    """What the console should say runs the agent: the scripted demo or a model."""
    provider = provider_from_env()
    if isinstance(provider, AnthropicLLM):
        return {"provider": "anthropic", "model": provider.model}
    return {"provider": "mock", "model": None}
