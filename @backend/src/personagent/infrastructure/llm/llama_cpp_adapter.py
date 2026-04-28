"""Adapter for llama-server communication through an OpenAI-compatible API."""

import json
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


class LlamaCppAdapter(LLMBackendRepository):  # type: ignore[misc]
    """
    Adapter que se comunica com o llama-server local via API OpenAI-compatible.
    Suporta streaming com parsing de reasoning_content (think tokens).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080/v1",
        api_key: str = "local",
        timeout: float = 120.0,
        stream_read_timeout: float = 0.0,
        default_max_tokens: int = 65536,
        reasoning: str = "off",
        reasoning_budget: int = 2048,
        ctx_size: int = 131072,
    ):
        self.base_url = base_url.rstrip("/")
        self.ctx_size = ctx_size
        self.timeout = timeout
        self.stream_read_timeout = stream_read_timeout
        self.default_max_tokens = default_max_tokens
        self.reasoning = reasoning.lower()
        self.reasoning_budget = reasoning_budget
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        self._client: httpx.AsyncClient | None = None

    def _get_timeout(self) -> httpx.Timeout:
        """Monta o timeout do httpx respeitando stream_read_timeout."""
        if self.stream_read_timeout and self.stream_read_timeout > 0:
            return httpx.Timeout(self.timeout, read=self.stream_read_timeout)
        return httpx.Timeout(self.timeout)

    async def _get_client(self) -> httpx.AsyncClient:
        """Return or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self._get_timeout(),
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
        """Execute a synchronous completion."""
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
                f"Could not connect to llama-server at {self.base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(
                f"Timeout while requesting llama-server ({self.timeout}s)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMBackendError(
                f"Erro HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        data = response.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        content, reasoning_content = normalize_message_content(message)

        return InferenceResult(
            content=content,
            reasoning_content=reasoning_content,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            model=data.get("model"),
            tool_calls=message.get("tool_calls"),
            metadata={"provider": "llama"},
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
        """Execute a streaming completion."""
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
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                response.encoding = "utf-8"

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Remove "data: "
                    if data_str == "[DONE]":
                        yield StreamChunk(finish_reason="stop")
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    chunk = self._parse_stream_chunk(
                        data,
                        tool_call_parts,
                        thinking_state,
                    )
                    if not chunk.is_empty:
                        yield chunk

                    if chunk.is_finished:
                        break

        except httpx.ConnectError as exc:
            raise LLMBackendConnectionError(
                f"Could not connect to llama-server at {self.base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMBackendTimeoutError(f"Timeout no streaming ({self.timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMBackendError(
                f"Erro HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

    async def health_check(self) -> dict[str, Any]:
        """Check whether llama-server is responding."""
        try:
            client = await self._get_client()
            response = await client.get("/health", timeout=5.0)
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "details": response.text if response.text else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
            }

    async def get_model_info(self) -> dict[str, Any]:
        """Return information about the loaded model."""
        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {}
            # Injeta context_length real do servidor nos modelos
            for model in data.get("data", []):
                if isinstance(model, dict) and "context_length" not in model:
                    model["context_length"] = self.ctx_size
            return data
        except Exception as exc:
            logger.warning("model_info_failed", error=str(exc))
            return {}

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
        """Build the payload for the llama-server API."""
        model = extra.get("model", "local-model")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        effective_max_tokens = max_tokens if max_tokens > 0 else self.default_max_tokens
        # Clamp para evitar valores absurdos vindos do frontend em modelo local
        if effective_max_tokens > self.default_max_tokens:
            logger.warning(
                "max_tokens_clamped",
                requested=effective_max_tokens,
                clamped=self.default_max_tokens,
            )
            effective_max_tokens = self.default_max_tokens
        if effective_max_tokens > 0:
            payload["max_tokens"] = effective_max_tokens

        chat_template_kwargs = dict(extra.get("chat_template_kwargs") or {})
        request_reasoning_budget = extra.get("reasoning_budget_tokens")
        request_reasoning_level = extra.get("reasoning_level")

        # Mapeia reasoning_level para budget se necessário
        if request_reasoning_budget is None and request_reasoning_level is not None:
            level_to_budget = {
                "low": 2048,
                "medium": 4082,
                "high": 8192,
                "xhigh": 16382,
                "max": 32768,
            }
            level = str(request_reasoning_level).strip().lower()
            request_reasoning_budget = level_to_budget.get(level)

        if request_reasoning_budget is not None:
            chat_template_kwargs["enable_thinking"] = True
            payload["thinking_budget_tokens"] = int(request_reasoning_budget)
        elif self.reasoning == "off":
            chat_template_kwargs["enable_thinking"] = False
        elif self.reasoning_budget >= 0:
            payload["thinking_budget_tokens"] = self.reasoning_budget
        if chat_template_kwargs:
            payload["chat_template_kwargs"] = chat_template_kwargs

        if extra.get("top_p"):
            payload["top_p"] = extra["top_p"]
        if extra.get("top_k"):
            payload["top_k"] = extra["top_k"]
        if extra.get("stop"):
            payload["stop"] = extra["stop"]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        return payload

    def _parse_stream_chunk(
        self,
        data: dict[str, Any],
        tool_call_parts: dict[int, dict[str, Any]] | None = None,
        thinking_state: ThinkingTagState | None = None,
    ) -> StreamChunk:
        """Parseia um chunk de stream da API."""
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

        return StreamChunk(
            content=content,
            reasoning_content=reasoning,
            finish_reason=finish_reason,
            usage=data.get("usage"),
            tool_calls=tool_calls,
            is_thinking=bool(reasoning and not content),
            metadata={"model": data["model"]} if data.get("model") else {},
        )

    def _accumulate_tool_call_delta(
        self,
        deltas: list[dict[str, Any]],
        accumulator: dict[int, dict[str, Any]],
    ) -> None:
        """Acumula deltas streaming de tool_calls OpenAI-compatible."""
        accumulate_tool_call_delta(deltas, accumulator)

    def _finalize_tool_calls(self, accumulator: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        """Finalize accumulated tool_calls in index order."""
        return [
            {
                "id": item.get("id") or f"call_{index}",
                "type": item.get("type") or "function",
                "function": item.get("function") or {},
            }
            for index, item in sorted(accumulator.items())
        ]

    async def close(self) -> None:
        """Fecha o cliente HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
