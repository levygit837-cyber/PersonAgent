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
from personagent.infrastructure.llm.openai_compatible_parser import (
    ThinkingTagState,
    accumulate_tool_call_delta,
    extract_reasoning_field,
    normalize_message_content,
    split_thinking_tags,
)

logger = structlog.get_logger(__name__)

DEFAULT_OUTPUT_TOKENS = 65536
MAX_REASONING_BUDGET_TOKENS = 32768
MIN_REASONING_MAX_TOKENS = 4096
FINAL_RESPONSE_TOKEN_RESERVE = 2048
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 0.0
STREAM_CONNECT_TIMEOUT_SECONDS = 30.0
STREAM_POOL_TIMEOUT_SECONDS = 30.0

KNOWN_REASONING_CHAT_MODELS = {
    # DeepSeek models
    "deepseek-ai/deepseek-v4-flash",
    "deepseek-ai/deepseek-v4-pro",
    # NVIDIA Nemotron models
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/llama-3.1-nemotron-51b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/nemotron-4-340b-reward",
    "nvidia/nemotron-nano-3-30b-a3b",
    "nvidia/nvidia-nemotron-nano-9b-v2",
    # Moonshot AI Kimi K2 models
    "moonshotai/kimi-k2.6",
    # Mistral models
    "mistralai/mistral-large-3-675b-instruct-2512",
    "mistralai/mistral-large-2-instruct",
    "mistralai/mistral-large",
    "mistralai/mistral-medium-3.5-128b",
    "mistralai/mistral-small-4-119b-2603",
    # Meta Llama
    "meta/llama-3.1-405b-instruct",
    "meta/llama-4-maverick-17b-128e-instruct",
    # Qwen large models (480B+)
    "qwen/qwen3-coder-480b-a35b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3-next-80b-a3b-thinking",
    # OpenAI OSS models
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    # ByteDance
    "bytedance/seed-oss-36b-instruct",
    # Zhipu AI (GLM)
    "z-ai/glm-5.1",
    "z-ai/glm5",
    # Stepfun
    "stepfun-ai/step-3.5-flash",
}

THINKING_TEMPLATE_KWARGS_MODELS = {
    "deepseek-ai/deepseek-v4-flash",
    "deepseek-ai/deepseek-v4-pro",
    "nvidia/nemotron-3-nano-30b-a3b",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3-next-80b-a3b-thinking",
}


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
        self.stream_read_timeout = self._normalize_stream_read_timeout(stream_read_timeout)
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
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        request_reasoning_budget = extra.get("reasoning_budget_tokens")
        thinking_budget = (
            min(int(request_reasoning_budget), MAX_REASONING_BUDGET_TOKENS)
            if request_reasoning_budget is not None and self._supports_thinking_budget(model)
            else None
        )
        effective_max_tokens = self._resolve_effective_max_tokens(
            model=model,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "stream": stream,
        }
        chat_template_kwargs = dict(extra.get("chat_template_kwargs") or {})
        if self._supports_thinking_template_kwargs(model):
            chat_template_kwargs.setdefault("enable_thinking", True)
        if chat_template_kwargs:
            payload["chat_template_kwargs"] = chat_template_kwargs

        if thinking_budget is not None:
            payload["nvext"] = {"max_thinking_tokens": thinking_budget}

        if extra.get("top_p"):
            payload["top_p"] = extra["top_p"]
        if extra.get("stop"):
            payload["stop"] = extra["stop"]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        return payload

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
        finish_reason = choices[0].get("finish_reason")
        tool_call_parts = tool_call_parts if tool_call_parts is not None else {}

        if delta.get("tool_calls"):
            self._accumulate_tool_call_delta(delta["tool_calls"], tool_call_parts)

        raw_content = delta.get("content", "") or ""
        tag_content, tag_reasoning = split_thinking_tags(
            raw_content,
            thinking_state,
            flush=finish_reason is not None,
        )
        content = tag_content
        reasoning = extract_reasoning_field(delta) + tag_reasoning
        tool_calls = (
            self._finalize_tool_calls(tool_call_parts)
            if finish_reason == "tool_calls" and tool_call_parts
            else None
        )

        has_signal = bool(content or reasoning or finish_reason or data.get("usage") or tool_calls)
        metadata = {}
        if has_signal:
            metadata = {
                "provider": self.provider_key,
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

    def _normalize_model_response(self, data: dict[str, Any]) -> dict[str, Any]:
        raw_models = data.get("data", []) if isinstance(data, dict) else []
        models_by_id: dict[str, dict[str, Any]] = {}
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            model = self._normalize_model(item)
            models_by_id[model_id] = model

        return {
            "object": "list",
            "provider": self.provider_key,
            "data": list(models_by_id.values()),
        }

    def _normalize_model(self, item: dict[str, Any]) -> dict[str, Any]:
        model_id = str(item["id"])
        supports_reasoning = self._is_reasoning_chat_model(model_id)
        supports_thinking_budget = self._supports_thinking_budget(model_id)
        capabilities = ["chat"]
        if supports_reasoning:
            capabilities.append("reasoning_chat")
        if supports_thinking_budget:
            capabilities.append("thinking_budget")

        return {
            "id": model_id,
            "provider": self.provider_key,
            "label": _model_label(model_id),
            "owned_by": item.get("owned_by") or model_id.split("/", 1)[0],
            "capabilities": capabilities,
            "supports_streaming": True,
            "supports_reasoning": supports_reasoning,
            "supports_thinking_budget": supports_thinking_budget,
            "raw": item,
        }

    def _filter_model_response(
        self,
        response: dict[str, Any],
        capability: str | None,
    ) -> dict[str, Any]:
        models = list(response.get("data") or [])
        if capability:
            models = [model for model in models if capability in model.get("capabilities", [])]
        return {
            "object": "list",
            "provider": self.provider_key,
            "data": models,
        }

    def _is_reasoning_chat_model(self, model_id: str) -> bool:
        lower = model_id.lower()
        return lower in KNOWN_REASONING_CHAT_MODELS

    def _supports_thinking_budget(self, model_id: str) -> bool:
        lower = model_id.lower()
        return "nemotron-3-nano-30b-a3b" in lower or "nemotron-nano-9b-v2" in lower

    def _supports_thinking_template_kwargs(self, model_id: str) -> bool:
        return model_id.lower() in THINKING_TEMPLATE_KWARGS_MODELS

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

    def _accumulate_tool_call_delta(
        self,
        deltas: list[dict[str, Any]],
        accumulator: dict[int, dict[str, Any]],
    ) -> None:
        accumulate_tool_call_delta(deltas, accumulator)

    def _finalize_tool_calls(
        self,
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

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


def _model_label(model_id: str) -> str:
    name = model_id.split("/", 1)[-1]
    return " ".join(
        part.upper() if part.isdigit() else part.capitalize() for part in name.split("-")
    )


async def _response_error_text(response: httpx.Response) -> str:
    try:
        if not response.is_closed:
            await response.aread()
        return response.text
    except Exception:
        return response.reason_phrase
