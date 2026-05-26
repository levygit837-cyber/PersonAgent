"""Streaming and timeout helpers for NVIDIA NIM adapter."""

from __future__ import annotations

from typing import Any

import httpx

from personagent.domain.models.inference_result import StreamChunk
from personagent.infrastructure.llm.nvidia_nim_adapter.constants import (
    STREAM_CONNECT_TIMEOUT_SECONDS,
    STREAM_POOL_TIMEOUT_SECONDS,
)
from personagent.infrastructure.llm.openai_compatible_parser import (
    ThinkingTagState,
    accumulate_tool_call_delta,
    extract_reasoning_field,
    split_thinking_tags,
)


async def _response_error_text(response: httpx.Response) -> str:
    try:
        if not response.is_closed:
            await response.aread()
        return response.text
    except Exception:
        return response.reason_phrase


def _stream_timeout_config(
    timeout: float,
    stream_read_timeout: float | None,
) -> httpx.Timeout:
    bounded_timeout = max(float(timeout), 1.0)
    return httpx.Timeout(
        timeout=None,
        connect=min(STREAM_CONNECT_TIMEOUT_SECONDS, bounded_timeout),
        read=stream_read_timeout,
        write=bounded_timeout,
        pool=min(STREAM_POOL_TIMEOUT_SECONDS, bounded_timeout),
    )


def _stream_timeout_label(stream_read_timeout: float | None) -> str:
    if stream_read_timeout is None:
        return "read timeout disabled"
    return f"read timeout {stream_read_timeout}s"


def _normalize_stream_read_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    timeout = float(value)
    return timeout if timeout > 0 else None


def _parse_stream_chunk(
    data: dict[str, Any],
    fallback_model: str,
    provider_key: str,
    tool_call_parts: dict[int, dict[str, Any]] | None = None,
    thinking_state: ThinkingTagState | None = None,
) -> StreamChunk:
    choices = data.get("choices", [])
    if not choices:
        return StreamChunk()

    delta = choices[0].get("delta", {})
    finish_reason = choices[0].get("finish_reason")
    tool_call_parts = tool_call_parts if tool_call_parts is not None else {}

    if delta.get("tool_calls"):
        _accumulate_tool_call_delta(delta["tool_calls"], tool_call_parts)

    raw_content = delta.get("content", "") or ""
    tag_content, tag_reasoning = split_thinking_tags(
        raw_content,
        thinking_state,
        flush=finish_reason is not None,
    )
    content = tag_content
    reasoning = extract_reasoning_field(delta) + tag_reasoning
    tool_calls = (
        _finalize_tool_calls(tool_call_parts)
        if finish_reason == "tool_calls" and tool_call_parts
        else None
    )

    has_signal = bool(content or reasoning or finish_reason or data.get("usage") or tool_calls)
    metadata = {}
    if has_signal:
        metadata = {
            "provider": provider_key,
            "model": data.get("model") or fallback_model,
        }

    return StreamChunk(
        content=content,
        reasoning_content=reasoning,
        finish_reason=finish_reason,
        usage=data.get("usage"),
        tool_calls=tool_calls,
        is_thinking=bool(reasoning and not content),
        metadata=metadata,
    )


def _accumulate_tool_call_delta(
    deltas: list[dict[str, Any]],
    accumulator: dict[int, dict[str, Any]],
) -> None:
    accumulate_tool_call_delta(deltas, accumulator)


def _finalize_tool_calls(
    accumulator: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id") or f"call_{index}",
            "type": item.get("type") or "function",
            "function": item.get("function") or {},
        }
        for index, item in sorted(accumulator.items())
    ]
