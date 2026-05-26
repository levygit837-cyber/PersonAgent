"""Codex SSE stream parsing and chunk builders."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from personagent.domain.exceptions import LLMBackendError
from personagent.domain.llm_backend.models import StreamChunk


@dataclass(slots=True)
class _SseEvent:
    event: str | None = None
    data_lines: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.event = None
        self.data_lines.clear()

    @property
    def data(self) -> str:
        return "\n".join(self.data_lines).strip()


class CodexStreamParser:
    """Parses Codex SSE streams into StreamChunk objects."""

    async def iter_response_chunks(
        self,
        response: httpx.Response,
        fallback_model: str,
    ) -> AsyncIterator[StreamChunk]:
        event = _SseEvent()
        async for line in response.aiter_lines():
            if not line:
                chunk = self.parse_sse_event(event.event, event.data, fallback_model)
                event.reset()
                if chunk is not None:
                    yield chunk
                    if chunk.finish_reason == "tool_calls":
                        return
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event.event = line.removeprefix("event:").strip()
                continue
            if line.startswith("data:"):
                event.data_lines.append(line.removeprefix("data:").strip())

        if event.data_lines:
            chunk = self.parse_sse_event(event.event, event.data, fallback_model)
            if chunk is not None:
                yield chunk

    def parse_sse_event(
        self,
        event_type: str | None,
        data_str: str,
        fallback_model: str,
    ) -> StreamChunk | None:
        if not data_str or data_str == "[DONE]":
            return None
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return None

        effective_type = str(data.get("type") or event_type or "")
        metadata = {"provider": "codex", "model": str(data.get("model") or fallback_model)}

        if effective_type in {"response.failed", "response.error", "error"} or data.get("error"):
            raise LLMBackendError(f"Codex stream error: {self._safe_error_detail(data)}")

        if effective_type == "response.output_text.delta":
            text = str(data.get("delta") or "")
            return StreamChunk(content=text, metadata=metadata) if text else None

        if effective_type in {
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        }:
            text = str(data.get("delta") or "")
            return (
                StreamChunk(reasoning_content=text, is_thinking=True, metadata=metadata)
                if text
                else None
            )

        if effective_type == "response.output_item.done":
            item = data.get("item") if isinstance(data.get("item"), dict) else data
            if item.get("type") == "function_call":
                return StreamChunk(
                    finish_reason="tool_calls",
                    tool_calls=[self.tool_call_from_response_item(item)],
                    metadata=metadata,
                )
            return None

        if effective_type == "response.completed":
            response_data = (
                data.get("response") if isinstance(data.get("response"), dict) else data
            )
            usage = self.normalize_usage(response_data.get("usage"))
            model = str(response_data.get("model") or metadata["model"])
            return StreamChunk(
                finish_reason="stop",
                usage=usage,
                metadata={**metadata, "model": model},
            )

        return None

    def tool_call_from_response_item(self, item: dict[str, Any]) -> dict[str, Any]:
        call_id = str(item.get("call_id") or item.get("id") or "")
        name = str(item.get("name") or "")
        arguments = item.get("arguments") or "{}"
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)
        return {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }

    def normalize_usage(self, usage: Any) -> dict[str, Any] | None:
        if not isinstance(usage, dict):
            return None
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        normalized: dict[str, Any] = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
            **usage,
        }
        details = usage.get("output_tokens_details")
        if isinstance(details, dict) and details.get("reasoning_tokens") is not None:
            normalized["reasoning_tokens"] = details.get("reasoning_tokens")
        return normalized

    @staticmethod
    def _safe_error_detail(data: dict[str, Any]) -> str:
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "unknown error")[:300]
        if isinstance(error, str):
            return error[:300]
        return str(data.get("type") or "unknown error")
