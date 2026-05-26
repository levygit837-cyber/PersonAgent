"""Adapter for Kimi Code Anthropic-compatible Messages API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendError,
    LLMBackendTimeoutError,
    provider_http_error,
)
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.llm.kimi_auth import KimiTokenManager
from personagent.infrastructure.llm.kimi_history import (
    anthropic_history_blocks,
    anthropic_history_blocks_from_tool_calls,
    attach_anthropic_history_blocks,
    parse_tool_arguments,
    tool_call_from_anthropic_block,
)

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"

DEFAULT_MODEL = "kimi-for-coding"
DEFAULT_OUTPUT_TOKENS = 32768
DEFAULT_CONTEXT_WINDOW = 262144
DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 0.0
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
MIN_THINKING_BUDGET_TOKENS = 1024
MAX_THINKING_BUDGET_TOKENS = 30720
FINAL_RESPONSE_TOKEN_RESERVE = 1024
STREAM_CONNECT_TIMEOUT_SECONDS = 30.0
STREAM_POOL_TIMEOUT_SECONDS = 30.0

REASONING_BUDGETS = {
    "low": 2048,
    "medium": 4082,
    "high": 8192,
    "xhigh": 16382,
    "max": 32768,
}


@dataclass(slots=True)
class _AnthropicStreamState:
    model: str
    content_blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    thinking_signatures: list[str] = field(default_factory=list)
    finish_reason: str | None = None


class KimiCodingAdapter(LLMBackendRepository):  # type: ignore[misc]
    """Kimi Code adapter using the Anthropic-compatible `/messages` endpoint."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        stream_read_timeout: float | None = DEFAULT_STREAM_READ_TIMEOUT_SECONDS,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token_manager = KimiTokenManager(api_key=api_key)
        self.timeout = timeout
        self.stream_read_timeout = self._normalize_stream_read_timeout(stream_read_timeout)
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self.context_window = context_window
        self.anthropic_version = anthropic_version
        self.headers = {
            "Authorization": f"Bearer {self._token_manager.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "anthropic-version": self.anthropic_version,
        }
        self._client: httpx.AsyncClient | None = None

    async def _try_auto_refresh_token(self) -> bool:
        """Proxy to KimiTokenManager — preserves backward compatibility."""
        refreshed = await self._token_manager.try_auto_refresh()
        if refreshed:
            self.headers["Authorization"] = f"Bearer {self._token_manager.api_key}"
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            self._client = None
        return refreshed

    def _is_token_expired(self) -> bool:
        """Proxy to KimiTokenManager — preserves backward compatibility."""
        return self._token_manager.is_expired()

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._token_manager.api_key:
            raise LLMBackendConnectionError("KIMI_API_KEY is not configured")
        if self._token_manager.is_expired():
            await self._try_auto_refresh_token()
        if not self._token_manager.api_key:
            raise LLMBackendConnectionError("KIMI_API_KEY is not configured and auto-refresh failed")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout,
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMBackendConnectionError, LLMBackendTimeoutError)),
        reraise=True,
    )
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
            response = await client.post("/messages", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(f"Could not connect to Kimi Code at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(f"Timeout calling Kimi Code ({self.timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                refreshed = await self._try_auto_refresh_token()
                if refreshed:
                    client = await self._get_client()
                    response = await client.post("/messages", json=payload)
                    response.raise_for_status()
                    return self._parse_message_response(response.json(), payload["model"])
            raise self._http_error(exc, "Kimi Code") from exc

        return self._parse_message_response(response.json(), payload["model"])

    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        payload = self._build_payload(
            messages,
            temperature,
            max_tokens,
            True,
            kwargs,
            tools=tools,
            tool_choice=tool_choice,
        )
        state = _AnthropicStreamState(model=payload["model"])

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                "/messages",
                json=payload,
                timeout=self._stream_timeout_config(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                response.raise_for_status()
                response.encoding = "utf-8"

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line.removeprefix("data:").strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    chunk, done = self._parse_stream_event(data, state)
                    if not chunk.is_empty:
                        yield chunk
                    if done:
                        break

        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(f"Could not connect to Kimi Code at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                f"Timeout streaming from Kimi Code ({self._stream_timeout_label()}, model={payload['model']})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                refreshed = await self._try_auto_refresh_token()
                if refreshed:
                    client = await self._get_client()
                    async with client.stream(
                        "POST",
                        "/messages",
                        json=payload,
                        timeout=self._stream_timeout_config(),
                    ) as response:
                        if response.status_code >= 400:
                            await response.aread()
                        response.raise_for_status()
                        response.encoding = "utf-8"
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_str = line.removeprefix("data:").strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            chunk, done = self._parse_stream_event(data, state)
                            if not chunk.is_empty:
                                yield chunk
                            if done:
                                break
                    return
            raise self._http_error(exc, "Kimi Code") from exc

    async def health_check(self) -> dict[str, Any]:
        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider": "kimi",
                "error": "KIMI_API_KEY is not configured",
            }
        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=10.0)
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "provider": "kimi",
            }
        except Exception as exc:
            return {"status": "unhealthy", "provider": "kimi", "error": str(exc)}

    async def get_model_info(self) -> dict[str, Any]:
        return await self.list_models()

    async def list_models(
        self,
        *,
        capability: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        del refresh
        model = {
            "id": self.default_model,
            "name": "Kimi K2.6",
            "provider": "kimi",
            "label": "Kimi K2.6",
            "owned_by": "kimi",
            "context_length": self.context_window,
            "capabilities": ["chat", "reasoning_chat", "tools", "streaming"],
            "supports_streaming": True,
            "supports_reasoning": True,
            "supports_tools": True,
            "supports_thinking_budget": True,
            "raw": {
                "id": self.default_model,
                "endpoint": f"{self.base_url}/messages",
                "protocol": "anthropic-messages",
            },
        }
        models = [model]
        if capability:
            models = [item for item in models if capability in item["capabilities"]]
        return {"object": "list", "provider": "kimi", "data": models}

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
        del temperature
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        effective_max_tokens = self._resolve_effective_max_tokens(max_tokens)
        system, anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": effective_max_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        thinking = self._thinking_config(extra, effective_max_tokens)
        if thinking is not None:
            payload["thinking"] = thinking

        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
            converted_tool_choice = self._convert_tool_choice(tool_choice)
            if converted_tool_choice:
                payload["tool_choice"] = converted_tool_choice

        return payload

    def _parse_message_response(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> InferenceResult:
        parsed = self._parse_content_blocks(data.get("content") or [])
        model = str(data.get("model") or fallback_model)
        metadata: dict[str, Any] = {"provider": "kimi", "model": model}
        if parsed["thinking_signatures"]:
            metadata["kimi_thinking_signatures"] = parsed["thinking_signatures"]

        return InferenceResult(
            content=parsed["content"],
            reasoning_content=parsed["reasoning"],
            finish_reason=self._finish_reason(data.get("stop_reason"), bool(parsed["tool_calls"])),
            usage=data.get("usage"),
            model=model,
            tool_calls=parsed["tool_calls"] or None,
            metadata=metadata,
        )

    def _parse_stream_event(
        self,
        data: dict[str, Any],
        state: _AnthropicStreamState,
    ) -> tuple[StreamChunk, bool]:
        event_type = data.get("type")
        metadata = {"provider": "kimi", "model": state.model}

        if event_type == "error" or data.get("error"):
            raise LLMBackendError(f"Kimi Code stream error: {data.get('error') or data}")

        if event_type == "message_start":
            message = data.get("message") or {}
            if message.get("model"):
                state.model = str(message["model"])
            return StreamChunk(), False

        if event_type == "content_block_start":
            index = int(data.get("index", 0))
            block = dict(data.get("content_block") or {})
            block.setdefault("_partial_json", "")
            state.content_blocks[index] = block
            return StreamChunk(), False

        if event_type == "content_block_delta":
            index = int(data.get("index", 0))
            block = state.content_blocks.setdefault(index, {})
            delta = data.get("delta") or {}
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                text = str(delta.get("text") or "")
                block["text"] = str(block.get("text") or "") + text
                return StreamChunk(content=text, metadata=metadata), False
            if delta_type == "thinking_delta":
                thinking = str(delta.get("thinking") or "")
                block["thinking"] = str(block.get("thinking") or "") + thinking
                return StreamChunk(reasoning_content=thinking, is_thinking=True, metadata=metadata), False
            if delta_type == "signature_delta":
                signature = str(delta.get("signature") or "")
                if signature:
                    block["signature"] = signature
                    state.thinking_signatures.append(signature)
                    return StreamChunk(
                        metadata={**metadata, "kimi_thinking_signatures": [signature]}
                    ), False
            if delta_type == "input_json_delta":
                block["_partial_json"] = str(block.get("_partial_json") or "") + str(
                    delta.get("partial_json") or ""
                )
            return StreamChunk(), False

        if event_type == "content_block_stop":
            return StreamChunk(), False

        if event_type == "message_delta":
            delta = data.get("delta") or {}
            state.finish_reason = self._finish_reason(delta.get("stop_reason"), False)
            if state.thinking_signatures:
                metadata["kimi_thinking_signatures"] = list(state.thinking_signatures)
            tool_calls = (
                self._tool_calls_from_stream_state(state)
                if state.finish_reason == "tool_calls"
                else None
            )
            return (
                StreamChunk(
                    finish_reason=state.finish_reason,
                    tool_calls=tool_calls,
                    usage=data.get("usage"),
                    metadata=metadata,
                ),
                False,
            )

        if event_type == "message_stop":
            return StreamChunk(), True

        return StreamChunk(), False

    def _parse_content_blocks(self, blocks: list[Any]) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        signatures: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            block_type = raw_block.get("type")
            if block_type == "text":
                content_parts.append(str(raw_block.get("text") or ""))
            elif block_type == "thinking":
                thinking = raw_block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    reasoning_parts.append(thinking)
                signature = raw_block.get("signature")
                if isinstance(signature, str) and signature:
                    signatures.append(signature)
            elif block_type == "tool_use":
                tool_calls.append(tool_call_from_anthropic_block(raw_block))

        history_blocks = anthropic_history_blocks(
            {index: block for index, block in enumerate(blocks) if isinstance(block, dict)}
        )
        attach_anthropic_history_blocks(tool_calls, history_blocks)

        return {
            "content": "".join(content_parts),
            "reasoning": "".join(reasoning_parts),
            "thinking_signatures": signatures,
            "tool_calls": tool_calls,
        }

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for message in messages:
            role = str(message.get("role") or "user")
            if role == "system":
                text = self._coerce_text(message.get("content"))
                if text:
                    system_parts.append(text)
                continue

            if role == "assistant":
                blocks = self._assistant_blocks(message)
                self._append_message(converted, "assistant", blocks)
                continue

            if role == "tool":
                self._append_message(
                    converted,
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(message.get("tool_call_id") or ""),
                            "content": self._coerce_text(message.get("content")),
                        }
                    ],
                )
                continue

            self._append_message(converted, "user", self._text_blocks(message.get("content")))

        if not converted:
            converted.append({"role": "user", "content": [{"type": "text", "text": ""}]})

        return "\n\n".join(system_parts) if system_parts else None, converted

    def _assistant_blocks(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = message.get("tool_calls") or []
        replay_blocks = anthropic_history_blocks_from_tool_calls(tool_calls)
        if replay_blocks:
            return replay_blocks

        blocks = self._text_blocks(message.get("content"))
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            arguments = function.get("arguments") or {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(tool_call.get("id") or ""),
                    "name": str(function.get("name") or tool_call.get("name") or ""),
                    "input": parse_tool_arguments(arguments),
                }
            )
        return blocks or [{"type": "text", "text": ""}]

    def _tool_calls_from_stream_state(
        self,
        state: _AnthropicStreamState,
    ) -> list[dict[str, Any]]:
        history_blocks = anthropic_history_blocks(state.content_blocks)
        tool_calls = [
            tool_call_from_anthropic_block(block)
            for _, block in sorted(state.content_blocks.items())
            if block.get("type") == "tool_use"
        ]
        attach_anthropic_history_blocks(tool_calls, history_blocks)
        return tool_calls

    def _append_message(
        self,
        messages: list[dict[str, Any]],
        role: str,
        content: list[dict[str, Any]],
    ) -> None:
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
            return
        messages.append({"role": role, "content": content})

    def _text_blocks(self, content: Any) -> list[dict[str, Any]]:
        text = self._coerce_text(content)
        return [{"type": "text", "text": text}] if text else []

    def _coerce_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content)

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools or []:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            converted.append(
                {
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "input_schema": function.get("parameters")
                    if isinstance(function.get("parameters"), dict)
                    else {"type": "object", "properties": {}},
                }
            )
        return converted

    def _convert_tool_choice(self, tool_choice: str | dict[str, Any] | None) -> dict[str, Any] | None:
        if tool_choice is None:
            return {"type": "auto"}
        if isinstance(tool_choice, str):
            normalized = tool_choice.strip().lower()
            if normalized in {"", "none"}:
                return None
            if normalized in {"required", "any"}:
                return {"type": "any"}
            return {"type": "auto"}
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                function = tool_choice.get("function") or {}
                if function.get("name"):
                    return {"type": "tool", "name": str(function["name"])}
            if tool_choice.get("type") in {"auto", "any", "tool"}:
                return tool_choice
        return {"type": "auto"}

    def _thinking_config(
        self,
        extra: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any] | None:
        raw_budget = extra.get("reasoning_budget_tokens")
        if raw_budget is None and extra.get("reasoning_level"):
            raw_budget = REASONING_BUDGETS.get(str(extra["reasoning_level"]).strip().lower())
        if raw_budget is None:
            return None

        budget = int(raw_budget)
        if budget <= 0:
            return {"type": "disabled"}

        budget = max(MIN_THINKING_BUDGET_TOKENS, budget)
        budget = min(budget, MAX_THINKING_BUDGET_TOKENS, max_tokens - FINAL_RESPONSE_TOKEN_RESERVE)
        if budget < MIN_THINKING_BUDGET_TOKENS:
            return {"type": "disabled"}
        return {"type": "enabled", "budget_tokens": budget}

    def _resolve_effective_max_tokens(self, max_tokens: int) -> int:
        if max_tokens > 0:
            return min(max_tokens, self.default_max_tokens)
        return self.default_max_tokens

    def _finish_reason(self, raw: Any, has_tool_calls: bool) -> str | None:
        if has_tool_calls or raw == "tool_use":
            return "tool_calls"
        if raw == "end_turn":
            return "stop"
        if raw == "max_tokens":
            return "length"
        return str(raw) if raw else None

    def _stream_timeout_config(self) -> httpx.Timeout:
        bounded_timeout = max(float(self.timeout), 1.0)
        return httpx.Timeout(
            timeout=None,
            connect=min(STREAM_CONNECT_TIMEOUT_SECONDS, bounded_timeout),
            read=self.stream_read_timeout,
            write=bounded_timeout,
            pool=min(STREAM_POOL_TIMEOUT_SECONDS, bounded_timeout),
        )

    def _stream_timeout_label(self) -> str:
        if self.stream_read_timeout is None:
            return "read timeout disabled"
        return f"read timeout {self.stream_read_timeout}s"

    def _normalize_stream_read_timeout(self, value: float | None) -> float | None:
        if value is None:
            return None
        timeout = float(value)
        return timeout if timeout > 0 else None

    def _http_error_message(self, exc: httpx.HTTPStatusError, provider: str) -> str:
        body = ""
        with suppress(Exception):
            body = exc.response.text[:500]
        suffix = f": {body}" if body else f": {exc.response.reason_phrase}"
        return f"{provider} HTTP {exc.response.status_code}{suffix}"

    def _http_error(self, exc: httpx.HTTPStatusError, provider: str) -> LLMBackendError:
        body = ""
        with suppress(Exception):
            body = exc.response.text[:500]
        return provider_http_error(
            provider=provider,
            status_code=exc.response.status_code,
            detail=body or exc.response.reason_phrase,
            retry_after=exc.response.headers.get("retry-after"),
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
