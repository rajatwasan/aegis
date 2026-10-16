"""LLM providers behind one tiny interface.

The provider's only job is to pick the next tool action. MockLLM (used by all
tests) replays a script deterministically. AnthropicLLM is the real model and
is selected only when ``AEGIS_LLM=anthropic``; it then requires a key and a
model id, with no silent default for either (AGENTS.md C3, C9; spec W3, D4).
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import httpx

from aegis.errors import AegisError, ConfigError

DONE_ACTION: dict[str, Any] = {"tool": "done", "args": {}}

MOCK_MODE = "mock"
ANTHROPIC_MODE = "anthropic"
MODES = (MOCK_MODE, ANTHROPIC_MODE)


class ProviderError(AegisError):
    """The model did not produce a usable action. The run fails; nothing is guessed."""


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


_SYSTEM_PROMPT = """You operate token tools behind a deterministic policy engine and a human
approval gate. You never move value yourself: you propose one action at a
time and the policy decides. Reply with exactly one JSON object and nothing
else, no prose, no code fence:

  {"tool": "<name>", "args": {...}}

Tools:
  propose_transfer  args: token, from, to, amount   (amount in base units)
  propose_mint      args: token, to, amount
  check_compliance  args: address
  get_balance       args: address
  done              args: {}                       (when the instruction is complete)

Use the operator address as "from" for transfers. Use the token address given
in the context. When the instruction is satisfied, or cannot be satisfied with
these tools, reply with the done action."""


class AnthropicLLM:
    """Real model provider over the Anthropic Messages API.

    Selected only by ``provider_from_env`` when ``AEGIS_LLM=anthropic``. The
    reply must be one JSON action object; a malformed reply is retried once
    with the parse error quoted back, and a second failure raises
    :class:`ProviderError` so the run fails instead of guessing (C1).
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        max_tokens: int = 512,
        timeout: float = 60.0,
    ) -> None:
        if not model:
            raise ConfigError("AnthropicLLM requires a model id (AEGIS_ANTHROPIC_MODEL)")
        if not api_key:
            raise ConfigError("AnthropicLLM requires ANTHROPIC_API_KEY")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
        self.calls = 0

    def next_action(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {
                "role": "user",
                "content": (
                    f"Context: {json.dumps(context, default=str)}\n"
                    f"Instruction: {instruction}\n"
                    "Reply with the next action as one JSON object."
                ),
            }
        ]
        last_error = ""
        for attempt in range(2):
            if attempt == 1:
                retry = (
                    f"Your previous reply was not a single JSON action object ({last_error}). "
                    "Reply with exactly one JSON object of the form "
                    '{"tool": ..., "args": {...}}.'
                )
                messages.append({"role": "user", "content": retry})
            text = self._complete(messages)
            try:
                return _parse_action(text)
            except ValueError as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": text})
        raise ProviderError(f"model returned no usable action after a retry: {last_error}")

    def _complete(self, messages: list[dict[str, Any]]) -> str:
        self.calls += 1
        try:
            response = self._client.post(
                self.API_URL,
                headers={"x-api-key": self.api_key, "anthropic-version": self.API_VERSION},
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": _SYSTEM_PROMPT,
                    "messages": messages,
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"model request failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"model request failed: HTTP {response.status_code}")
        try:
            blocks = response.json()["content"]
            texts = [b["text"] for b in blocks if b.get("type") == "text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"model reply had no content: {exc}") from exc
        if not texts:
            raise ProviderError("model reply had no text block")
        return "\n".join(texts)


def _parse_action(text: str) -> dict[str, Any]:
    """Exactly one JSON object with a ``tool`` string and an ``args`` object."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    try:
        action = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc.msg}") from exc
    if not isinstance(action, dict) or not isinstance(action.get("tool"), str):
        raise ValueError("JSON is not an object with a string 'tool'")
    args = action.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("'args' is not an object")
    return {"tool": action["tool"], "args": args}


def llm_mode(environ: dict[str, str] | None = None) -> str:
    """``mock`` unless ``AEGIS_LLM`` names another supported provider."""
    env = os.environ if environ is None else environ
    mode = env.get("AEGIS_LLM", MOCK_MODE).strip().lower() or MOCK_MODE
    if mode not in MODES:
        raise ConfigError(f"AEGIS_LLM={mode!r} is not supported; use one of {', '.join(MODES)}")
    return mode


def provider_from_env(
    environ: dict[str, str] | None = None, *, client: httpx.Client | None = None
) -> LLMProvider:
    """MockLLM by default; AnthropicLLM when ``AEGIS_LLM=anthropic``.

    Anthropic mode requires ``ANTHROPIC_API_KEY`` and ``AEGIS_ANTHROPIC_MODEL``
    and raises :class:`ConfigError` without them: no half configured provider
    silently turns into the mock (C9).
    """
    env = os.environ if environ is None else environ
    mode = llm_mode(env)
    if mode == MOCK_MODE:
        return MockLLM()
    model = env.get("AEGIS_ANTHROPIC_MODEL", "").strip()
    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not model or not api_key:
        missing = [
            name
            for name, value in (("AEGIS_ANTHROPIC_MODEL", model), ("ANTHROPIC_API_KEY", api_key))
            if not value
        ]
        raise ConfigError(f"AEGIS_LLM=anthropic requires {' and '.join(missing)}")
    return AnthropicLLM(model, api_key, client=client)
