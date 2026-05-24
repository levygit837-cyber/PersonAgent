"""Google Vertex AI native Gemini adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

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
from personagent.infrastructure.llm.vertex_ai.content_builder import VertexContentBuilder
from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    GOOGLE_CLOUD_SCOPE,
    VERTEX_MODELS,
    VertexModelSpec,
)
from personagent.infrastructure.llm.vertex_ai.streaming import VertexStreamingHandler

logger = structlog.get_logger(__name__)


class VertexAiAdapter(LLMBackendRepository):  # type: ignore[misc]
    """Adapter nativo para Gemini no Vertex AI."""

    def __init__(
        self,
        *,
        api_key: str = "",
        auth_mode: str = "auto",
        project_id: str = "",
        location: str = "global",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        stream_read_timeout: float | None = 0.0,
        default_model: str = "gemini-3.1-flash-lite-preview",
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        models_cache_ttl_seconds: int = 300,
    ) -> None:
        self.api_key = api_key.strip()
        self.auth_mode = auth_mode.strip().lower() or "auto"
        self.project_id = project_id.strip()
        self.location = location.strip() or "global"
        self.timeout = timeout
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self.models_cache_ttl_seconds = models_cache_ttl_seconds
        self._client: httpx.AsyncClient | None = None
        self._adc_token: str | None = None
        self._adc_token_expiry: datetime | None = None
        self._adc_project_id: str | None = None
        self._models_cache: dict[str, Any] | None = None
        self._models_cache_at = 0.0
        self._content_builder = VertexContentBuilder(
            default_model=self.default_model,
            default_max_tokens=self.default_max_tokens,
        )
        self._streaming = VertexStreamingHandler(
            timeout=self.timeout,
            stream_read_timeout=stream_read_timeout,
            auth_mode=self.auth_mode,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url(),
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
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
        payload, model = self._content_builder.build_payload(
            messages,
            temperature,
            max_tokens,
            kwargs,
            tools=tools,
        )

        try:
            client = await self._get_client()
            response = await client.post(
                self._request_path(model, stream=False),
                params=await self._request_params(),
                headers=await self._request_headers(),
                json=payload,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(
                f"Could not connect to Vertex AI at {self._base_url()}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(f"Timeout calling Vertex AI ({self.timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc

        return self._streaming.parse_inference_result(response.json(), model)

    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        payload, model = self._content_builder.build_payload(
            messages,
            temperature,
            max_tokens,
            kwargs,
            tools=tools,
        )
        thought_signatures: list[str] = []

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                self._request_path(model, stream=True),
                params=await self._request_params(),
                headers={
                    **(await self._request_headers()),
                    "Accept": "text/event-stream",
                },
                json=payload,
                timeout=self._streaming.stream_timeout_config(),
            ) as response:
                response.raise_for_status()
                response.encoding = "utf-8"

                async for event in self._streaming.stream_events(response):
                    if event == "[DONE]":
                        yield StreamChunk(
                            finish_reason="stop",
                            metadata=self._streaming.metadata(model, thought_signatures),
                        )
                        break

                    data = event

                    if data.get("error"):
                        raise LLMBackendError(f"Vertex AI stream error: {data['error']}")

                    chunks, signatures = self._streaming.stream_chunks_from_data(data, model)
                    thought_signatures.extend(signatures)
                    for chunk in chunks:
                        yield chunk

        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(
                f"Could not connect to Vertex AI at {self._base_url()}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                "Timeout streaming from Vertex AI "
                f"({self._streaming.stream_timeout_label()}, model={model})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            with suppress(Exception):
                await exc.response.aread()
            raise self._http_error(exc) from exc

    async def health_check(self) -> dict[str, Any]:
        try:
            strategy = self._auth_strategy()
            if strategy == "adc":
                await self._adc_access_token()
            return {
                "status": "healthy",
                "provider": "vertex",
                "auth_mode": strategy,
                "location": self.location,
            }
        except Exception as exc:
            return {"status": "unhealthy", "provider": "vertex", "error": str(exc)}

    async def get_model_info(self) -> dict[str, Any]:
        return await self.list_models()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def list_models(
        self,
        *,
        capability: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not refresh
            and self._models_cache is not None
            and now - self._models_cache_at < self.models_cache_ttl_seconds
        ):
            return self._filter_model_response(self._models_cache, capability)

        response = {
            "object": "list",
            "provider": "vertex",
            "data": [self._model_to_catalog_item(model) for model in VERTEX_MODELS],
        }
        self._models_cache = response
        self._models_cache_at = now
        return self._filter_model_response(response, capability)

    def _model_to_catalog_item(self, model: VertexModelSpec) -> dict[str, Any]:
        capabilities = ["chat", "image_input"]
        if model.supports_thinking:
            capabilities.append("thinking")
        if model.image_output:
            capabilities.extend(["image_output", "image_generation"])
        if model.supports_tools:
            capabilities.append("tools")
        if model.supports_code_execution:
            capabilities.append("code_execution")
        if model.supports_context_cache:
            capabilities.append("context_cache")

        return {
            "id": model.id,
            "provider": "vertex",
            "label": model.label,
            "owned_by": "google",
            "context_length": model.input_tokens,
            "max_output_tokens": model.output_tokens,
            "capabilities": capabilities,
            "supports_streaming": True,
            "supports_reasoning": model.supports_thinking,
            "supports_image_output": model.image_output,
            "supports_tools": model.supports_tools,
            "launch_stage": model.launch_stage,
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
            "provider": "vertex",
            "data": models,
        }

    def _request_path(self, model: str, *, stream: bool) -> str:
        suffix = "streamGenerateContent" if stream else "generateContent"
        model_path = quote(model, safe="")
        if self._auth_strategy() == "adc":
            project_id = quote(self._resolved_project_id(), safe="")
            location = quote(self.location, safe="")
            return (
                f"/projects/{project_id}/locations/{location}/publishers/google/"
                f"models/{model_path}:{suffix}"
            )
        return f"/publishers/google/models/{model_path}:{suffix}"

    async def _request_params(self) -> dict[str, str]:
        if self._auth_strategy() == "api_key":
            return {"key": self.api_key}
        return {}

    async def _request_headers(self) -> dict[str, str]:
        if self._auth_strategy() != "adc":
            return {}
        return {"Authorization": f"Bearer {await self._adc_access_token()}"}

    async def _adc_access_token(self) -> str:
        if (
            self._adc_token
            and self._adc_token_expiry
            and self._adc_token_expiry > datetime.now(UTC)
        ):
            return self._adc_token

        token, expiry, project = await asyncio.to_thread(self._load_adc_token)
        self._adc_token = token
        self._adc_token_expiry = _ensure_aware_datetime(expiry)
        self._adc_project_id = project
        return token

    def _load_adc_token(self) -> tuple[str, datetime | None, str | None]:
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise LLMBackendConnectionError(
                "google-auth is required for Vertex AI ADC mode"
            ) from exc

        credentials, project = google.auth.default(scopes=[GOOGLE_CLOUD_SCOPE])
        credentials.refresh(Request())
        token = getattr(credentials, "token", None)
        if not token:
            raise LLMBackendConnectionError("Vertex AI ADC did not return an access token")
        return token, getattr(credentials, "expiry", None), project

    def _resolved_project_id(self) -> str:
        project = self.project_id or self._adc_project_id or ""
        if not project:
            raise LLMBackendConnectionError(
                "VERTEX_PROJECT_ID is required when using Vertex AI ADC mode"
            )
        return project

    def _base_url(self) -> str:
        if self._auth_strategy() == "adc" and self.location != "global":
            return f"https://{self.location}-aiplatform.googleapis.com/v1"
        return "https://aiplatform.googleapis.com/v1"

    def _auth_strategy(self) -> str:
        if self.auth_mode in {"api_key", "apikey", "key", "express"}:
            if not self.api_key:
                raise LLMBackendConnectionError("GOOGLE_API_KEY is not configured")
            return "api_key"
        if self.auth_mode in {"adc", "application_default_credentials"}:
            return "adc"
        if self.auth_mode == "auto":
            return "api_key" if self.api_key else "adc"
        raise LLMBackendConnectionError(
            "VERTEX_AUTH_MODE must be auto, api_key, express, or adc"
        )

    def _http_error(self, exc: httpx.HTTPStatusError) -> LLMBackendError:
        detail = exc.response.reason_phrase
        with suppress(ValueError, TypeError, httpx.ResponseNotRead):
            body = exc.response.json()
            detail = _error_message_from_body(body, detail)
        return provider_http_error(
            provider="Vertex AI",
            status_code=exc.response.status_code,
            detail=detail,
            retry_after=exc.response.headers.get("retry-after"),
        )


def _error_message_from_body(body: Any, fallback: str) -> str:
    if isinstance(body, list):
        for item in body:
            detail = _error_message_from_body(item, "")
            if detail:
                return detail
        return fallback
    if not isinstance(body, dict):
        return fallback
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or fallback)
    detail = body.get("detail")
    if detail:
        return str(detail)
    return fallback


def _ensure_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
