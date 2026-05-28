"""Deterministic mock LLM adapter for stress testing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository


class MockLLMAdapter(LLMBackendRepository):
    """Configurable mock LLM for deterministic stress testing.

    Supports tool-call sequences — the adapter emits tool_calls for the first
    N calls matching the sequence length, then emits content for subsequent calls.
    """

    def __init__(
        self,
        *,
        latency_ms: float = 10,
        token_rate: float = 200,
        tool_call_sequence: list[list[dict[str, Any]]] | None = None,
        final_response: str = "Mock response completed.",
        chunk_size_tokens: int = 4,
    ) -> None:
        self.latency_ms = latency_ms
        self.token_rate = token_rate
        self.tool_call_sequence = tool_call_sequence or []
        self.final_response = final_response
        self.chunk_size_tokens = chunk_size_tokens
        self._call_count = 0
        self._total_calls = 0
        self._call_latencies: list[float] = []

    @property
    def call_count(self) -> int:
        return self._total_calls

    @property
    def average_latency_ms(self) -> float:
        if not self._call_latencies:
            return 0.0
        return sum(self._call_latencies) / len(self._call_latencies)

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
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)
        self._total_calls += 1
        elapsed = (time.perf_counter() - start) * 1000
        self._call_latencies.append(elapsed)

        if self._call_count < len(self.tool_call_sequence):
            calls = self.tool_call_sequence[self._call_count]
            self._call_count += 1
            return InferenceResult(
                content="",
                tool_calls=calls,
                finish_reason="tool_calls",
                usage={"prompt_tokens": 100, "completion_tokens": 50},
            )

        return InferenceResult(
            content=self.final_response,
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": len(self.final_response.split())},
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
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)
        self._total_calls += 1

        if self._call_count < len(self.tool_call_sequence):
            calls = self.tool_call_sequence[self._call_count]
            self._call_count += 1
            yield StreamChunk(
                tool_calls=calls,
                finish_reason="tool_calls",
                usage={"prompt_tokens": 100, "completion_tokens": 50},
            )
            elapsed = (time.perf_counter() - start) * 1000
            self._call_latencies.append(elapsed)
            return

        words = self.final_response.split()
        inter_chunk_delay = (self.chunk_size_tokens / self.token_rate) if self.token_rate > 0 else 0

        for i in range(0, len(words), self.chunk_size_tokens):
            chunk_words = words[i: i + self.chunk_size_tokens]
            yield StreamChunk(content=" ".join(chunk_words) + " ")
            if inter_chunk_delay > 0:
                await asyncio.sleep(inter_chunk_delay)

        yield StreamChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": len(words)},
        )
        elapsed = (time.perf_counter() - start) * 1000
        self._call_latencies.append(elapsed)

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "provider": "mock"}

    async def get_model_info(self) -> dict[str, Any]:
        return {"model": "mock-llm", "provider": "mock"}

    def reset(self) -> None:
        """Reset call counter for reuse across tests."""
        self._call_count = 0
        self._total_calls = 0
        self._call_latencies.clear()


def make_tool_call_payload(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    call_id: str | None = None,
) -> dict[str, Any]:
    """Build an OpenAI-format tool_call dict."""
    import json as _json

    return {
        "id": call_id or f"call_{name}_001",
        "type": "function",
        "function": {
            "name": name,
            "arguments": _json.dumps(arguments or {}),
        },
    }
