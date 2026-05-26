"""Adapter for Kimi Code Anthropic-compatible Messages API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import suppress
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
from personagent.infrastructure.llm.kimi_payload import KimiPayloadBuilder
from personagent.infrastructure.llm.kimi_stream import (
    KimiStreamParser,
    _AnthropicStreamState,
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
        self._payload_builder = KimiPayloadBuilder(
            default_model=self.default_model,
            default_max_tokens=self.default_max_tokens,
        )
        self._stream_parser = KimiStreamParser()

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
        return self._payload_builder.build_payload(
            messages,
            temperature,
            max_tokens,
            stream,
            extra,
            tools=tools,
            tool_choice=tool_choice,
        )

    def _parse_message_response(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> InferenceResult:
        parsed = self._stream_parser.parse_content_blocks(data.get("content") or [])
        model = str(data.get("model") or fallback_model)
        metadata: dict[str, Any] = {"provider": "kimi", "model": model}
        if parsed["thinking_signatures"]:
            metadata["kimi_thinking_signatures"] = parsed["thinking_signatures"]

        return InferenceResult(
            content=parsed["content"],
            reasoning_content=parsed["reasoning"],
            finish_reason=self._stream_parser._finish_reason(
                data.get("stop_reason"), bool(parsed["tool_calls"])
            ),
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
        """Proxy to KimiStreamParser — preserves backward compatibility."""
        return self._stream_parser.parse_stream_event(data, state)

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Proxy to KimiPayloadBuilder — preserves backward compatibility."""
        return self._payload_builder.convert_messages(messages)

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
