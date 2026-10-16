"""W3 tests: provider selection and the real model adapter, offline (AGENTS.md T4).

The Anthropic adapter is exercised against an ``httpx.MockTransport`` that
plays the Messages API: scripted replies, malformed replies, HTTP failures.
No network, no key.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.agent.llm import (
    AnthropicLLM,
    MockLLM,
    ProviderError,
    llm_mode,
    provider_from_env,
)
from aegis.errors import ConfigError


def messages_api(replies: list[str | int], seen: list[dict] | None = None) -> httpx.Client:
    """A fake Messages API: each entry is a text reply, or an int HTTP status."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append({"headers": dict(request.headers), "body": body})
        reply = queue.pop(0) if queue else '{"tool": "done", "args": {}}'
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": "nope"})
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": reply}], "stop_reason": "end_turn"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestProviderSelection:
    def test_mock_is_the_default(self) -> None:
        assert llm_mode({}) == "mock"
        assert isinstance(provider_from_env({}), MockLLM)
        assert isinstance(provider_from_env({"AEGIS_LLM": "mock"}), MockLLM)

    def test_unknown_mode_is_a_config_error(self) -> None:
        with pytest.raises(ConfigError, match="not supported"):
            llm_mode({"AEGIS_LLM": "gpt"})

    def test_anthropic_llm_requires_model_and_key(self) -> None:
        with pytest.raises(ConfigError, match="AEGIS_ANTHROPIC_MODEL and ANTHROPIC_API_KEY"):
            provider_from_env({"AEGIS_LLM": "anthropic"})
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            provider_from_env({"AEGIS_LLM": "anthropic", "AEGIS_ANTHROPIC_MODEL": "m"})
        with pytest.raises(ConfigError, match="AEGIS_ANTHROPIC_MODEL"):
            provider_from_env({"AEGIS_LLM": "anthropic", "ANTHROPIC_API_KEY": "k"})
        provider = provider_from_env(
            {"AEGIS_LLM": "anthropic", "AEGIS_ANTHROPIC_MODEL": "m", "ANTHROPIC_API_KEY": "k"},
            client=messages_api([]),
        )
        assert isinstance(provider, AnthropicLLM)
        assert provider.model == "m"


class TestAnthropicLLM:
    def test_returns_the_models_action_and_sends_context(self) -> None:
        seen: list[dict] = []
        reply = json.dumps(
            {
                "tool": "propose_transfer",
                "args": {"token": "0xT", "from": "0xA", "to": "0xB", "amount": 5},
            }
        )
        llm = AnthropicLLM("test-model", "test-key", client=messages_api([reply], seen))
        action = llm.next_action("pay bob 5", {"operator": "0xA", "token": "0xT", "results": []})
        assert action == {
            "tool": "propose_transfer",
            "args": {"token": "0xT", "from": "0xA", "to": "0xB", "amount": 5},
        }
        assert llm.calls == 1
        request = seen[0]
        assert request["headers"]["x-api-key"] == "test-key"
        assert request["body"]["model"] == "test-model"
        assert "pay bob 5" in request["body"]["messages"][0]["content"]
        assert '"operator": "0xA"' in request["body"]["messages"][0]["content"]
        assert "propose_transfer" in request["body"]["system"]

    def test_accepts_a_fenced_json_reply(self) -> None:
        llm = AnthropicLLM("m", "k", client=messages_api(['```json\n{"tool": "done"}\n```']))
        assert llm.next_action("x", {}) == {"tool": "done", "args": {}}

    def test_retries_once_on_malformed_output(self) -> None:
        seen: list[dict] = []
        llm = AnthropicLLM(
            "m", "k", client=messages_api(["sure, transferring now", '{"tool": "done"}'], seen)
        )
        assert llm.next_action("x", {}) == {"tool": "done", "args": {}}
        assert llm.calls == 2
        retry_messages = seen[1]["body"]["messages"]
        assert retry_messages[-2]["role"] == "assistant"  # the bad reply is quoted back
        assert "not a single JSON action object" in retry_messages[-1]["content"]

    def test_anthropic_llm_rejects_malformed_json_after_retry(self) -> None:
        llm = AnthropicLLM("m", "k", client=messages_api(["nope", '{"tool": 7}']))
        with pytest.raises(ProviderError, match="no usable action after a retry"):
            llm.next_action("x", {})
        assert llm.calls == 2

    def test_http_failure_is_a_provider_error_not_a_guess(self) -> None:
        llm = AnthropicLLM("m", "k", client=messages_api([500]))
        with pytest.raises(ProviderError, match="HTTP 500"):
            llm.next_action("x", {})

    def test_reply_without_text_block_is_a_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t"}]})

        llm = AnthropicLLM("m", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(ProviderError, match="no text block"):
            llm.next_action("x", {})

    def test_constructor_refuses_missing_model_or_key(self) -> None:
        with pytest.raises(ConfigError):
            AnthropicLLM("", "k", client=messages_api([]))
        with pytest.raises(ConfigError):
            AnthropicLLM("m", "", client=messages_api([]))
