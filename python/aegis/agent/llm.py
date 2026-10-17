"""LLM providers behind one tiny interface.

The provider's only job is to pick the next tool action. MockLLM (used by all
tests) replays a script deterministically. AnthropicLLM is optional and only
activates when AEGIS_LLM=anthropic and a key is present; nothing requires it.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

DONE_ACTION: dict[str, Any] = {"tool": "done", "args": {}}


class LLMProvider(Protocol):
    """Chooses the next action given the user instruction and tool context."""

    def next_action(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]: ...


class MockLLM:
    """Deterministic scripted provider.

    In normal mode it replays `script` verbatim, one action per call.
    In gullible mode (M6 evals) it additionally obeys any instruction embedded
    in the input that carries an `AEGIS-INJECT:` marker — modeling a fully
    prompt-injected model — so the layers below can prove they hold anyway.
    """

    INJECT_MARKER = "AEGIS-INJECT:"

    def __init__(self, script: list[dict[str, Any]] | None = None, gullible: bool = False) -> None:
        self.script = list(script or [])
        self.gullible = gullible
        self.calls: list[str] = []

    def next_action(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(instruction)
        if self.gullible and self.INJECT_MARKER in instruction:
            payload = instruction.split(self.INJECT_MARKER, 1)[1].strip()
            try:
                injected = json.loads(payload)
            except json.JSONDecodeError:
                injected = None
            if isinstance(injected, dict) and "tool" in injected:
                return injected
        if self.script:
            return self.script.pop(0)
        return dict(DONE_ACTION)


DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = """You operate token tools behind a deterministic policy engine and a
human approval gate. You cannot move gated assets yourself; you only propose.
Reply with exactly one JSON object and nothing else:
{"tool": "<propose_transfer|propose_mint|check_compliance|get_balance|done>", "args": {...}}
propose_transfer args: token, from, to, amount (integer base units), asset_class (default 0).
propose_mint args: token, to, amount, asset_class.
check_compliance args: address. get_balance args: token, address.
Use done when there is nothing to do."""


def parse_action(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply.

    A reply with no parseable object, or one without a string ``tool``, becomes
    ``{"tool": "malformed", ...}``, which the typed registry refuses. An
    unreadable reply is never mapped to a default action (AGENTS.md R11).
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return {"tool": "malformed", "args": {"reason": "no JSON object in model reply"}}
    try:
        action = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return {"tool": "malformed", "args": {"reason": f"model reply is not JSON: {exc.msg}"}}
    if not isinstance(action, dict) or not isinstance(action.get("tool"), str):
        return {"tool": "malformed", "args": {"reason": "model reply has no tool name"}}
    action.setdefault("args", {})
    return action


class AnthropicLLM:
    """Real-model provider over the Messages API. Never used by tests or the demo.

    Active only when AEGIS_LLM=anthropic and ANTHROPIC_API_KEY is set. The
    model comes from AEGIS_LLM_MODEL. HTTP errors raise with the status; a
    reply that is not one action becomes a refused ``malformed`` action.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        transport: Any | None = None,
    ) -> None:
        self.model = model or os.environ.get("AEGIS_LLM_MODEL", "").strip() or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("AnthropicLLM requires ANTHROPIC_API_KEY")
        self._transport = transport  # httpx transport override, for tests

    def next_action(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]:
        import httpx

        with httpx.Client(transport=self._transport, timeout=60) as client:
            response = client.post(
                self.API_URL,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": self.model,
                    "max_tokens": 512,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Context: {json.dumps(context)}\nInstruction: {instruction}"
                            ),
                        }
                    ],
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"model request failed: HTTP {response.status_code}")
        blocks = response.json().get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return parse_action(text)


def provider_from_env() -> LLMProvider:
    """MockLLM unless AEGIS_LLM=anthropic with a key present."""
    if os.environ.get("AEGIS_LLM") == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return MockLLM()
