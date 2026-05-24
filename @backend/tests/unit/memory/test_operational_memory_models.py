"""Tests for operational memory persistence models."""

from __future__ import annotations

from uuid import uuid4

from personagent.infrastructure.persistence.operational_memory.models import (
    StoredMemoryChunk,
    StoredStructuredMemoryItem,
)


class _FakeChunkORM:
    """Minimal stub matching OperationalMemoryChunkORM shape used in tests."""

    def __init__(self) -> None:
        self.id = uuid4()
        self.content = "fake chunk content"
        self.content_hash = "abc123"
        self.file_path = "/tmp/test.py"
        self.source_type = "tool_result"
        self.created_at = None


class _FakeEventORM:
    """Minimal stub matching OperationalMemoryEventORM shape used in tests."""

    def __init__(self) -> None:
        self.id = uuid4()
        self.event_type = "tool_result"
        self.tool_name = "bash"
        self.error = None
        self.paths = ["/tmp/test.py"]


def test_stored_memory_chunk_defaults() -> None:
    """Score defaults to 0.0."""
    chunk = _FakeChunkORM()
    stored = StoredMemoryChunk(chunk=chunk, event=None, embedding=None)
    assert stored.score == 0.0


def test_stored_memory_chunk_with_embedding() -> None:
    """Embedding is preserved as-is."""
    chunk = _FakeChunkORM()
    embedding = [0.1, 0.2, 0.3]
    stored = StoredMemoryChunk(chunk=chunk, event=None, embedding=embedding)
    assert stored.embedding == embedding


def test_stored_memory_chunk_with_score() -> None:
    """Score is settable at construction."""
    chunk = _FakeChunkORM()
    stored = StoredMemoryChunk(chunk=chunk, event=None, embedding=None, score=0.85)
    assert stored.score == 0.85


def test_stored_structured_item_defaults() -> None:
    """Optional fields default correctly."""
    item_id = uuid4()
    item = StoredStructuredMemoryItem(
        id=item_id,
        project_slug="test-project",
        item_type="file_state",
        summary="A test item",
        evidence=["evidence line 1"],
        paths=["/tmp/test.py"],
        source_ids=[str(uuid4())],
        event_types=["tool_result"],
        status="active",
        source_type="tool_result",
        source_chunk_id=None,
        primary_path="/tmp/test.py",
        conversation_id=None,
        workspace_root="/tmp",
        trust_level="high",
        importance=0.8,
        created_at=None,
    )
    assert item.distance is None
    assert item.lexical_rank == 0.0
    assert item.score == 0.0
    assert item.ranking_reasons is None


def test_stored_structured_item_with_optional_fields() -> None:
    """All optional fields are preserved."""
    item_id = uuid4()
    reasons = ["exact_anchor_match", "term_overlap"]
    item = StoredStructuredMemoryItem(
        id=item_id,
        project_slug="test-project",
        item_type="decision",
        summary="A decision",
        evidence=["evidence"],
        paths=["/tmp/decision.py"],
        source_ids=[str(uuid4())],
        event_types=["decision"],
        status="active",
        source_type="decision",
        source_chunk_id=uuid4(),
        primary_path="/tmp/decision.py",
        conversation_id=uuid4(),
        workspace_root="/tmp",
        trust_level="high",
        importance=0.95,
        created_at=None,
        distance=0.12,
        lexical_rank=0.75,
        score=0.92,
        ranking_reasons=reasons,
    )
    assert item.distance == 0.12
    assert item.lexical_rank == 0.75
    assert item.score == 0.92
    assert item.ranking_reasons == reasons
    assert item.source_chunk_id is not None
    assert item.conversation_id is not None
