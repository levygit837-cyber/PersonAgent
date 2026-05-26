"""Adapter for ZenMux OpenAI-compatible APIs."""

from __future__ import annotations

from typing import Any

import httpx

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendError,
    LLMBackendTimeoutError,
    provider_http_error,
)
from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.infrastructure.llm.nvidia_nim_adapter import (
    DEFAULT_OUTPUT_TOKENS,
    FINAL_RESPONSE_TOKEN_RESERVE,
    MIN_REASONING_MAX_TOKENS,
    NvidiaNimAdapter,
    _response_error_text,
)
from personagent.infrastructure.llm.shared.openai_compatible_parser import (
    ThinkingTagState,
    extract_reasoning_field,
    normalize_message_content,
    split_thinking_tags,
)

ZENMUX_CONTEXT_WINDOW = 1_000_000
ZENMUX_MAX_OUTPUT_TOKENS = 256_000
ZENMUX_FREE_DEEPSEEK_MODELS = {
    "deepseek/deepseek-v4-flash-free",
    "deepseek/deepseek-v4-pro-free",
}
ZENMUX_DEEPSEEK_MODELS = {
    *ZENMUX_FREE_DEEPSEEK_MODELS,
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
}


class ZenMuxAdapter(NvidiaNimAdapter):
    """ZenMux provider using OpenAI Chat Completions as the primary runtime."""

    def __init__(
        self,
        base_url: str = "https://zenmux.ai/api/v1",
        api_key: str = "",
        timeout: float = 240.0,
        stream_read_timeout: float | None = 0.0,
        default_model: str = "deepseek/deepseek-v4-flash-free",
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        models_cache_ttl_seconds: int = 300,
        context_window: int = ZENMUX_CONTEXT_WINDOW,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            stream_read_timeout=stream_read_timeout,
            default_model=default_model,
            default_max_tokens=default_max_tokens,
            models_cache_ttl_seconds=models_cache_ttl_seconds,
            provider_key="zenmux",
            provider_display_name="ZenMux",
            api_key_env_name="ZENMUX_API_KEY",
        )
        self.context_window = context_window

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> InferenceResult:
        payload = self._build_payload(
            messages,
            temperature,
            max_tokens,
            stream,
            kwargs,
            tools=tools,
            tool_choice=tool_choice,
        )

        try:
            client = await self._get_client()
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(f"Could not connect to ZenMux at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(f"Timeout calling ZenMux ({self.timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            detail = await _response_error_text(exc.response)
            raise provider_http_error(
                provider="ZenMux",
                status_code=exc.response.status_code,
                detail=detail[:500] or exc.response.reason_phrase,
                retry_after=exc.response.headers.get("retry-after"),
            ) from exc

        return self._parse_chat_response(response.json(), payload["model"])

    async def responses_completion(
        self,
        input_value: str | list[dict[str, Any]],
        *,
        model: str | None = None,
        reasoning_level: str | None = None,
        reasoning_summary: str = "auto",
    ) -> InferenceResult:
        requested_model = str(model or "").strip()
        payload = {
            "model": self.default_model if requested_model in {"", "local-model"} else requested_model,
            "input": input_value,
            "reasoning": {
                "effort": self._responses_reasoning_effort(reasoning_level),
                "summary": reasoning_summary,
            },
        }

        try:
            client = await self._get_client()
            response = await client.post("/responses", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(f"Could not connect to ZenMux at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(f"Timeout calling ZenMux Responses ({self.timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            detail = await _response_error_text(exc.response)
            raise provider_http_error(
                provider="ZenMux",
                status_code=exc.response.status_code,
                detail=detail[:500] or exc.response.reason_phrase,
                retry_after=exc.response.headers.get("retry-after"),
            ) from exc

        return self._parse_responses_response(response.json(), payload["model"])

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        extra: dict[str, Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        thinking_budget = self._reasoning_budget(extra.get("reasoning_budget_tokens"))
        effective_max_tokens = self._resolve_effective_max_tokens(
            model=model,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages_with_reasoning(messages),
            "max_tokens": effective_max_tokens,
            "stream": stream,
            "reasoning": {
                "enabled": True,
                "effort": self._reasoning_effort(extra.get("reasoning_level")),
                "max_tokens": min(thinking_budget or 2048, effective_max_tokens),
            },
        }

        if not self._is_reasoning_chat_model(model):
            payload["temperature"] = temperature
        if extra.get("stop"):
            payload["stop"] = extra["stop"]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        return payload

    def _parse_chat_response(self, data: dict[str, Any], fallback_model: str) -> InferenceResult:
        choices = data.get("choices") or []
        if not choices:
            raise LLMBackendError(f"ZenMux returned no choices: {data}")

        choice = choices[0]
        message = choice.get("message", {})
        content, reasoning_content, reasoning_details = self._normalize_chat_message(message)
        model = data.get("model") or fallback_model
        metadata: dict[str, Any] = {"provider": "zenmux", "model": model}
        if reasoning_details is not None:
            metadata["zenmux_reasoning_details"] = reasoning_details

        return InferenceResult(
            content=content,
            reasoning_content=reasoning_content,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            model=model,
            tool_calls=message.get("tool_calls"),
            metadata=metadata,
        )

    def _parse_stream_chunk(
        self,
        data: dict[str, Any],
        fallback_model: str,
        tool_call_parts: dict[int, dict[str, Any]] | None = None,
        thinking_state: ThinkingTagState | None = None,
    ) -> StreamChunk:
        choices = data.get("choices", [])
        if not choices:
            return StreamChunk()

        delta = choices[0].get("delta", {})
        reasoning_details = delta.get("reasoning_details")
        chunk = super()._parse_stream_chunk(
            data,
            fallback_model,
            tool_call_parts,
            thinking_state,
        )
        details_text = _reasoning_details_text(reasoning_details)
        if not details_text and reasoning_details is None:
            return chunk

        metadata = dict(chunk.metadata)
        if chunk.content or chunk.reasoning_content or chunk.finish_reason or chunk.tool_calls or details_text:
            metadata.setdefault("provider", "zenmux")
            metadata.setdefault("model", data.get("model") or fallback_model)
        if reasoning_details is not None:
            metadata["zenmux_reasoning_details"] = reasoning_details
        reasoning = details_text + chunk.reasoning_content
        return StreamChunk(
            content=chunk.content,
            reasoning_content=reasoning,
            finish_reason=chunk.finish_reason,
            usage=chunk.usage,
            tool_calls=chunk.tool_calls,
            images=chunk.images,
            is_thinking=bool(reasoning and not chunk.content),
            metadata=metadata,
        )

    def _parse_responses_response(self, data: dict[str, Any], fallback_model: str) -> InferenceResult:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        raw_reasoning: list[Any] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "reasoning":
                raw_reasoning.append(item)
                summary = item.get("summary")
                if isinstance(summary, str):
                    reasoning_parts.append(summary)
                elif isinstance(summary, list):
                    reasoning_parts.extend(_content_blocks_text(summary))
                reasoning_parts.append(_reasoning_details_text(item.get("content")))
            elif item_type == "message":
                content_parts.extend(_content_blocks_text(item.get("content")))

        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text and not content_parts:
            content_parts.append(output_text)

        model = data.get("model") or fallback_model
        metadata: dict[str, Any] = {"provider": "zenmux", "model": model}
        if raw_reasoning:
            metadata["zenmux_responses_reasoning"] = raw_reasoning
        return InferenceResult(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
            finish_reason=data.get("status"),
            usage=data.get("usage"),
            model=model,
            metadata=metadata,
        )

    def _normalize_chat_message(
        self,
        message: dict[str, Any],
    ) -> tuple[str, str, Any | None]:
        raw_content_value = message.get("content", "") or ""
        raw_content = (
            raw_content_value
            if isinstance(raw_content_value, str)
            else "".join(_content_blocks_text(raw_content_value))
        )
        reasoning_details = message.get("reasoning_details")
        details_text = _reasoning_details_text(reasoning_details)
        direct_reasoning = extract_reasoning_field(message)
        visible, tagged_reasoning = split_thinking_tags(raw_content, flush=True)
        if not visible and not details_text:
            visible, tagged_reasoning = normalize_message_content(message)
            direct_reasoning = ""
        return visible, details_text + direct_reasoning + tagged_reasoning, reasoning_details

    def _normalize_model(self, item: dict[str, Any]) -> dict[str, Any]:
        model = super()._normalize_model(item)
        raw_capabilities = item.get("capabilities")
        if isinstance(raw_capabilities, dict) and raw_capabilities.get("reasoning") is True:
            if "reasoning_chat" not in model["capabilities"]:
                model["capabilities"].append("reasoning_chat")
            model["supports_reasoning"] = True
        if "streaming" not in model["capabilities"]:
            model["capabilities"].append("streaming")
        if "tools" not in model["capabilities"]:
            model["capabilities"].append("tools")
        model["context_length"] = int(item.get("context_length") or self.context_window)
        model["max_output_tokens"] = ZENMUX_MAX_OUTPUT_TOKENS
        model["supports_streaming"] = True
        model["supports_tools"] = True
        return model

    def _normalize_model_response(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = super()._normalize_model_response(data)
        models = [
            model
            for model in normalized.get("data", [])
            if str(model.get("id") or "").lower() in ZENMUX_DEEPSEEK_MODELS
        ]
        models.sort(key=lambda model: _zenmux_model_rank(str(model.get("id") or "")))
        return {"object": "list", "provider": "zenmux", "data": models}

    def _is_reasoning_chat_model(self, model_id: str) -> bool:
        return model_id.lower() in ZENMUX_DEEPSEEK_MODELS

    def _supports_thinking_budget(self, model_id: str) -> bool:
        return self._is_reasoning_chat_model(model_id)

    def _resolve_effective_max_tokens(
        self,
        *,
        model: str,
        max_tokens: int,
        thinking_budget: int | None,
    ) -> int:
        effective_max_tokens = max_tokens if max_tokens > 0 else self.default_max_tokens
        if self._is_reasoning_chat_model(model):
            effective_max_tokens = max(effective_max_tokens, MIN_REASONING_MAX_TOKENS)
        if thinking_budget is not None and thinking_budget >= effective_max_tokens:
            effective_max_tokens = thinking_budget + FINAL_RESPONSE_TOKEN_RESERVE
        return min(effective_max_tokens, ZENMUX_MAX_OUTPUT_TOKENS)

    def _reasoning_budget(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(0, min(int(value), 32_768))
        except (TypeError, ValueError):
            return None

    def _reasoning_effort(self, level: Any) -> str:
        normalized = str(level or "medium").strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return "high"

    def _responses_reasoning_effort(self, level: Any) -> str:
        normalized = str(level or "medium").strip().lower()
        if normalized in {"low", "medium", "high", "xhigh"}:
            return normalized
        if normalized == "max":
            return "xhigh"
        if normalized in {"none", "minimal"}:
            return "low"
        return "medium"

    def _messages_with_reasoning(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized_messages: list[dict[str, Any]] = []
        for message in messages:
            next_message = dict(message)
            metadata = next_message.pop("metadata", None)
            if next_message.get("role") == "assistant" and isinstance(metadata, dict):
                if (
                    "reasoning_content" not in next_message
                    and isinstance(metadata.get("reasoning_content"), str)
                ):
                    next_message["reasoning_content"] = metadata["reasoning_content"]
                if "reasoning_details" not in next_message and metadata.get("zenmux_reasoning_details"):
                    next_message["reasoning_details"] = metadata["zenmux_reasoning_details"]
            normalized_messages.append(next_message)
        return normalized_messages


def _reasoning_details_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("signature") and not any(
            isinstance(value.get(key), str) and value.get(key)
            for key in ("text", "content", "reasoning", "thinking")
        ):
            return ""
        return "".join(
            str(value.get(key) or "")
            for key in ("text", "content", "reasoning", "thinking")
            if isinstance(value.get(key), str)
        )
    if isinstance(value, list):
        return "".join(_reasoning_details_text(item) for item in value)
    return ""


def _content_blocks_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    parts: list[str] = []
    for block in value:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            block_type = str(block.get("type") or "")
            if block_type in {"output_text", "text", "summary_text"} and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block.get("content"), str):
                parts.append(block["content"])
            elif isinstance(block.get("summary"), str):
                parts.append(block["summary"])
    return parts


def _zenmux_model_rank(model_id: str) -> tuple[int, str]:
    normalized = model_id.lower()
    if normalized == "deepseek/deepseek-v4-flash-free":
        return (0, normalized)
    if normalized == "deepseek/deepseek-v4-pro-free":
        return (1, normalized)
    return (2, normalized)
