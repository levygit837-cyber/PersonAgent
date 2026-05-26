from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.adapters.api.errors import install_error_handlers
from personagent.application.retry import RetryPolicy
from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    ErrorCategory,
    ProviderRateLimitError,
    provider_http_error,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolUseContext


def test_personagent_error_serializes_stable_envelope() -> None:
    error = ConversationNotFoundError("Conversation not found", metadata={"id": "abc"})

    envelope = error.to_envelope()

    assert envelope["code"] == "conversation.not_found"
    assert envelope["category"] == ErrorCategory.CONVERSATION.value
    assert envelope["status"] == 404
    assert envelope["retryable"] is False
    assert envelope["metadata"] == {"id": "abc"}
    assert envelope["correlation_id"]


def test_provider_http_error_classifies_rate_limit() -> None:
    error = provider_http_error(
        provider="NVIDIA NIM",
        status_code=429,
        detail="rate limit exceeded",
        retry_after="2",
    )

    assert isinstance(error, ProviderRateLimitError)
    assert error.retryable is True
    assert error.to_envelope()["metadata"]["retry_after"] == "2"
    assert error.safe_for_model is False


def test_provider_http_error_redacts_sensitive_detail() -> None:
    error = provider_http_error(
        provider="NVIDIA NIM",
        status_code=500,
        detail="upstream echoed Authorization: Bearer nvapi-abcdefghijklmnopqrstuvwxyz123456",
    )

    assert "nvapi-" not in str(error)
    assert "[redacted]" in str(error)
    assert error.safe_for_model is False


def test_retry_policy_blocks_stream_replay_after_output() -> None:
    policy = RetryPolicy(max_attempts=3, jitter_seconds=0)
    error = provider_http_error(
        provider="NVIDIA NIM",
        status_code=503,
        detail="overloaded",
    )

    assert policy.should_retry(error, attempt=1, foreground=True, emitted_output=False)
    assert not policy.should_retry(error, attempt=1, foreground=True, emitted_output=True)
    assert not policy.should_retry(error, attempt=1, foreground=True, idempotent=False)


@pytest.mark.asyncio
async def test_api_error_handler_preserves_detail_and_adds_envelope() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/conversation")
    async def conversation() -> None:
        raise ConversationNotFoundError("Conversation not found")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/conversation")

    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"] == "Conversation not found"
    assert payload["error"]["code"] == "conversation.not_found"
    assert payload["error"]["category"] == "conversation"


@pytest.mark.asyncio
async def test_tool_orchestrator_unknown_tool_returns_structured_error(tmp_path: Path) -> None:
    orchestrator = ToolOrchestrator(
        ToolRegistry([]),
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )
    call = ToolCall(id="call_missing", name="MissingTool", arguments={})
    context = ToolUseContext(
        conversation_id="conv",
        workspace_root=tmp_path,
        cwd=tmp_path,
        allowed_roots=(tmp_path,),
    )

    events = [event async for event in orchestrator.execute([call], context)]

    result = events[-1].result
    assert result is not None
    assert result.status == ToolExecutionStatus.ERROR
    assert result.metadata["error"]["code"] == "tool.not_found"
    assert result.metadata["error"]["category"] == "tool"


def test_tool_runtime_config_defaults_to_unlimited_iterations(tmp_path: Path) -> None:
    default_config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    unbounded_config = ToolRuntimeConfig.from_values(
        workspace_root=tmp_path,
        max_tool_iterations=None,
    )
    explicit_config = ToolRuntimeConfig.from_values(
        workspace_root=tmp_path,
        max_tool_iterations=10_000,
    )

    assert default_config.max_tool_iterations is None
    assert unbounded_config.max_tool_iterations is None
    assert explicit_config.max_tool_iterations == 10_000
    assert default_config.result_max_chars is None
