"""Tests for :class:`OperationalMemoryExtractor`.

Pins the structured-memory extraction surface that was previously
five private methods on :class:`OperationalMemoryService`.
"""

from __future__ import annotations

from uuid import uuid4

from personagent.application.services.operational_memory.extraction import (
    OperationalMemoryExtractor,
    _compact_text,
    _importance_from_event,
    _structured_status_from_event,
    _structured_summary,
    _structured_type_from_event,
    _trust_level_from_event,
)
from personagent.domain.memory.models.operational import (
    MemoryChunk,
    MemoryEvent,
    MemoryItemStatus,
    OperationalMemoryEventType,
    StructuredMemoryType,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _event(
    *,
    event_type: OperationalMemoryEventType = OperationalMemoryEventType.TOOL_RESULT,
    paths: list[str] | None = None,
    status: str | None = None,
    error: str | None = None,
    resolution: str | None = None,
    task: str | None = None,
    metadata: dict | None = None,
    tool_name: str | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        project_slug="test",
        workspace_root="/tmp/test",
        conversation_id=str(uuid4()),
        event_type=event_type,
        tool_name=tool_name,
        status=status,
        error=error,
        resolution=resolution,
        task=task,
        paths=paths or [],
        metadata=metadata or {},
        source_hash="abc",
    )


def _chunk(content: str = "some content", file_path: str | None = None) -> MemoryChunk:
    return MemoryChunk(
        project_slug="test",
        source_type="tool_result",
        source_id="ev-1",
        content=content,
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# OperationalMemoryExtractor.structured_items_from_event
# ---------------------------------------------------------------------------


def test_extractor_returns_empty_list_for_empty_chunks() -> None:
    extractor = OperationalMemoryExtractor()
    assert extractor.structured_items_from_event(_event(), []) == []


def test_extractor_skips_chunks_with_empty_compact_text() -> None:
    extractor = OperationalMemoryExtractor()
    items = extractor.structured_items_from_event(
        _event(),
        [_chunk(content="   \n\t  "), _chunk(content="valid")],
    )
    assert len(items) == 1
    assert items[0].summary.endswith("valid")


def test_extractor_preserves_event_paths_and_dedupes() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(paths=["a.py", "b.py", "a.py"])
    items = extractor.structured_items_from_event(
        event,
        [_chunk(file_path="a.py")],
    )
    assert items[0].paths == ["a.py", "b.py"]


def test_extractor_sets_is_latest_for_decision_events() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.DECISION)
    items = extractor.structured_items_from_event(event, [_chunk()])
    assert items[0].metadata["is_latest"] is True


def test_extractor_sets_is_latest_for_agent_state_events() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.AGENT_STATE)
    items = extractor.structured_items_from_event(event, [_chunk()])
    assert items[0].metadata["is_latest"] is True


def test_extractor_sets_is_latest_for_file_state_events() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.FILE_EDITED)
    items = extractor.structured_items_from_event(event, [_chunk()])
    assert items[0].metadata["is_latest"] is True


def test_extractor_sets_is_latest_false_for_fact_events() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.TOOL_RESULT)
    items = extractor.structured_items_from_event(event, [_chunk()])
    assert items[0].metadata["is_latest"] is False


def test_extractor_evidence_is_truncated() -> None:
    extractor = OperationalMemoryExtractor()
    long_content = "word " * 200
    items = extractor.structured_items_from_event(
        _event(),
        [_chunk(content=long_content)],
    )
    evidence = items[0].evidence[0]
    assert len(evidence) < len(long_content)
    assert evidence.startswith("word word")


def test_extractor_includes_tool_name_in_summary() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.TOOL_RESULT, tool_name="read_file")
    items = extractor.structured_items_from_event(event, [_chunk(content="hello")])
    assert "via read_file" in items[0].summary


def test_extractor_includes_path_in_summary() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.FILE_READ)
    items = extractor.structured_items_from_event(
        event,
        [_chunk(content="hello", file_path="src/app.py")],
    )
    assert "in src/app.py" in items[0].summary


def test_extractor_produces_stable_content_hash() -> None:
    """The same inputs must yield the same content_hash."""
    extractor = OperationalMemoryExtractor()
    event = _event(event_type=OperationalMemoryEventType.DECISION)
    chunk = _chunk(content="decision text")
    items_a = extractor.structured_items_from_event(event, [chunk])
    items_b = extractor.structured_items_from_event(event, [chunk])
    assert items_a[0].metadata["content_hash"] == items_b[0].metadata["content_hash"]


def test_extractor_metadata_includes_tenant_fields() -> None:
    extractor = OperationalMemoryExtractor()
    event = _event()
    items = extractor.structured_items_from_event(event, [_chunk()])
    meta = items[0].metadata
    assert meta["project_slug"] == "test"
    assert meta["workspace_root"] == "/tmp/test"
    assert meta["source_type"] == "tool_result"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_structured_type_from_event_mappings() -> None:
    assert _structured_type_from_event(OperationalMemoryEventType.OPERATIONAL_SUMMARY) == StructuredMemoryType.SESSION_SUMMARY
    assert _structured_type_from_event(OperationalMemoryEventType.DECISION) == StructuredMemoryType.DECISION
    assert _structured_type_from_event(OperationalMemoryEventType.AGENT_STATE) == StructuredMemoryType.LATEST_STATE
    assert _structured_type_from_event(OperationalMemoryEventType.ERROR_FOUND) == StructuredMemoryType.ERROR_SOLUTION
    assert _structured_type_from_event(OperationalMemoryEventType.FILE_CREATED) == StructuredMemoryType.FILE_STATE
    assert _structured_type_from_event(OperationalMemoryEventType.COMMAND_EXECUTED) == StructuredMemoryType.COMMAND_RESULT
    assert _structured_type_from_event(OperationalMemoryEventType.TEST_RESULT) == StructuredMemoryType.TEST_RESULT
    assert _structured_type_from_event(OperationalMemoryEventType.TOOL_CALL) == StructuredMemoryType.TOOL_TRACE
    assert _structured_type_from_event(OperationalMemoryEventType.USER_MESSAGE) == StructuredMemoryType.FACT


def test_structured_status_from_event_detects_superseded() -> None:
    event = _event(status="this was superseded by another")
    assert _structured_status_from_event(event) == MemoryItemStatus.SUPERSEDED


def test_structured_status_from_event_detects_rejected() -> None:
    event = _event(error="rejected by user")
    assert _structured_status_from_event(event) == MemoryItemStatus.REJECTED


def test_structured_status_from_event_detects_stale() -> None:
    event = _event(resolution="stale data")
    assert _structured_status_from_event(event) == MemoryItemStatus.STALE


def test_structured_status_from_event_defaults_to_active() -> None:
    event = _event()
    assert _structured_status_from_event(event) == MemoryItemStatus.ACTIVE


def test_trust_level_user_message_is_low() -> None:
    assert _trust_level_from_event(_event(event_type=OperationalMemoryEventType.USER_MESSAGE)) == "low"
    assert _trust_level_from_event(_event(event_type=OperationalMemoryEventType.ASSISTANT_MESSAGE)) == "low"


def test_trust_level_tool_result_is_medium() -> None:
    assert _trust_level_from_event(_event(event_type=OperationalMemoryEventType.TOOL_RESULT)) == "medium"
    assert _trust_level_from_event(_event(event_type=OperationalMemoryEventType.FILE_READ)) == "medium"


def test_trust_level_decision_is_high() -> None:
    assert _trust_level_from_event(_event(event_type=OperationalMemoryEventType.DECISION)) == "high"


def test_importance_decision_is_highest() -> None:
    assert _importance_from_event(_event(event_type=OperationalMemoryEventType.DECISION)) == 0.95


def test_importance_user_message_is_lowest() -> None:
    assert _importance_from_event(_event(event_type=OperationalMemoryEventType.USER_MESSAGE)) == 0.2


def test_compact_text_under_limit_preserved() -> None:
    text = "short text"
    assert _compact_text(text, limit=100) == text


def test_compact_text_over_limit_truncates() -> None:
    text = "a" * 1_000
    result = _compact_text(text, limit=100)
    assert "..." in result
    assert len(result) < len(text)


def test_structured_summary_includes_label_and_path() -> None:
    event = _event(event_type=OperationalMemoryEventType.FILE_EDITED, tool_name="edit_file")
    summary = _structured_summary(
        item_type=StructuredMemoryType.FILE_STATE,
        event=event,
        path="src/app.py",
        text="changed route",
    )
    assert summary.startswith("File state from file edited via edit_file in src/app.py:")
    assert "changed route" in summary
