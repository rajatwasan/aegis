"""W5: the real provider parses defensively and never needs a key in tests."""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.agent.llm import AnthropicLLM, MockLLM, parse_action, provider_from_env
from aegis.agent.tools import UnknownToolError, validate_action


def transport(reply_text: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["system"]  # the tool contract is sent as the system prompt
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(status, json={"content": [{"type": "text", "text": reply_text}]})

    return httpx.MockTransport(handler)


def llm(reply: str, status: int = 200) -> AnthropicLLM:
    return AnthropicLLM(model="test-model", api_key="test-key", transport=transport(reply, status))


def test_valid_json_action() -> None:
    action = llm('{"tool": "get_balance", "args": {"token": "0x1", "address": "0x2"}}')
    assert action.next_action("balance?", {}) == {
        "tool": "get_balance",
        "args": {"token": "0x1", "address": "0x2"},
    }


def test_json_wrapped_in_prose() -> None:
    reply = 'Sure, here you go:\n{"tool": "done", "args": {}}\nAnything else?'
    assert llm(reply).next_action("x", {}) == {"tool": "done", "args": {}}


@pytest.mark.parametrize(
    "reply",
    ["I would rather not.", "{not json}", '["tool", "done"]', '{"args": {}}'],
)
def test_unreadable_reply_becomes_refused_malformed(reply: str) -> None:
    action = llm(reply).next_action("x", {})
    assert action["tool"] == "malformed"
    with pytest.raises(UnknownToolError, match="malformed model reply"):
        validate_action(action)


def test_http_error_raises_with_status() -> None:
    with pytest.raises(RuntimeError, match="HTTP 529"):
        llm("{}", status=529).next_action("x", {})


def test_model_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AEGIS_LLM_MODEL", "claude-from-env")
    assert AnthropicLLM(api_key="k").model == "claude-from-env"
    monkeypatch.delenv("AEGIS_LLM_MODEL")
    assert AnthropicLLM(api_key="k").model == "claude-sonnet-5-5"


def test_provider_from_env(monkeypatch) -> None:
    monkeypatch.delenv("AEGIS_LLM", raising=False)
    assert isinstance(provider_from_env(), MockLLM)
    monkeypatch.setenv("AEGIS_LLM", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(provider_from_env(), MockLLM)  # no key: scripted, never a silent call
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(provider_from_env(), AnthropicLLM)


def test_parse_action_fills_missing_args() -> None:
    assert parse_action('{"tool": "done"}') == {"tool": "done", "args": {}}
