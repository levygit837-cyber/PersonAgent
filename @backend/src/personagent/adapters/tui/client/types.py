"""Pydantic models for chat API payloads and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequestPayload(BaseModel):
    """Payload sent to /chat/completions/stream."""

    message: str
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = 4096
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    prompt_mode: str = "auto"
    reasoning_level: str = "medium"
    reasoning_budget_tokens: int | None = None
    conversation_id: str | None = None
    system_prompt: str | None = None
    workspace_root: str | None = None
    tools_enabled: bool = True
    max_tool_iterations: int | None = None
    plan_mode_requested: bool = False


class StreamChunk(BaseModel):
    """A single SSE chunk from the chat completion stream."""

    content: str | None = None
    reasoning_content: str | None = None
    is_thinking: bool = False
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    images: list[dict[str, Any]] | None = None
    model: str | None = None
    provider: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    event: str | None = None
    error: str | None = None
