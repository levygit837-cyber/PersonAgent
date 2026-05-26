"""Adapter for NVIDIA NIM hosted OpenAI-compatible APIs."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendError,
    LLMBackendTimeoutError,
    provider_http_error,
)
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.llm.nvidia_nim_adapter.constants import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_STREAM_READ_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    FINAL_RESPONSE_TOKEN_RESERVE,
    MIN_REASONING_MAX_TOKENS,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.models import (
    _filter_model_response,
    _normalize_model_response,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.models import (
    _is_reasoning_chat_model as _default_is_reasoning_chat_model,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.models import (
    _normalize_model as _normalize_model_impl,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.models import (
    _supports_thinking_budget as _default_supports_thinking_budget,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.models import (
    _supports_thinking_template_kwargs as _default_supports_thinking_template_kwargs,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.payload import (
    _build_payload as _build_payload_impl,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.streaming import (
    _accumulate_tool_call_delta,
    _finalize_tool_calls,
    _normalize_stream_read_timeout,
    _parse_stream_chunk,
    _response_error_text,
    _stream_timeout_config,
    _stream_timeout_label,
)
from personagent.infrastructure.llm.openai_compatible_parser import (
    ThinkingTagState,
    normalize_message_content,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "NvidiaNimAdapter",
    "DEFAULT_OUTPUT_TOKENS",
    "FINAL_RESPONSE_TOKEN_RESERVE",
    "MIN_REASONING_MAX_TOKENS",
    "_response_error_text",
]


class NvidiaNimAdapter(LLMBackendRepository):  # type: ignore[misc]
    """NVIDIA NIM OpenAI-compatible adapter."""

    def __init__(
        self,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        stream_read_timeout: float | None = DEFAULT_STREAM_READ_TIMEOUT_SECONDS,
        default_model: str = "moonshotai/kimi-k2.6",
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        models_cache_ttl_seconds: int = 300,
        provider_key: str = "nvidia",
        provider_display_name: str = "NVIDIA NIM",
        api_key_env_name: str = "NVIDIA_API_KEY",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.stream_read_timeout = _normalize_stream_read_timeout(stream_read_timeout)
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self.models_cache_ttl_seconds = models_cache_ttl_seconds
        self.provider_key = provider_key
        self.provider_display_name = provider_display_name
        self.api_key_env_name = api_key_env_name
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        self._client: httpx.AsyncClient | None = None
        self._models_cache: dict[str, Any] | None = None
        self._models_cache_at = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise LLMBackendConnectionError(f"{self.api_key_env_name} is not configured")
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
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(
                f"Could not connect to {self.provider_display_name} at {self.base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                f"Timeout calling {self.provider_display_name} ({self.timeout}s)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = await _response_error_text(exc.response)
            raise provider_http_error(
                provider=self.provider_display_name,
                status_code=exc.response.status_code,
                detail=detail[:500] or exc.response.reason_phrase,
                retry_after=exc.response.headers.get("retry-after"),
            ) from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMBackendError(f"{self.provider_display_name} returned no choices: {data}")

        choice = choices[0]
        message = choice.get("message", {})
        content, reasoning_content = normalize_message_content(message)
        model = data.get("model") or payload["model"]

        return InferenceResult(
            content=content,
            reasoning_content=reasoning_content,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            model=model,
            tool_calls=message.get("tool_calls"),
            metadata={"provider": self.provider_key, "model": model},
        )

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
        tool_call_parts: dict[int, dict[str, Any]] = {}
        thinking_state = ThinkingTagState()

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                timeout=self._stream_timeout_config(),
            ) as response:
                response.raise_for_status()
                response.encoding = "utf-8"

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        yield StreamChunk(
                            finish_reason="stop",
                            metadata={
                                "provider": self.provider_key,
                                "model": payload["model"],
                            },
                        )
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        raise LLMBackendError(
                            f"{self.provider_display_name} stream error: {data['error']}"
                        )

                    chunk = self._parse_stream_chunk(
                        data,
                        payload["model"],
                        tool_call_parts,
                        thinking_state,
                    )
                    if not chunk.is_empty:
                        yield chunk

                    if chunk.is_finished:
                        break

        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(
                f"Could not connect to {self.provider_display_name} at {self.base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                f"Timeout streaming from {self.provider_display_name} "
                f"({self._stream_timeout_label()}, model={payload['model']})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = await _response_error_text(exc.response)
            raise provider_http_error(
                provider=self.provider_display_name,
                status_code=exc.response.status_code,
                detail=detail[:500] or exc.response.reason_phrase,
                retry_after=exc.response.headers.get("retry-after"),
            ) from exc

    async def health_check(self) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unhealthy", "error": f"{self.api_key_env_name} is not configured"}
        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=10.0)
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "provider": self.provider_key,
            }
        except Exception as exc:
            return {"status": "unhealthy", "provider": self.provider_key, "error": str(exc)}

    async def get_model_info(self) -> dict[str, Any]:
        return await self.list_models(capability="reasoning_chat")

    async def list_models(
        self,
        *,
        capability: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if not self.api_key:
            return {
                "object": "list",
                "data": [],
                "provider": self.provider_key,
                "error": f"{self.api_key_env_name} is not configured",
            }

        now = time.monotonic()
        if (
            not refresh
            and self._models_cache is not None
            and now - self._models_cache_at < self.models_cache_ttl_seconds
        ):
            return self._filter_model_response(self._models_cache, capability)

        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            normalized = self._normalize_model_response(data)
            self._models_cache = normalized
            self._models_cache_at = now
            return self._filter_model_response(normalized, capability)
        except Exception as exc:
            logger.warning(
                "provider_model_info_failed",
                provider=self.provider_key,
                error=str(exc),
            )
            return {
                "object": "list",
                "data": [],
                "provider": self.provider_key,
                "error": str(exc),
            }

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
        return _build_payload_impl(
            messages,
            temperature,
            max_tokens,
            stream,
            extra,
            default_model=self.default_model,
            default_max_tokens=self.default_max_tokens,
            provider_key=self.provider_key,
            is_reasoning_chat_model=self._is_reasoning_chat_model,
            supports_thinking_budget=self._supports_thinking_budget,
            supports_thinking_template_kwargs=self._supports_thinking_template_kwargs,
            resolve_effective_max_tokens=self._resolve_effective_max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

    def _parse_stream_chunk(
        self,
        data: dict[str, Any],
        fallback_model: str,
        tool_call_parts: dict[int, dict[str, Any]] | None = None,
        thinking_state: ThinkingTagState | None = None,
    ) -> StreamChunk:
        return _parse_stream_chunk(
            data,
            fallback_model,
            self.provider_key,
            tool_call_parts,
            thinking_state,
        )

    def _normalize_model(self, item: dict[str, Any]) -> dict[str, Any]:
        return _normalize_model_impl(
            item,
            self.provider_key,
            is_reasoning_chat_model=self._is_reasoning_chat_model,
            supports_thinking_budget=self._supports_thinking_budget,
        )

    def _normalize_model_response(self, data: dict[str, Any]) -> dict[str, Any]:
        return _normalize_model_response(
            data,
            self.provider_key,
            normalize_model=self._normalize_model,
        )


    def _filter_model_response(
        self,
        response: dict[str, Any],
        capability: str | None,
    ) -> dict[str, Any]:
        return _filter_model_response(response, capability, self.provider_key)

    def _is_reasoning_chat_model(self, model_id: str) -> bool:
        return _default_is_reasoning_chat_model(model_id)

    def _supports_thinking_budget(self, model_id: str) -> bool:
        return _default_supports_thinking_budget(model_id)

    def _supports_thinking_template_kwargs(self, model_id: str) -> bool:
        return _default_supports_thinking_template_kwargs(model_id)

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

        return effective_max_tokens

    def _stream_timeout_config(self) -> httpx.Timeout:
        return _stream_timeout_config(self.timeout, self.stream_read_timeout)

    def _stream_timeout_label(self) -> str:
        return _stream_timeout_label(self.stream_read_timeout)

    def _normalize_stream_read_timeout(self, value: float | None) -> float | None:
        return _normalize_stream_read_timeout(value)

    def _accumulate_tool_call_delta(
        self,
        deltas: list[dict[str, Any]],
        accumulator: dict[int, dict[str, Any]],
    ) -> None:
        _accumulate_tool_call_delta(deltas, accumulator)

    def _finalize_tool_calls(
        self,
        accumulator: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return _finalize_tool_calls(accumulator)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
