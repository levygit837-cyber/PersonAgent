import base64
import json

import httpx
import pytest

from personagent.infrastructure.llm.codex_subscription_adapter import (
    CodexAuthStore,
    CodexSubscriptionAdapter,
)


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    return f"header.{payload.rstrip('=')}.signature"


def test_codex_auth_store_reads_chatgpt_tokens_without_public_token(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "last_refresh": "2026-04-27T12:00:00Z",
                "tokens": {
                    "access_token": "secret-access-token",
                    "account_id": "acct_123",
                    "id_token": _jwt(
                        {
                            "email": "user@example.com",
                            "chatgpt_plan_type": "plus",
                        }
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = CodexAuthStore(tmp_path).read_status()
    public = snapshot.public_dict()

    assert snapshot.authenticated is True
    assert snapshot.access_token == "secret-access-token"
    assert public["email"] == "user@example.com"
    assert public["plan_type"] == "plus"
    assert "access_token" not in public


def test_codex_model_cache_normalization_filters_api_support_and_keeps_core_models(tmp_path):
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "client_version": "0.124.0",
                "models": [
                    {
                        "slug": "unsupported-model",
                        "display_name": "Unsupported",
                        "supported_in_api": False,
                    },
                    {
                        "slug": "gpt-5.5",
                        "display_name": "GPT-5.5",
                        "context_window": 272000,
                        "supported_in_api": True,
                        "supported_reasoning_levels": ["low", "medium", "high", "xhigh"],
                        "supports_parallel_tool_calls": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    adapter = CodexSubscriptionAdapter(codex_home=str(tmp_path))
    catalog = adapter._read_local_models_cache(ignore_ttl=True)

    assert catalog is not None
    ids = [model["id"] for model in catalog["data"]]
    assert "unsupported-model" not in ids
    assert "gpt-5.5" in ids
    assert "gpt-5.4-mini" in ids
    assert catalog["data"][0]["provider"] == "codex"


def test_codex_payload_uses_responses_shape_tools_and_xhigh_for_max():
    adapter = CodexSubscriptionAdapter()

    payload = adapter._build_payload(
        [
            {"role": "system", "content": "You are PersonAgent."},
            {"role": "user", "content": "Inspect README."},
            {
                "role": "assistant",
                "content": "I will read it.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "README content"},
        ],
        max_tokens=-1,
        extra={"model": "gpt-5.5", "reasoning_level": "max"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                    "strict": True,
                },
            }
        ],
        tool_choice="auto",
        stream=True,
    )

    assert payload["model"] == "gpt-5.5"
    assert payload["instructions"] == "You are PersonAgent."
    assert payload["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "strict": False,
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True
    assert payload["input"][0] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "Inspect README."}],
    }
    assert payload["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "README content",
    }


def test_codex_sse_parser_splits_reasoning_content_and_tool_calls():
    adapter = CodexSubscriptionAdapter()

    content = adapter._parse_sse_event(
        "response.output_text.delta",
        json.dumps({"delta": "visible"}),
        "gpt-5.5",
    )
    reasoning = adapter._parse_sse_event(
        "response.reasoning_summary_text.delta",
        json.dumps({"delta": "thinking"}),
        "gpt-5.5",
    )
    tool = adapter._parse_sse_event(
        "response.output_item.done",
        json.dumps(
            {
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                }
            }
        ),
        "gpt-5.5",
    )
    completed = adapter._parse_sse_event(
        "response.completed",
        json.dumps(
            {
                "response": {
                    "model": "gpt-5.5",
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": 5,
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                }
            }
        ),
        "gpt-5.5",
    )

    assert content is not None and content.content == "visible"
    assert reasoning is not None and reasoning.reasoning_content == "thinking"
    assert reasoning.is_thinking is True
    assert tool is not None and tool.finish_reason == "tool_calls"
    assert tool.tool_calls is not None
    assert tool.tool_calls[0]["id"] == "call_1"
    assert completed is not None and completed.finish_reason == "stop"
    assert completed.usage is not None
    assert completed.usage["reasoning_tokens"] == 2


@pytest.mark.asyncio
async def test_codex_stream_retries_once_after_401(monkeypatch):
    adapter = CodexSubscriptionAdapter()
    calls = 0
    refreshes = 0

    async def fake_stream(_payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("401", request=request, response=response)
        yield adapter._parse_sse_event(
            "response.output_text.delta",
            json.dumps({"delta": "ok"}),
            "gpt-5.5",
        )

    async def fake_refresh():
        nonlocal refreshes
        refreshes += 1
        return True

    monkeypatch.setattr(adapter, "_stream_payload", fake_stream)
    monkeypatch.setattr(adapter.auth_store, "refresh_via_cli", fake_refresh)

    chunks = [chunk async for chunk in adapter._stream_payload_with_refresh({"model": "gpt-5.5"})]

    assert calls == 2
    assert refreshes == 1
    assert chunks[0].content == "ok"


def test_codex_http_error_message_redacts_response_body():
    adapter = CodexSubscriptionAdapter()
    request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
    response = httpx.Response(
        500,
        request=request,
        content=b"secret-access-token should not be exposed",
    )
    exc = httpx.HTTPStatusError("500", request=request, response=response)

    message = adapter._http_error_message(exc, "Codex")

    assert "secret-access-token" not in message
    assert message == "Codex HTTP 500: Internal Server Error"
