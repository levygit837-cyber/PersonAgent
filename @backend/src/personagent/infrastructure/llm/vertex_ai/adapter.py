"""Google Vertex AI native Gemini adapter."""

from __future__ import annotations

import asyncio
import json
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
from personagent.domain.models.inference_result import GeneratedImage, InferenceResult, StreamChunk
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.llm.vertex_ai.content_builder import VertexContentBuilder
from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STREAM_POOL_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    GOOGLE_CLOUD_SCOPE,
    VERTEX_MODELS,
    VertexModelSpec,
)

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
        self.stream_read_timeout = self._normalize_stream_read_timeout(stream_read_timeout)
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

        return self._parse_inference_result(response.json(), model)

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
                timeout=self._stream_timeout_config(),
            ) as response:
                response.raise_for_status()
                response.encoding = "utf-8"

                async for event in self._stream_events(response):
                    if event == "[DONE]":
                        yield StreamChunk(
                            finish_reason="stop",
                            metadata=self._metadata(model, thought_signatures),
                        )
                        break

                    data = event

                    if data.get("error"):
                        raise LLMBackendError(f"Vertex AI stream error: {data['error']}")

                    chunks, signatures = self._stream_chunks_from_data(data, model)
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
                f"({self._stream_timeout_label()}, model={model})"
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

    def _parse_inference_result(self, data: dict[str, Any], fallback_model: str) -> InferenceResult:
        parsed = self._parse_candidate_data(data, fallback_model)
        return InferenceResult(
            content=parsed["content"],
            reasoning_content=parsed["reasoning"],
            finish_reason=parsed["finish_reason"],
            usage=parsed["usage"],
            model=parsed["model"],
            tool_calls=parsed["tool_calls"] or None,
            images=parsed["images"],
            metadata=self._metadata(parsed["model"], parsed["thought_signatures"]),
        )

    def _stream_chunks_from_data(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> tuple[list[StreamChunk], list[str]]:
        candidate = _first_candidate(data)
        if not candidate:
            return [], []

        model = str(data.get("modelVersion") or data.get("model") or fallback_model)
        metadata = self._metadata(model)
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
                        metadata=self._metadata(model, [signature] if signature else None),
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
                    metadata=self._metadata(model, thought_signatures),
                )
            )

        return chunks, thought_signatures

    def _parse_candidate_data(self, data: dict[str, Any], fallback_model: str) -> dict[str, Any]:
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

    def _metadata(
        self,
        model: str,
        thought_signatures: list[str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": "vertex",
            "model": model,
            "vertex_auth_mode": self._auth_strategy(),
        }
        if thought_signatures:
            metadata["vertex_thought_signatures"] = [
                signature for signature in thought_signatures if signature
            ]
        return metadata

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

    def _stream_timeout_config(self) -> httpx.Timeout:
        bounded_timeout = max(float(self.timeout), 1.0)
        return httpx.Timeout(
            timeout=None,
            connect=min(DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS, bounded_timeout),
            read=self.stream_read_timeout,
            write=bounded_timeout,
            pool=min(DEFAULT_STREAM_POOL_TIMEOUT_SECONDS, bounded_timeout),
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

    def _stream_data_from_line(self, line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        if stripped.startswith("data: "):
            return stripped[6:]
        if stripped.startswith("{"):
            return stripped
        return ""

    async def _stream_events(self, response: httpx.Response) -> AsyncIterator[dict[str, Any] | str]:
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

    async def _json_stream_objects(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
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


def _ensure_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
