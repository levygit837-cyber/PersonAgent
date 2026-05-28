"""Micro-benchmarks for operational memory capture pipeline."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.services.operational_memory.capture import OperationalMemoryCapture
from personagent.domain.memory.models.operational import (
    EmbeddingStatus,
    MemoryChunk,
    MemoryEvent,
    OperationalMemoryEventType,
    RecallFinding,
)
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
    stable_hash,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult

from tests.stress.mock_embedding import MockEmbeddingAdapter


def _make_capture_service(
    embedding_adapter: Any = None,
    embeddings_enabled: bool = True,
) -> tuple[OperationalMemoryCapture, MagicMock]:
    """Build a capture service with mocked repository."""
    repository = MagicMock()
    repository.record_event = AsyncMock()
    repository.record_chunks = AsyncMock(side_effect=lambda chunks: chunks)
    repository.record_structured_items = AsyncMock()
    repository.record_embeddings = AsyncMock()
    repository.mark_chunks_failed = AsyncMock()

    redactor = OperationalMemoryRedactor()
    chunker = OperationalMemoryChunker()
    extractor = MagicMock()
    extractor.structured_items_from_event = MagicMock(return_value=[])

    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(deque)

    service = OperationalMemoryCapture(
        repository=repository,
        redactor=redactor,
        chunker=chunker,
        extractor=extractor,
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embeddings_enabled,
        embedding_model="mock-embed",
        capture_tools_enabled=True,
        max_capture_chars=24_000,
        queue=None,
        queue_enabled=False,
        queue_fallback_sync=True,
        hot_cache=hot_cache,
    )
    return service, repository


@pytest.mark.stress
class TestMemoryCaptureBenchmarks:

    async def test_capture_user_message_small(self, benchmark):
        """100-char user message → event creation + chunking baseline."""
        service, repo = _make_capture_service(embedding_adapter=None, embeddings_enabled=False)

        await benchmark(
            lambda: service.capture_user_message(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id="conv-1",
                message="Hello, this is a short test message for benchmarking purposes.",
            )
        )

    async def test_capture_user_message_large(self, benchmark):
        """10KB user message → measure chunking throughput."""
        service, repo = _make_capture_service(embedding_adapter=None, embeddings_enabled=False)
        message = "x " * 5000

        await benchmark(
            lambda: service.capture_user_message(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id="conv-1",
                message=message,
            )
        )

    async def test_capture_with_mock_embedding(self, benchmark):
        """Capture with mock embedding (50ms simulated) → total latency."""
        mock_embed = MockEmbeddingAdapter(latency_ms=5, dimensions=1024)
        service, repo = _make_capture_service(
            embedding_adapter=mock_embed,
            embeddings_enabled=True,
        )

        await benchmark(
            lambda: service.capture_user_message(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id="conv-1",
                message="Test message with embedding enabled.",
            )
        )

    async def test_capture_tool_result(self, benchmark):
        """Tool result capture → event type detection + paths extraction."""
        service, repo = _make_capture_service(embedding_adapter=None, embeddings_enabled=False)
        call = ToolCall(
            id="call_001",
            name="read_file",
            arguments={"path": "src/main.py"},
        )
        result = ToolResult(
            tool_call_id="call_001",
            tool_name="read_file",
            content="import os\nprint('hello')\n" * 100,
            data={"type": "file_read", "path": "src/main.py"},
        )

        await benchmark(
            lambda: service.capture_tool_result(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id="conv-1",
                call=call,
                result=result,
            )
        )

    async def test_sequential_10_captures(self, benchmark):
        """10 sequential captures → measure pipeline throughput."""
        service, repo = _make_capture_service(embedding_adapter=None, embeddings_enabled=False)

        async def run_10():
            for i in range(10):
                await service.capture_user_message(
                    project_slug="test-project",
                    workspace_root="/tmp/test",
                    conversation_id="conv-1",
                    message=f"Message number {i} with some content to process.",
                )

        await benchmark(run_10)

    async def test_capture_redaction_overhead(self, benchmark):
        """Message with API keys and tokens → measure redaction overhead."""
        service, repo = _make_capture_service(embedding_adapter=None, embeddings_enabled=False)
        message = (
            "Here is my API key: sk-1234567890abcdef1234567890abcdef "
            "and my token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0 "
            "password: SuperSecret123! "
            "Bearer abcdef0123456789 "
        ) * 10

        await benchmark(
            lambda: service.capture_user_message(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id="conv-1",
                message=message,
            )
        )
