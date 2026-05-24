"""Vertex AI streaming response parser — SSE parsing, delta accumulation, tool call assembly."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from personagent.domain.models.inference_result import GeneratedImage, InferenceResult, StreamChunk
from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STREAM_POOL_TIMEOUT_SECONDS,
)


class VertexStreamingHandler:
    """Parses Vertex AI streaming and non-streaming responses into PersonAgent models."""

    def __init__(
        self,
        *,
        timeout: float,
        stream_read_timeout: float | None,
        auth_mode: str,
    ) -> None:
        self._timeout = timeout
        self._stream_read_timeout = self._normalize_stream_read_timeout(stream_read_timeout)
        self._auth_mode = auth_mode

    # -- public entry points ------------------------------------------------

    def parse_inference_result(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> InferenceResult:
        parsed = self._parse_candidate_data(data, fallback_model)
        return InferenceResult(
            content=parsed["content"],
            reasoning_content=parsed["reasoning"],
            finish_reason=parsed["finish_reason"],
            usage=parsed["usage"],
            model=parsed["model"],
            tool_calls=parsed["tool_calls"] or None,
            images=parsed["images"],
            metadata=self.metadata(parsed["model"], parsed["thought_signatures"]),
        )

    def stream_chunks_from_data(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> tuple[list[StreamChunk], list[str]]:
        candidate = _first_candidate(data)
        if not candidate:
            return [], []

        model = str(data.get("modelVersion") or data.get("model") or fallback_model)
        metadata = self.metadata(model)
        chunks: list[StreamChunk] = []
        thought_signatures: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        content = candidate.get("content") or {}
        raw_parts = self._normalized_content_parts(content)
        for index, part in enumerate(content.get("parts") or []):
            signature = _part_thought_signature(part)
            if signature:
                thought_signatures.append(signature)

            if part.get("functionCall"):
                tool_calls.append(self._tool_call_from_part(part, index))
                continue

            image = self._image_from_part(part)
            if image:
                chunks.append(StreamChunk(images=[image], metadata=metadata))
                continue

            text = _part_text(part)
            if not text:
                continue
            if _part_is_thought(part):
                chunks.append(
                    StreamChunk(
                        reasoning_content=text,
                        is_thinking=True,
                        metadata=self.metadata(model, [signature] if signature else None),
                    )
                )
            else:
                chunks.append(StreamChunk(content=text, metadata=metadata))

        finish_reason = self._finish_reason(candidate.get("finishReason"), bool(tool_calls))
        self._attach_content_parts(tool_calls, raw_parts)
        if tool_calls or finish_reason:
            chunks.append(
                StreamChunk(
                    finish_reason=finish_reason,
                    tool_calls=tool_calls or None,
                    usage=_usage_metadata(data),
                    metadata=self.metadata(model, thought_signatures),
                )
            )

        return chunks, thought_signatures

    async def stream_events(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[dict[str, Any] | str]:
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            async for data in self._json_stream_objects(response):
                yield data
            return

        async for line in response.aiter_lines():
            data_str = self._stream_data_from_line(line)
            if not data_str:
                continue
            if data_str == "[DONE]":
                yield data_str
                return
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data

    def stream_timeout_config(self) -> httpx.Timeout:
        bounded_timeout = max(float(self._timeout), 1.0)
        return httpx.Timeout(
            timeout=None,
            connect=min(DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS, bounded_timeout),
            read=self._stream_read_timeout,
            write=bounded_timeout,
            pool=min(DEFAULT_STREAM_POOL_TIMEOUT_SECONDS, bounded_timeout),
        )

    def stream_timeout_label(self) -> str:
        if self._stream_read_timeout is None:
            return "read timeout disabled"
        return f"read timeout {self._stream_read_timeout}s"

    def metadata(
        self,
        model: str,
        thought_signatures: list[str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": "vertex",
            "model": model,
            "vertex_auth_mode": self._auth_mode,
        }
        if thought_signatures:
            metadata["vertex_thought_signatures"] = [
                signature for signature in thought_signatures if signature
            ]
        return metadata

    # -- private helpers ----------------------------------------------------

    def _parse_candidate_data(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> dict[str, Any]:
        candidate = _first_candidate(data) or {}
        model = str(data.get("modelVersion") or data.get("model") or fallback_model)
        content = candidate.get("content") or {}
        raw_parts = self._normalized_content_parts(content)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        thought_signatures: list[str] = []
        images: list[GeneratedImage] = []
        tool_calls: list[dict[str, Any]] = []

        for index, part in enumerate(content.get("parts") or []):
            signature = _part_thought_signature(part)
            if signature:
                thought_signatures.append(signature)
            if part.get("functionCall"):
                tool_calls.append(self._tool_call_from_part(part, index))
                continue
            image = self._image_from_part(part)
            if image:
                images.append(image)
                continue
            text = _part_text(part)
            if not text:
                continue
            if _part_is_thought(part):
                reasoning_parts.append(text)
            else:
                content_parts.append(text)

        self._attach_content_parts(tool_calls, raw_parts)
        return {
            "content": "".join(content_parts),
            "reasoning": "".join(reasoning_parts),
            "images": images,
            "tool_calls": tool_calls,
            "thought_signatures": thought_signatures,
            "finish_reason": self._finish_reason(candidate.get("finishReason"), bool(tool_calls)),
            "usage": _usage_metadata(data),
            "model": model,
        }

    def _attach_content_parts(
        self,
        tool_calls: list[dict[str, Any]],
        parts: list[dict[str, Any]],
    ) -> None:
        if not tool_calls or not parts:
            return
        extra = tool_calls[0].get("extra_content")
        next_extra = dict(extra) if isinstance(extra, dict) else {}
        google = next_extra.get("google")
        next_google = dict(google) if isinstance(google, dict) else {}
        if not next_google.get("thought_signature"):
            signature = next(
                (signature for part in parts if (signature := _part_thought_signature(part))),
                "",
            )
            if signature:
                next_google["thought_signature"] = signature
        next_google["content_parts"] = parts
        next_extra["google"] = next_google
        tool_calls[0]["extra_content"] = next_extra

    def _normalized_content_parts(self, content: dict[str, Any]) -> list[dict[str, Any]]:
        parts = content.get("parts") or []
        return [part for part in parts if isinstance(part, dict)]

    def _tool_call_from_part(self, part: dict[str, Any], index: int) -> dict[str, Any]:
        function_call = part.get("functionCall") or {}
        name = str(function_call.get("name") or "")
        args = function_call.get("args")
        call: dict[str, Any] = {
            "id": f"vertex-call-{index}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args or {}, ensure_ascii=False),
            },
        }
        signature = _part_thought_signature(part)
        if signature:
            call["extra_content"] = {"google": {"thought_signature": signature}}
        return call

    def _image_from_part(self, part: dict[str, Any]) -> GeneratedImage | None:
        inline_data = part.get("inlineData") or part.get("inline_data")
        if not isinstance(inline_data, dict):
            return None
        data = inline_data.get("data")
        if not isinstance(data, str) or not data:
            return None
        mime_type = inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png"
        return GeneratedImage(mime_type=str(mime_type), data=data, alt="Generated image")

    def _finish_reason(self, raw: Any, has_tool_calls: bool) -> str | None:
        if has_tool_calls:
            return "tool_calls"
        if raw is None:
            return None
        normalized = str(raw).strip().upper()
        if normalized in {"", "FINISH_REASON_UNSPECIFIED"}:
            return None
        return {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "BLOCKLIST": "content_filter",
            "PROHIBITED_CONTENT": "content_filter",
            "SPII": "content_filter",
        }.get(normalized, normalized.lower())

    def _normalize_stream_read_timeout(self, value: float | None) -> float | None:
        if value is None:
            return None
        timeout = float(value)
        return timeout if timeout > 0 else None

    def _stream_data_from_line(self, line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        if stripped.startswith("data: "):
            return stripped[6:]
        if stripped.startswith("{"):
            return stripped
        return ""

    async def _json_stream_objects(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[dict[str, Any]]:
        decoder = json.JSONDecoder()
        buffer = ""
        async for text in response.aiter_text():
            buffer += text
            while True:
                buffer = buffer.lstrip()
                if not buffer:
                    break
                if buffer[0] in "[,":
                    buffer = buffer[1:]
                    continue
                if buffer[0] == "]":
                    return
                try:
                    item, index = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                buffer = buffer[index:]
                if isinstance(item, dict):
                    yield item
                elif isinstance(item, list):
                    for nested in item:
                        if isinstance(nested, dict):
                            yield nested


def _first_candidate(data: dict[str, Any]) -> dict[str, Any] | None:
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    candidate = candidates[0]
    return candidate if isinstance(candidate, dict) else None


def _usage_metadata(data: dict[str, Any]) -> dict[str, int] | None:
    usage = data.get("usageMetadata") or data.get("usage_metadata")
    return usage if isinstance(usage, dict) else None


def _part_text(part: dict[str, Any]) -> str:
    value = part.get("text")
    return value if isinstance(value, str) else ""


def _part_thought_signature(part: dict[str, Any]) -> str:
    value = part.get("thoughtSignature") or part.get("thought_signature")
    return value if isinstance(value, str) else ""


def _part_is_thought(part: dict[str, Any]) -> bool:
    value = part.get("thought")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    snake_value = part.get("is_thought") or part.get("isThought")
    if isinstance(snake_value, bool):
        return snake_value
    if isinstance(snake_value, str):
        return snake_value.strip().lower() in {"true", "1", "yes"}
    return False
