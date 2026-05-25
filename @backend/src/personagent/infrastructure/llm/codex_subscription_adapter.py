"""Adapter for ChatGPT Subscription access through the Codex backend API."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import httpx
import structlog

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendError,
    LLMBackendTimeoutError,
    provider_http_error,
)
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.llm.codex_auth import CodexAuthStore
from personagent.infrastructure.llm.codex_payload import CodexPayloadBuilder
from personagent.infrastructure.llm.codex_streaming import CodexStreamParser

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_CONTEXT_WINDOW = 272000
DEFAULT_OUTPUT_TOKENS = 65536
DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 0.0
DEFAULT_MODELS_CACHE_TTL_SECONDS = 300
FALLBACK_CLIENT_VERSION = "0.124.0"
STREAM_CONNECT_TIMEOUT_SECONDS = 30.0
STREAM_POOL_TIMEOUT_SECONDS = 30.0

class CodexSubscriptionAdapter(LLMBackendRepository):  # type: ignore[misc]
    """Direct Responses API adapter for Codex ChatGPT Subscription models."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        codex_home: str = "",
        codex_cli_path: str = "codex",
        client_version: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        stream_read_timeout: float | None = DEFAULT_STREAM_READ_TIMEOUT_SECONDS,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        models_cache_ttl_seconds: int = DEFAULT_MODELS_CACHE_TTL_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self.context_window = context_window
        self.timeout = timeout
        self.stream_read_timeout = self._normalize_stream_read_timeout(stream_read_timeout)
        self.models_cache_ttl_seconds = models_cache_ttl_seconds
        self.configured_client_version = client_version.strip()
        self.auth_store = CodexAuthStore(codex_home, codex_cli_path=codex_cli_path)
        self._payload_builder = CodexPayloadBuilder(default_model=self.default_model)
        self._stream_parser = CodexStreamParser()
        self._client: httpx.AsyncClient | None = None
        self._client_version_cache: str | None = None
        self._remote_models_cache: dict[str, Any] | None = None
        self._remote_models_cache_at = 0.0

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
        del stream
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict[str, Any]] | None = None
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        model = str(kwargs.get("model") or self.default_model)
        metadata: dict[str, Any] = {"provider": "codex", "model": model}

        async for chunk in self.chat_completion_stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        ):
            if chunk.content:
                content_parts.append(chunk.content)
            if chunk.reasoning_content:
                reasoning_parts.append(chunk.reasoning_content)
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.metadata.get("model"):
                model = str(chunk.metadata["model"])
            metadata.update(chunk.metadata)

        return InferenceResult(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
            finish_reason=finish_reason,
            usage=usage,
            model=model,
            tool_calls=tool_calls,
            metadata=metadata,
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
        del temperature
        payload = self._payload_builder.build_payload(
            messages,
            max_tokens=max_tokens,
            extra=kwargs,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
        )

        try:
            async for chunk in self._stream_payload_with_refresh(payload):
                yield chunk
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(f"Could not connect to Codex at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                f"Timeout streaming from Codex ({self._stream_timeout_label()}, model={payload['model']})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc, "Codex") from exc

    async def health_check(self) -> dict[str, Any]:
        snapshot = self.auth_store.read_status()
        return {
            "status": "healthy" if snapshot.authenticated else "unhealthy",
            "provider": "codex",
            **snapshot.public_dict(),
        }

    async def get_model_info(self) -> dict[str, Any]:
        return await self.list_models()

    async def list_models(
        self,
        *,
        capability: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if not refresh:
            local = self._read_local_models_cache()
            if local:
                return self._filter_models(local, capability)
            if self._remote_models_cache and self._remote_models_cache_fresh():
                return self._filter_models(self._remote_models_cache, capability)

        try:
            models = await self._fetch_models_with_refresh()
            self._remote_models_cache = models
            self._remote_models_cache_at = time.monotonic()
            return self._filter_models(models, capability)
        except LLMBackendError:
            local = self._read_local_models_cache(ignore_ttl=True)
            if local:
                return self._filter_models(local, capability)
            fallback = self._normalize_models_catalog([], source="fallback")
            return self._filter_models(fallback, capability)

    async def logout(self) -> dict[str, Any]:
        ok = await self.auth_store.logout()
        snapshot = self.auth_store.read_status()
        return {"logout_started": ok, **snapshot.public_dict()}

    def auth_status(self) -> dict[str, Any]:
        return self.auth_store.read_status().public_dict()

    def auth_signature(self) -> str:
        return self.auth_store.auth_signature()

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        extra: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        return self._payload_builder.build_payload(
            messages,
            max_tokens=max_tokens,
            extra=extra,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
        )

    async def _stream_payload_with_refresh(self, payload: dict[str, Any]) -> AsyncIterator[StreamChunk]:
        retried = False
        while True:
            try:
                async for chunk in self._stream_payload(payload):
                    yield chunk
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 401 or retried:
                    raise
                retried = True
                await self.auth_store.refresh_via_cli()

    async def _stream_payload(self, payload: dict[str, Any]) -> AsyncIterator[StreamChunk]:
        client = await self._get_client()
        async with client.stream(
            "POST",
            "/responses",
            json=payload,
            headers=self.auth_store.auth_headers(
                accept_stream=True,
                client_version=await self._client_version(),
            ),
            timeout=self._stream_timeout_config(),
        ) as response:
            if response.status_code >= 400:
                await response.aread()
            response.raise_for_status()
            response.encoding = "utf-8"
            async for chunk in self._stream_parser.iter_response_chunks(response, payload["model"]):
                yield chunk

    def _parse_sse_event(
        self,
        event_type: str | None,
        data_str: str,
        fallback_model: str,
    ) -> StreamChunk | None:
        return self._stream_parser.parse_sse_event(event_type, data_str, fallback_model)

    async def _fetch_models_with_refresh(self) -> dict[str, Any]:
        retried = False
        while True:
            try:
                client = await self._get_client()
                version = await self._client_version()
                response = await client.get(
                    "/models",
                    params={"client_version": version},
                    headers=self.auth_store.auth_headers(client_version=version),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                return self._normalize_models_catalog(data, source="remote")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 401 or retried:
                    raise self._http_error(exc, "Codex") from exc
                retried = True
                await self.auth_store.refresh_via_cli()
            except httpx.ConnectError as exc:
                raise LLMBackendConnectionError(f"Could not connect to Codex at {self.base_url}") from exc
            except httpx.TimeoutException as exc:
                raise LLMBackendTimeoutError(f"Timeout calling Codex ({self.timeout}s)") from exc

    def _read_local_models_cache(self, *, ignore_ttl: bool = False) -> dict[str, Any] | None:
        path = self.auth_store.models_cache_path
        if not path.exists():
            return None
        if not ignore_ttl and self.models_cache_ttl_seconds > 0:
            age = time.time() - path.stat().st_mtime
            if age > self.models_cache_ttl_seconds:
                return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return self._normalize_models_catalog(data, source="local_cache")

    def _normalize_models_catalog(self, data: Any, *, source: str) -> dict[str, Any]:
        raw_models = []
        if isinstance(data, dict):
            if isinstance(data.get("models"), list):
                raw_models = data["models"]
            elif isinstance(data.get("data"), list):
                raw_models = data["data"]
        elif isinstance(data, list):
            raw_models = data

        models = [
            normalized
            for item in raw_models
            if isinstance(item, dict)
            for normalized in [self._normalize_model(item, source=source)]
            if normalized is not None
        ]
        self._ensure_core_models(models, source=source)
        return {"object": "list", "provider": "codex", "data": models}

    def _normalize_model(self, item: dict[str, Any], *, source: str) -> dict[str, Any] | None:
        if item.get("supported_in_api") is False:
            return None
        model_id = str(item.get("slug") or item.get("id") or item.get("name") or "").strip()
        if not model_id:
            return None
        label = str(item.get("display_name") or item.get("label") or model_id)
        context_length = self._int_or_default(item.get("context_window"), self.context_window)
        capabilities = ["chat", "streaming", "tools", "reasoning_chat"]
        if item.get("supports_parallel_tool_calls"):
            capabilities.append("parallel_tool_calls")
        if item.get("supports_reasoning_summaries"):
            capabilities.append("reasoning_summaries")
        if item.get("support_verbosity"):
            capabilities.append("verbosity")
        if "vision" in {str(value).lower() for value in item.get("input_modalities") or []}:
            capabilities.append("image_input")

        return {
            "id": model_id,
            "name": label,
            "provider": "codex",
            "label": label,
            "owned_by": "openai",
            "context_length": context_length,
            "capabilities": capabilities,
            "supports_streaming": True,
            "supports_reasoning": True,
            "supports_tools": True,
            "supports_thinking_budget": True,
            "supported_reasoning_levels": item.get("supported_reasoning_levels") or [
                "low",
                "medium",
                "high",
                "xhigh",
            ],
            "raw": {**item, "source": source, "endpoint": f"{self.base_url}/responses"},
        }

    def _ensure_core_models(self, models: list[dict[str, Any]], *, source: str) -> None:
        existing = {str(item.get("id")) for item in models}
        for model_id, label in {
            "gpt-5.4-mini": "GPT-5.4-Mini",
            "gpt-5.5": "GPT-5.5",
        }.items():
            if model_id in existing:
                continue
            models.append(
                self._normalize_model(
                    {
                        "slug": model_id,
                        "display_name": label,
                        "context_window": self.context_window,
                        "supported_in_api": True,
                        "supported_reasoning_levels": ["low", "medium", "high", "xhigh"],
                        "supports_reasoning_summaries": True,
                        "supports_parallel_tool_calls": True,
                    },
                    source=f"{source}_fallback",
                )
            )

    def _filter_models(self, catalog: dict[str, Any], capability: str | None) -> dict[str, Any]:
        if not capability:
            return catalog
        models = [
            item
            for item in catalog.get("data", [])
            if capability in (item.get("capabilities") or [])
        ]
        return {**catalog, "data": models}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def _client_version(self) -> str:
        if self.configured_client_version:
            return self.configured_client_version
        if self._client_version_cache:
            return self._client_version_cache

        cache_path = self.auth_store.models_cache_path
        with suppress(Exception):
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            version = str(data.get("client_version") or "").strip()
            if version:
                self._client_version_cache = version
                return version

        version = await self._codex_cli_version()
        self._client_version_cache = version or FALLBACK_CLIENT_VERSION
        return self._client_version_cache

    async def _codex_cli_version(self) -> str | None:
        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [self.auth_store.codex_cli_path, "--version"],
                check=False,
                text=True,
                capture_output=True,
                timeout=5,
            )

        with suppress(Exception):
            result = await asyncio.to_thread(run)
            match = re.search(r"(\d+\.\d+\.\d+)", result.stdout or result.stderr)
            if match:
                return match.group(1)
        return None

    def _remote_models_cache_fresh(self) -> bool:
        return (
            self.models_cache_ttl_seconds > 0
            and time.monotonic() - self._remote_models_cache_at < self.models_cache_ttl_seconds
        )

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
        return f"{provider} HTTP {exc.response.status_code}: {exc.response.reason_phrase}"

    def _http_error(self, exc: httpx.HTTPStatusError, provider: str) -> LLMBackendError:
        return provider_http_error(
            provider=provider,
            status_code=exc.response.status_code,
            detail=exc.response.text[:500] or exc.response.reason_phrase,
            retry_after=exc.response.headers.get("retry-after"),
        )

    def _safe_error_detail(self, data: dict[str, Any]) -> str:
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "unknown error")[:300]
        if isinstance(error, str):
            return error[:300]
        return str(data.get("type") or "unknown error")

    @staticmethod
    def _int_or_default(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
