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


class AnthropicLLM:
    """Real-model provider. Never used by tests or the demo.

    Active only when AEGIS_LLM=anthropic and ANTHROPIC_API_KEY is set; calls
    the Messages API over httpx and expects the model to reply with one JSON
    action object.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("AnthropicLLM requires ANTHROPIC_API_KEY")

    def next_action(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]:
        import httpx

        prompt = (
            "You operate token tools behind a policy engine. Reply with exactly one"
            ' JSON object {"tool": <propose_transfer|propose_mint|check_compliance|'
            'get_balance|done>, "args": {...}}.\n'
            f"Available context: {json.dumps(context)}\nInstruction: {instruction}"
        )
        response = httpx.post(
            self.API_URL,
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.model,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        text = response.json()["content"][0]["text"]
        return json.loads(text)


def provider_from_env() -> LLMProvider:
    """MockLLM unless AEGIS_LLM=anthropic with a key present."""
    if os.environ.get("AEGIS_LLM") == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return MockLLM()
