"""Tests for :class:`ToolResultBudgetService` and resume reconstruction."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.application.use_cases.chat.tooling.tool_result_budget import (
    ToolResultBudgetService,
    reconstruct_state_from_conversation,
)
from personagent.application.use_cases.chat.tooling.tool_result_budget_helpers import (
    _is_content_already_compacted,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.tools.tool_result_budget import (
    ContentReplacementState,
    PERSISTED_OUTPUT_TAG,
    ToolResultReplacementRecord,
)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _FakeArtifactStorage(ArtifactStoragePort):
    """In-memory artifact storage that writes to a dict."""

    def __init__(self, fail: bool = False) -> None:
        self.files: dict[str, str] = {}
        self.fail = fail

    def persist_tool_result(
        self,
        content: str,
        conversation_id: str,
        tool_call_id: str,
        root: Any,
    ) -> str | None:
        if self.fail:
            return None
        path = f"/tmp/tool-results/{conversation_id}/{tool_call_id}.txt"
        self.files[path] = content
        return path

    def store_bytes(
        self,
        *,
        category: str,
        conversation_id: str,
        content: bytes,
        suffix: str,
        mime_type: str,
        root: Any,
        ttl_seconds: int | None,
    ) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conversation(
    messages: list[Message] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Conversation:
    return Conversation(
        id=uuid4(),
        title="t",
        messages=list(messages or []),
        metadata=dict(metadata or {}),
    )


def _assistant_msg(content: str = "calling tool", tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or []}


def _tool_msg(content: str, tool_call_id: str) -> dict[str, Any]:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


# ---------------------------------------------------------------------------
# enforce_budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_budget_no_op_when_under_limit() -> None:
    service = ToolResultBudgetService(artifact_storage=_FakeArtifactStorage())
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [
        _assistant_msg(),
        _tool_msg("a" * 10_000, "t1"),
        _tool_msg("b" * 20_000, "t2"),
    ]
    adjusted, newly = await service.enforce_budget(rendered, conv, state)
    assert adjusted is rendered
    assert newly == []
    assert state.has_seen("t1")
    assert state.has_seen("t2")


@pytest.mark.asyncio
async def test_enforce_budget_replaces_largest_fresh_results() -> None:
    storage = _FakeArtifactStorage()
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [
        _assistant_msg(),
        _tool_msg("a" * 80_000, "t1"),
        _tool_msg("b" * 80_000, "t2"),
        _tool_msg("c" * 80_000, "t3"),
    ]
    adjusted, newly = await service.enforce_budget(rendered, conv, state)
    assert len(newly) == 1
    replaced_id = newly[0].tool_call_id
    assert replaced_id in {"t1", "t2", "t3"}
    assert _is_content_already_compacted(
        next(m for m in adjusted if m.get("tool_call_id") == replaced_id)["content"]
    )
    assert state.is_replaced(replaced_id)
    untouched = {"t1", "t2", "t3"} - {replaced_id}
    for tid in untouched:
        assert not state.is_replaced(tid)


@pytest.mark.asyncio
async def test_enforce_budget_reapplies_cached_replacements() -> None:
    storage = _FakeArtifactStorage()
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered1 = [
        _assistant_msg(),
        _tool_msg("a" * 250_000, "t1"),
    ]
    adjusted1, newly1 = await service.enforce_budget(rendered1, conv, state)
    assert len(newly1) == 1
    cached_preview = state.get_replacement("t1")
    assert cached_preview is not None

    rendered2 = [
        _assistant_msg(),
        _tool_msg("a" * 250_000, "t1"),
    ]
    adjusted2, newly2 = await service.enforce_budget(rendered2, conv, state)
    assert newly2 == []
    assert adjusted2[1]["content"] == cached_preview


@pytest.mark.asyncio
async def test_enforce_budget_freezes_seen_results() -> None:
    storage = _FakeArtifactStorage()
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered1 = [
        _assistant_msg(),
        _tool_msg("a" * 10_000, "t1"),
    ]
    await service.enforce_budget(rendered1, conv, state)
    assert state.has_seen("t1")
    assert not state.is_replaced("t1")

    rendered2 = [
        _assistant_msg(),
        _tool_msg("a" * 10_000, "t1"),
        _tool_msg("b" * 120_000, "t2"),
        _tool_msg("c" * 120_000, "t3"),
    ]
    adjusted2, newly2 = await service.enforce_budget(rendered2, conv, state)
    assert not _is_content_already_compacted(adjusted2[1]["content"])
    replaced_ids = {r.tool_call_id for r in newly2}
    assert "t1" not in replaced_ids


@pytest.mark.asyncio
async def test_enforce_budget_skips_tools_in_skip_set() -> None:
    storage = _FakeArtifactStorage()
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [
        _assistant_msg(tool_calls=[
            {"id": "t1", "function": {"name": "Read"}},
            {"id": "t2", "function": {"name": "shell"}},
        ]),
        _tool_msg("a" * 120_000, "t1"),
        _tool_msg("b" * 120_000, "t2"),
    ]
    adjusted, newly = await service.enforce_budget(
        rendered, conv, state, skip_tool_names={"Read"}
    )
    assert len(newly) == 0

    state2 = ContentReplacementState()
    rendered2 = [
        _assistant_msg(tool_calls=[
            {"id": "t1", "function": {"name": "Read"}},
            {"id": "t2", "function": {"name": "shell"}},
        ]),
        _tool_msg("a" * 120_000, "t1"),
        _tool_msg("b" * 250_000, "t2"),
    ]
    adjusted2, newly2 = await service.enforce_budget(
        rendered2, conv, state2, skip_tool_names={"Read"}
    )
    assert len(newly2) == 1
    assert newly2[0].tool_call_id == "t2"


@pytest.mark.asyncio
async def test_enforce_budget_handles_persistence_failure() -> None:
    storage = _FakeArtifactStorage(fail=True)
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [
        _assistant_msg(),
        _tool_msg("a" * 250_000, "t1"),
    ]
    adjusted, newly = await service.enforce_budget(rendered, conv, state)
    assert newly == []
    assert adjusted[1]["content"] == "a" * 250_000
    assert state.has_seen("t1")
    assert not state.is_replaced("t1")


@pytest.mark.asyncio
async def test_enforce_budget_no_storage_returns_original() -> None:
    service = ToolResultBudgetService(artifact_storage=None)
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [_assistant_msg(), _tool_msg("a" * 250_000, "t1")]
    adjusted, newly = await service.enforce_budget(rendered, conv, state)
    assert adjusted is rendered
    assert newly == []


# ---------------------------------------------------------------------------
# apply_budget (integration wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_budget_persists_records_to_metadata() -> None:
    storage = _FakeArtifactStorage()
    service = ToolResultBudgetService(artifact_storage=storage)
    conv = _conversation()
    state = ContentReplacementState()
    rendered = [
        _assistant_msg(),
        _tool_msg("a" * 250_000, "t1"),
    ]
    adjusted = await service.apply_budget(rendered, conv, state)
    assert _is_content_already_compacted(adjusted[1]["content"])
    records = conv.metadata.get("tool_result_replacements", [])
    assert len(records) == 1
    assert records[0]["tool_call_id"] == "t1"


# ---------------------------------------------------------------------------
# reconstruct_state_from_conversation
# ---------------------------------------------------------------------------


def test_reconstruct_state_populates_seen_and_replacements() -> None:
    conv = _conversation(
        messages=[
            Message(role=Role.ASSISTANT, content="call"),
            Message(role=Role.TOOL, content="result1", tool_call_id="t1"),
            Message(role=Role.TOOL, content="result2", tool_call_id="t2"),
        ],
        metadata={
            "tool_result_replacements": [
                {"tool_call_id": "t1", "replacement": "preview1"},
            ]
        },
    )
    state = reconstruct_state_from_conversation(conv)
    assert state.has_seen("t1")
    assert state.has_seen("t2")
    assert state.is_replaced("t1")
    assert state.get_replacement("t1") == "preview1"
    assert not state.is_replaced("t2")


def test_reconstruct_state_ignores_invalid_records() -> None:
    conv = _conversation(
        messages=[
            Message(role=Role.TOOL, content="r", tool_call_id="t1"),
        ],
        metadata={
            "tool_result_replacements": [
                {"bad_key": "no tool_call_id"},
            ]
        },
    )
    state = reconstruct_state_from_conversation(conv)
    assert state.has_seen("t1")
    assert not state.is_replaced("t1")


# ---------------------------------------------------------------------------
# ContentReplacementState (domain module)
# ---------------------------------------------------------------------------


def test_clone_creates_independent_copy() -> None:
    state = ContentReplacementState()
    state.add_replacement("t1", "preview")
    clone = state.clone()
    clone.add_replacement("t2", "other")
    assert state.is_replaced("t1")
    assert not state.is_replaced("t2")
    assert clone.is_replaced("t1")
    assert clone.is_replaced("t2")
