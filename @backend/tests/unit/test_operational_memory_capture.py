"""Tests for :class:`OperationalMemoryCapture`.

Pins the operational-memory capture surface that was previously
~15 methods on :class:`OperationalMemoryService`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from personagent.application.services.operational_memory.capture import (
    OperationalMemoryCapture,
)
from personagent.domain.memory.models.operational import (
    DecisionMemory,
    DecisionStatus,
    EmbeddingStatus,
    MemoryChunk,
    MemoryEvent,
    OperationalMemoryEventType,
    RecallFinding,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RedactorStub:
    def redact_text(self, text: str | None) -> str:
        return str(text or "")

    def redact_data(self, data: Any) -> Any:
        return data


class _ChunkerStub:
    def __init__(self, chunks: list[MemoryChunk] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._chunks = chunks or []

    def chunk_text(self, **kwargs: Any) -> list[MemoryChunk]:
        self.calls.append(kwargs)
        return self._chunks


class _ExtractorStub:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.calls: list[tuple[MemoryEvent, list[MemoryChunk]]] = []
        self._items = items or []

    def structured_items_from_event(
        self, event: MemoryEvent, chunks: list[MemoryChunk]
    ) -> list[Any]:
        self.calls.append((event, chunks))
        return self._items


class _RepositoryStub:
    def __init__(
        self,
        event: MemoryEvent | None = None,
        chunks: list[MemoryChunk] | None = None,
    ) -> None:
        self.record_event_calls: list[MemoryEvent] = []
        self.record_event_with_outbox_calls: list[dict[str, Any]] = []
        self.mark_outbox_published_calls: list[str] = []
        self.mark_outbox_failed_calls: list[tuple[str, str]] = []
        self.mark_outbox_completed_calls: list[str] = []
        self.record_chunks_calls: list[list[MemoryChunk]] = []
        self.record_embeddings_calls: list[dict[str, Any]] = []
        self.mark_chunks_failed_calls: list[tuple[list[MemoryChunk], str]] = []
        self.record_decision_calls: list[DecisionMemory] = []
        self.record_structured_items_calls: list[list[Any]] = []
        self.get_event_calls: list[str] = []
        self._event = event
        self._chunks = chunks or []

    async def record_event(self, event: MemoryEvent) -> None:
        self.record_event_calls.append(event)

    async def record_event_with_outbox(
        self,
        event: MemoryEvent,
        *,
        job_type: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> tuple[MemoryEvent, dict[str, Any]]:
        self.record_event_with_outbox_calls.append(
            {
                "event": event,
                "job_type": job_type,
                "payload": payload,
                "dedupe_key": dedupe_key,
            }
        )
        return event, {"id": str(uuid4())}

    async def mark_outbox_published(self, outbox_id: str) -> None:
        self.mark_outbox_published_calls.append(outbox_id)

    async def mark_outbox_failed(self, outbox_id: str, error: str) -> None:
        self.mark_outbox_failed_calls.append((outbox_id, error))

    async def mark_outbox_completed(self, outbox_id: str) -> None:
        self.mark_outbox_completed_calls.append(outbox_id)

    async def record_chunks(self, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        self.record_chunks_calls.append(chunks)
        return self._chunks or chunks

    async def record_embeddings(
        self,
        *,
        chunks: list[MemoryChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        self.record_embeddings_calls.append(
            {
                "chunks": chunks,
                "vectors": vectors,
                "embedding_model": embedding_model,
            }
        )

    async def mark_chunks_failed(self, chunks: list[MemoryChunk], error: str) -> None:
        self.mark_chunks_failed_calls.append((chunks, error))

    async def record_decision(self, decision: DecisionMemory) -> None:
        self.record_decision_calls.append(decision)

    async def record_structured_items(self, items: list[Any]) -> None:
        self.record_structured_items_calls.append(items)

    async def get_event(self, event_id: str) -> MemoryEvent | None:
        self.get_event_calls.append(event_id)
        return self._event


class _EmbeddingAdapterStub:
    def __init__(
        self,
        vectors: list[list[float]] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._vectors = vectors
        self._exc = exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self._exc is not None:
            raise self._exc
        return self._vectors or [[0.1] * 10] * len(texts)


class _QueueStub:
    def __init__(self, exc: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._exc = exc

    async def publish(self, outbox: dict[str, Any]) -> None:
        self.calls.append(outbox)
        if self._exc is not None:
            raise self._exc


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


def _capture(
    *,
    repository: _RepositoryStub | None = None,
    redactor: _RedactorStub | None = None,
    chunker: _ChunkerStub | None = None,
    extractor: _ExtractorStub | None = None,
    embedding_adapter: _EmbeddingAdapterStub | None = None,
    embeddings_enabled: bool = True,
    embedding_model: str = "test-model",
    capture_tools_enabled: bool = True,
    max_capture_chars: int = 24_000,
    queue: _QueueStub | None = None,
    queue_enabled: bool = False,
    queue_fallback_sync: bool = True,
    hot_cache: dict[str, deque[RecallFinding]] | None = None,
) -> OperationalMemoryCapture:
    return OperationalMemoryCapture(
        repository=repository or _RepositoryStub(),
        redactor=redactor or _RedactorStub(),
        chunker=chunker or _ChunkerStub(),
        extractor=extractor or _ExtractorStub(),
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embeddings_enabled,
        embedding_model=embedding_model,
        capture_tools_enabled=capture_tools_enabled,
        max_capture_chars=max_capture_chars,
        queue=queue,
        queue_enabled=queue_enabled,
        queue_fallback_sync=queue_fallback_sync,
        hot_cache=hot_cache if hot_cache is not None else {},
    )


# ---------------------------------------------------------------------------
# capture_user_message
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_user_message_records_event_with_correct_type() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)

    await capture.capture_user_message(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        message="hello world",
        metadata={"key": "value"},
    )

    assert len(repo.record_event_calls) == 1
    event = repo.record_event_calls[0]
    assert event.event_type == OperationalMemoryEventType.USER_MESSAGE
    assert event.project_slug == "acme"
    assert event.workspace_root == "/repo"
    assert event.conversation_id == "conv-1"
    assert event.input == {"message": "hello world"}
    assert event.metadata == {"key": "value"}


@pytest.mark.anyio
async def test_capture_user_message_uses_empty_metadata_when_none() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)

    await capture.capture_user_message(
        project_slug="acme",
        workspace_root=None,
        conversation_id="conv-1",
        message="hi",
    )

    assert repo.record_event_calls[0].metadata == {}


# ---------------------------------------------------------------------------
# capture_assistant_message
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_assistant_message_records_event_with_provider_and_model() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)

    await capture.capture_assistant_message(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        content="assistant reply",
        reasoning_content="because",
        provider="openai",
        model="gpt-4",
        finish_reason="stop",
    )

    event = repo.record_event_calls[0]
    assert event.event_type == OperationalMemoryEventType.ASSISTANT_MESSAGE
    assert event.status == "stop"
    assert event.metadata == {"provider": "openai", "model": "gpt-4"}
    assert event.output["content"] == "assistant reply"
    assert event.output["explicit_provider_reasoning"] == "because"


# ---------------------------------------------------------------------------
# capture_tool_result
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_tool_result_skips_when_disabled() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo, capture_tools_enabled=False)
    call = ToolCall(id="tc-1", name="read_file", arguments={"path": "src/app.py"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="read_file",
        content="file content",
        status=ToolExecutionStatus.COMPLETED,
        data={"type": "file_read"},
    )

    await capture.capture_tool_result(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        call=call,
        result=result,
    )

    assert repo.record_event_calls == []


@pytest.mark.anyio
async def test_capture_tool_result_creates_file_read_event() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    call = ToolCall(id="tc-1", name="read_file", arguments={"path": "src/app.py"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="read_file",
        content="file content",
        status=ToolExecutionStatus.COMPLETED,
        data={"type": "file_read"},
    )

    await capture.capture_tool_result(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        call=call,
        result=result,
    )

    event = repo.record_event_calls[0]
    assert event.event_type == OperationalMemoryEventType.FILE_READ
    assert event.tool_name == "read_file"
    assert event.input == {"tool_call_id": "tc-1", "arguments": {"path": "src/app.py"}}


@pytest.mark.anyio
async def test_capture_tool_result_creates_error_event_for_error_result() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    call = ToolCall(id="tc-1", name="shell", arguments={"command": "ls"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="shell",
        content="error output",
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data={},
    )

    await capture.capture_tool_result(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        call=call,
        result=result,
    )

    event = repo.record_event_calls[0]
    assert event.event_type == OperationalMemoryEventType.ERROR_FOUND
    assert event.error == "error output"


@pytest.mark.anyio
async def test_capture_tool_result_uses_context_workspace_when_workspace_root_none() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    call = ToolCall(id="tc-1", name="read_file", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="read_file",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
        data={"type": "file_read"},
    )
    context = ToolUseContext(
        conversation_id="conv-1",
        workspace_root=Path("/context/repo"),
        cwd=Path("/context/repo"),
        allowed_roots=(Path("/context/repo"),),
    )

    await capture.capture_tool_result(
        project_slug="acme",
        workspace_root=None,
        conversation_id="conv-1",
        call=call,
        result=result,
        context=context,
    )

    event = repo.record_event_calls[0]
    assert event.workspace_root == "/context/repo"


@pytest.mark.anyio
async def test_capture_tool_result_records_decision_when_present() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    call = ToolCall(id="tc-1", name="write_file", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="write_file",
        content="decision content",
        status=ToolExecutionStatus.COMPLETED,
        data={"decision": "We made a decision to use Redis"},
    )

    await capture.capture_tool_result(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        call=call,
        result=result,
    )

    assert len(repo.record_decision_calls) == 1
    assert repo.record_decision_calls[0].decision.strip() == "We made a decision to use Redis"
    assert repo.record_decision_calls[0].status == DecisionStatus.ACTIVE


# ---------------------------------------------------------------------------
# capture_turn_summary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_turn_summary_records_operational_summary_event() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)

    await capture.capture_turn_summary(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        summary="turn summary text",
        metadata={"turn": 1},
    )

    event = repo.record_event_calls[0]
    assert event.event_type == OperationalMemoryEventType.OPERATIONAL_SUMMARY
    assert event.output == {"summary": "turn summary text"}
    assert event.metadata == {"turn": 1}


# ---------------------------------------------------------------------------
# _capture_event — direct path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_event_direct_path_records_event_and_indexes() -> None:
    repo = _RepositoryStub()
    chunker = _ChunkerStub(chunks=[_chunk("content")])
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(lambda: deque(maxlen=100))
    capture = _capture(repository=repo, chunker=chunker, hot_cache=hot_cache)
    event = _memory_event()

    await capture._capture_event(event, content="content")

    assert len(repo.record_event_calls) == 1
    assert repo.record_event_calls[0] is event
    assert len(chunker.calls) == 1


# ---------------------------------------------------------------------------
# _capture_event — queue path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_event_queue_path_publishes_and_marks_published() -> None:
    repo = _RepositoryStub()
    queue = _QueueStub()
    capture = _capture(repository=repo, queue=queue, queue_enabled=True)
    event = _memory_event()

    await capture._capture_event(event, content="content")

    assert len(queue.calls) == 1
    assert len(repo.mark_outbox_published_calls) == 1
    assert len(repo.record_event_calls) == 0  # event recorded via outbox


@pytest.mark.anyio
async def test_capture_event_queue_fallback_processes_when_publish_fails() -> None:
    repo = _RepositoryStub()
    chunker = _ChunkerStub(chunks=[_chunk("content")])
    queue = _QueueStub(exc=RuntimeError("queue down"))
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(lambda: deque(maxlen=100))
    capture = _capture(
        repository=repo, chunker=chunker, queue=queue, queue_enabled=True, queue_fallback_sync=True, hot_cache=hot_cache
    )
    event = _memory_event()

    await capture._capture_event(event, content="content")

    assert len(queue.calls) == 1
    assert len(repo.mark_outbox_completed_calls) == 1
    assert len(chunker.calls) == 1  # fallback sync processed indexing


@pytest.mark.anyio
async def test_capture_event_queue_no_fallback_marks_failed() -> None:
    repo = _RepositoryStub()
    queue = _QueueStub(exc=RuntimeError("queue down"))
    capture = _capture(
        repository=repo,
        queue=queue,
        queue_enabled=True,
        queue_fallback_sync=False,
    )
    event = _memory_event()

    await capture._capture_event(event, content="content")

    assert len(repo.mark_outbox_failed_calls) == 1
    assert len(repo.mark_outbox_completed_calls) == 0


@pytest.mark.anyio
async def test_capture_event_swallows_exception_on_total_failure() -> None:
    repo = _RepositoryStub()
    repo.record_event = lambda e: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]
    capture = _capture(repository=repo)
    event = _memory_event()

    await capture._capture_event(event, content="content")  # should not raise

    assert repo.record_event_calls == []  # call failed before appending


# ---------------------------------------------------------------------------
# process_indexing_event (public)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_process_indexing_event_delegates_to_indexing() -> None:
    repo = _RepositoryStub()
    chunker = _ChunkerStub(chunks=[_chunk("indexed")])
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(lambda: deque(maxlen=100))
    capture = _capture(repository=repo, chunker=chunker, hot_cache=hot_cache)
    event = _memory_event()

    await capture.process_indexing_event(event, content="indexed")

    assert len(chunker.calls) == 1
    assert len(repo.record_chunks_calls) == 1


# ---------------------------------------------------------------------------
# _embed_chunks
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_chunks_records_embeddings_when_enabled() -> None:
    adapter = _EmbeddingAdapterStub(vectors=[[0.5] * 10])
    chunk = _chunk("text", embedding_status=EmbeddingStatus.PENDING)
    repo = _RepositoryStub()
    capture = _capture(
        repository=repo, embedding_adapter=adapter, embeddings_enabled=True
    )

    await capture._embed_chunks([chunk])

    assert len(adapter.calls) == 1
    assert adapter.calls[0] == ["text"]
    assert len(repo.record_embeddings_calls) == 1
    assert repo.record_embeddings_calls[0]["embedding_model"] == "test-model"


@pytest.mark.anyio
async def test_embed_chunks_skips_when_embeddings_disabled() -> None:
    adapter = _EmbeddingAdapterStub()
    chunk = _chunk("text", embedding_status=EmbeddingStatus.PENDING)
    capture = _capture(
        embedding_adapter=adapter, embeddings_enabled=False
    )

    await capture._embed_chunks([chunk])

    assert adapter.calls == []


@pytest.mark.anyio
async def test_embed_chunks_skips_when_no_pending_chunks() -> None:
    adapter = _EmbeddingAdapterStub()
    chunk = _chunk("text", embedding_status=EmbeddingStatus.EMBEDDED)
    capture = _capture(
        embedding_adapter=adapter, embeddings_enabled=True
    )

    await capture._embed_chunks([chunk])

    assert adapter.calls == []


@pytest.mark.anyio
async def test_embed_chunks_marks_failed_when_adapter_raises() -> None:
    adapter = _EmbeddingAdapterStub(exc=RuntimeError("timeout"))
    chunk = _chunk("text", embedding_status=EmbeddingStatus.PENDING)
    repo = _RepositoryStub()
    capture = _capture(
        repository=repo, embedding_adapter=adapter, embeddings_enabled=True
    )

    await capture._embed_chunks([chunk])

    assert len(repo.mark_chunks_failed_calls) == 1
    assert repo.mark_chunks_failed_calls[0][1] == "timeout"


# ---------------------------------------------------------------------------
# _safe_record_decision
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_safe_record_decision_records_decision() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    decision = DecisionMemory(project_slug="acme", decision="use redis")

    await capture._safe_record_decision(decision)

    assert len(repo.record_decision_calls) == 1
    assert repo.record_decision_calls[0] is decision


@pytest.mark.anyio
async def test_safe_record_decision_swallows_exception() -> None:
    repo = _RepositoryStub()
    repo.record_decision = lambda d: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]
    capture = _capture(repository=repo)
    decision = DecisionMemory(project_slug="acme", decision="use redis")

    await capture._safe_record_decision(decision)  # should not raise


# ---------------------------------------------------------------------------
# _safe_record_structured_items
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_safe_record_structured_items_records_items() -> None:
    repo = _RepositoryStub()
    extractor = _ExtractorStub(items=[{"type": "fact"}])
    capture = _capture(repository=repo, extractor=extractor)
    event = _memory_event()
    chunks = [_chunk("content")]

    await capture._safe_record_structured_items(event, chunks)

    assert len(extractor.calls) == 1
    assert len(repo.record_structured_items_calls) == 1
    assert repo.record_structured_items_calls[0] == [{"type": "fact"}]


@pytest.mark.anyio
async def test_safe_record_structured_items_swallows_exception() -> None:
    repo = _RepositoryStub()
    extractor = _ExtractorStub(items=[{"type": "fact"}])
    repo.record_structured_items = lambda i: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]
    capture = _capture(repository=repo, extractor=extractor)
    event = _memory_event()
    chunks = [_chunk("content")]

    await capture._safe_record_structured_items(event, chunks)  # should not raise


# ---------------------------------------------------------------------------
# _remember_hot and _remember_hot_event
# ---------------------------------------------------------------------------


def test_remember_hot_adds_finding_to_cache() -> None:
    cache: dict[str, deque[RecallFinding]] = defaultdict(lambda: deque(maxlen=100))
    capture = _capture(hot_cache=cache)
    event = _memory_event(event_type=OperationalMemoryEventType.TOOL_RESULT, tool_name="read_file")
    chunk = _chunk("hot content")

    capture._remember_hot(event, [chunk])

    assert "acme" in cache
    assert len(cache["acme"]) == 1
    finding = cache["acme"][0]
    assert finding.score == 0.25
    assert "read_file" in finding.finding


def test_remember_hot_event_adds_event_finding_to_cache() -> None:
    cache: dict[str, deque[RecallFinding]] = defaultdict(lambda: deque(maxlen=100))
    capture = _capture(hot_cache=cache)
    event = _memory_event(event_type=OperationalMemoryEventType.USER_MESSAGE)

    capture._remember_hot_event(event, "user said hello", file_path=None)

    assert len(cache["acme"]) == 1
    finding = cache["acme"][0]
    assert finding.score == 0.2
    assert "user said hello" in finding.finding


# ---------------------------------------------------------------------------
# _event_type_from_tool_result
# ---------------------------------------------------------------------------


def test_event_type_from_error_result() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="shell", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="shell",
        content="error",
        status=ToolExecutionStatus.ERROR,
        is_error=True,
    )
    assert capture._event_type_from_tool_result(call, result, {}) == OperationalMemoryEventType.ERROR_FOUND


def test_event_type_from_file_read() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="read_file", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="read_file",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "file_read"})
        == OperationalMemoryEventType.FILE_READ
    )


def test_event_type_from_file_write_created() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="write_file", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="write_file",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "file_write", "created": True})
        == OperationalMemoryEventType.FILE_CREATED
    )


def test_event_type_from_shell_test_command() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="shell", arguments={"command": "pytest"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="shell",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "shell", "command": "pytest"})
        == OperationalMemoryEventType.TEST_RESULT
    )


def test_event_type_from_shell_dependency_install() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="shell", arguments={"command": "pip install"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="shell",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "shell", "command": "pip install"})
        == OperationalMemoryEventType.DEPENDENCY_INSTALLED
    )


def test_event_type_from_shell_other_command() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="shell", arguments={"command": "ls"})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="shell",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "shell", "command": "ls"})
        == OperationalMemoryEventType.COMMAND_EXECUTED
    )


def test_event_type_from_task_tool() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="task_list", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="task_list",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {})
        == OperationalMemoryEventType.AGENT_STATE
    )


def test_event_type_defaults_to_tool_result() -> None:
    capture = _capture()
    call = ToolCall(id="tc-1", name="unknown_tool", arguments={})
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="unknown_tool",
        content="content",
        status=ToolExecutionStatus.COMPLETED,
    )
    assert (
        capture._event_type_from_tool_result(call, result, {"type": "something_else"})
        == OperationalMemoryEventType.TOOL_RESULT
    )


# ---------------------------------------------------------------------------
# _paths_from_payload
# ---------------------------------------------------------------------------


def test_paths_from_payload_extracts_path_keys() -> None:
    capture = _capture()
    paths = capture._paths_from_payload({"path": "src/app.py", "file_path": "src/b.py"})
    assert paths == ["src/app.py", "src/b.py"]


def test_paths_from_payload_extracts_nested_paths() -> None:
    capture = _capture()
    paths = capture._paths_from_payload({"nested": {"path": "deep/file.py"}})
    assert "deep/file.py" in paths


def test_paths_from_payload_dedupes() -> None:
    capture = _capture()
    paths = capture._paths_from_payload({"path": "a.py"}, {"path": "a.py"})
    assert paths == ["a.py"]


def test_paths_from_payload_limits_to_20() -> None:
    capture = _capture()
    payloads = [{"path": f"file{i}.py"} for i in range(25)]
    paths = capture._paths_from_payload(*payloads)
    assert len(paths) == 20


# ---------------------------------------------------------------------------
# _decision_from_tool_payload
# ---------------------------------------------------------------------------


def test_decision_from_tool_payload_returns_none_for_irrelevant_text() -> None:
    capture = _capture()
    event = _memory_event()
    assert capture._decision_from_tool_payload("acme", "conv-1", event, {}, "random text") is None


def test_decision_from_tool_payload_returns_active_decision() -> None:
    capture = _capture()
    event = _memory_event()
    decision = capture._decision_from_tool_payload(
        "acme", "conv-1", event, {"decision": "We made a decision to use Postgres"}, ""
    )
    assert decision is not None
    assert decision.status == DecisionStatus.ACTIVE
    assert "Postgres" in decision.decision


def test_decision_from_tool_payload_returns_superseded() -> None:
    capture = _capture()
    event = _memory_event()
    decision = capture._decision_from_tool_payload(
        "acme", "conv-1", event, {"decision": "This was superseded by a new plan"}, ""
    )
    assert decision is not None
    assert decision.status == DecisionStatus.SUPERSEDED


def test_decision_from_tool_payload_returns_rejected() -> None:
    capture = _capture()
    event = _memory_event()
    decision = capture._decision_from_tool_payload(
        "acme", "conv-1", event, {"decision": "This was rejected"}, ""
    )
    assert decision is not None
    assert decision.status == DecisionStatus.REJECTED


# ---------------------------------------------------------------------------
# _looks_like_dependency_install / _looks_like_test_command
# ---------------------------------------------------------------------------


def test_looks_like_dependency_install_detects_pip() -> None:
    capture = _capture()
    assert capture._looks_like_dependency_install("pip install requests") is True
    assert capture._looks_like_dependency_install("pytest") is False


def test_looks_like_test_command_detects_pytest() -> None:
    capture = _capture()
    assert capture._looks_like_test_command("pytest -x") is True
    assert capture._looks_like_test_command("pip install") is False


# ---------------------------------------------------------------------------
# _compact_json
# ---------------------------------------------------------------------------


def test_compact_json_serializes_dict() -> None:
    capture = _capture()
    result = capture._compact_json({"b": 2, "a": 1})
    assert result == '{"a": 1, "b": 2}'


def test_compact_json_falls_back_to_str() -> None:
    capture = _capture()
    result = capture._compact_json(object())  # not JSON-serializable
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _strip_null_bytes
# ---------------------------------------------------------------------------


def test_strip_null_bytes_removes_from_strings() -> None:
    capture = _capture()
    assert capture._strip_null_bytes("hello\x00world") == "helloworld"


def test_strip_null_bytes_walks_dicts_and_lists() -> None:
    capture = _capture()
    payload = {
        "text": "hello\x00world",
        "nested": {"deep": "a\x00b"},
        "list": ["x\x00y", {"z": "z\x00z"}],
        "int": 42,
    }
    result = capture._strip_null_bytes(payload)
    assert result["text"] == "helloworld"
    assert result["nested"]["deep"] == "ab"
    assert result["list"] == ["xy", {"z": "zz"}]
    assert result["int"] == 42


@pytest.mark.anyio
async def test_capture_event_strips_null_bytes_before_insert() -> None:
    repo = _RepositoryStub()
    capture = _capture(repository=repo)
    event = _memory_event()
    event.input = {"message": "hello\x00world"}
    event.output = {"content": "a\x00b"}
    event.error = "err\x00or"

    await capture._capture_event(event, content="body\x00text")

    recorded = repo.record_event_calls[0]
    assert recorded.input["message"] == "helloworld"
    assert recorded.output["content"] == "ab"
    assert recorded.error == "error"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_event(
    *,
    event_type: OperationalMemoryEventType = OperationalMemoryEventType.TOOL_RESULT,
    tool_name: str | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        project_slug="acme",
        workspace_root="/repo",
        conversation_id="conv-1",
        event_type=event_type,
        tool_name=tool_name,
    )


def _chunk(content: str = "content", embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING) -> MemoryChunk:
    return MemoryChunk(
        project_slug="acme",
        source_type="tool_result",
        source_id="src-1",
        content=content,
        embedding_status=embedding_status,
    )
