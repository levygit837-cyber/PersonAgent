"""Tests for EventOutboxManager pure helpers.

Tests the module-level functions extracted from OperationalMemoryRepository.
Class methods are exercised by the existing integration test suite.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from personagent.domain.memory.models.operational import (
    MemoryEvent,
    OperationalMemoryEventType,
)
from personagent.infrastructure.persistence.operational_memory.event_outbox import (
    _event_from_row,
    _event_row,
    _outbox_payload,
    _uuid_or_none,
)

# ---------------------------------------------------------------------------
# _uuid_or_none
# ---------------------------------------------------------------------------


def test_uuid_or_none_returns_uuid_unchanged() -> None:
    uid = uuid4()
    assert _uuid_or_none(uid) is uid


def test_uuid_or_none_parses_valid_string() -> None:
    uid = uuid4()
    result = _uuid_or_none(str(uid))
    assert result == uid


def test_uuid_or_none_returns_none_for_none() -> None:
    assert _uuid_or_none(None) is None


def test_uuid_or_none_returns_none_for_invalid_string() -> None:
    assert _uuid_or_none("not-a-uuid") is None


def test_uuid_or_none_returns_none_for_empty_string() -> None:
    assert _uuid_or_none("") is None


# ---------------------------------------------------------------------------
# _event_row
# ---------------------------------------------------------------------------


def _make_event(**overrides: object) -> MemoryEvent:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "project_slug": "test-project",
        "workspace_root": "/tmp/test",
        "session_id": "session-1",
        "conversation_id": str(uuid4()),
        "agent_name": "test-agent",
        "event_type": OperationalMemoryEventType.TOOL_RESULT,
        "task": "run tests",
        "tool_name": "pytest",
        "status": "success",
        "input": {"cmd": "pytest"},
        "output": {"result": "ok"},
        "error": None,
        "resolution": None,
        "paths": ["/tmp/test.py"],
        "metadata": {"key": "value"},
        "source_hash": "abc123",
        "created_at": None,
    }
    defaults.update(overrides)
    return MemoryEvent(**{k: v for k, v in defaults.items() if v is not ...})  # type: ignore[arg-type]


def test_event_row_basic_mapping() -> None:
    event = _make_event()
    row = _event_row(event)
    assert row.id == event.id
    assert row.project_slug == event.project_slug
    assert row.event_type == event.event_type.value
    assert row.tool_name == event.tool_name


def test_event_row_converts_conversation_id_to_uuid() -> None:
    cid = uuid4()
    event = _make_event(conversation_id=str(cid))
    row = _event_row(event)
    assert row.conversation_id == cid


def test_event_row_none_conversation_id() -> None:
    event = _make_event(conversation_id=None)
    row = _event_row(event)
    assert row.conversation_id is None


def test_event_row_preserves_input_output() -> None:
    event = _make_event(input={"cmd": "ls"}, output={"files": 3})
    row = _event_row(event)
    assert row.input == {"cmd": "ls"}
    assert row.output == {"files": 3}


def test_event_row_metadata_stored_as_metadata_() -> None:
    event = _make_event(metadata={"source": "test"})
    row = _event_row(event)
    assert row.metadata_ == {"source": "test"}


def test_event_row_source_hash_preserved() -> None:
    event = _make_event(source_hash="deadbeef")
    row = _event_row(event)
    assert row.source_hash == "deadbeef"


# ---------------------------------------------------------------------------
# _event_from_row
# ---------------------------------------------------------------------------


def _make_event_orm_row(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "project_slug": "test-project",
        "workspace_root": "/tmp/test",
        "session_id": "session-1",
        "conversation_id": uuid4(),
        "agent_name": "test-agent",
        "event_type": "tool_result",
        "task": "run tests",
        "tool_name": "pytest",
        "status": "success",
        "input": {"cmd": "pytest"},
        "output": {"result": "ok"},
        "error": None,
        "resolution": None,
        "paths": ["/tmp/test.py"],
        "metadata_": {"key": "value"},
        "source_hash": "abc123",
        "created_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_event_from_row_basic_mapping() -> None:
    row = _make_event_orm_row()
    event = _event_from_row(row)
    assert event.id == row.id
    assert event.project_slug == row.project_slug
    assert event.event_type == OperationalMemoryEventType.TOOL_RESULT


def test_event_from_row_converts_conversation_id_to_str() -> None:
    cid = uuid4()
    row = _make_event_orm_row(conversation_id=cid)
    event = _event_from_row(row)
    assert event.conversation_id == str(cid)


def test_event_from_row_none_conversation_id() -> None:
    row = _make_event_orm_row(conversation_id=None)
    event = _event_from_row(row)
    assert event.conversation_id is None


def test_event_from_row_empty_input_becomes_dict() -> None:
    row = _make_event_orm_row(input=None)
    event = _event_from_row(row)
    assert event.input == {}


def test_event_from_row_empty_output_becomes_dict() -> None:
    row = _make_event_orm_row(output=None)
    event = _event_from_row(row)
    assert event.output == {}


def test_event_from_row_empty_paths_becomes_list() -> None:
    row = _make_event_orm_row(paths=None)
    event = _event_from_row(row)
    assert event.paths == []


def test_event_from_row_empty_metadata_becomes_dict() -> None:
    row = _make_event_orm_row(metadata_=None)
    event = _event_from_row(row)
    assert event.metadata == {}


def test_event_from_row_unknown_event_type_raises() -> None:
    row = _make_event_orm_row(event_type="unknown_custom_type")
    with pytest.raises(ValueError):
        _event_from_row(row)


# ---------------------------------------------------------------------------
# _outbox_payload
# ---------------------------------------------------------------------------


def _make_outbox_row(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "event_id": uuid4(),
        "project_slug": "test-project",
        "workspace_root": "/tmp/test",
        "job_type": "index_operational_memory_event",
        "payload": {"event_id": "evt-1", "content": "test"},
        "dedupe_key": "evt-1:index_operational_memory_event",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_outbox_payload_basic_mapping() -> None:
    row = _make_outbox_row()
    payload = _outbox_payload(row)
    assert payload["id"] == str(row.id)
    assert payload["event_id"] == str(row.event_id)
    assert payload["job_type"] == row.job_type
    assert payload["payload"] == row.payload
    assert payload["dedupe_key"] == row.dedupe_key


def test_outbox_payload_none_event_id() -> None:
    row = _make_outbox_row(event_id=None)
    payload = _outbox_payload(row)
    assert payload["event_id"] is None


def test_outbox_payload_empty_payload() -> None:
    row = _make_outbox_row(payload=None)
    payload = _outbox_payload(row)
    assert payload["payload"] == {}


def test_outbox_payload_preserves_project_slug() -> None:
    row = _make_outbox_row(project_slug="my-project")
    payload = _outbox_payload(row)
    assert payload["project_slug"] == "my-project"
