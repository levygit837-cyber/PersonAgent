"""Tests for the chat memory-recall coordinator.

The coordinator is the single entry point for both recall pipelines:

* **classic recall** -- the file-backed long-term memory pipeline,
  which surfaces ``RelevantMemory`` items and tracks them on the
  conversation so they're not redrawn next turn;
* **operational recall** -- the execution-history pipeline, which
  returns a formatted block plus rich metadata, with a
  ``latest_only`` fallback when primary recall is empty.

These tests pin the externally observable behavior we rely on: the
metadata side effects (``_surfaced_memory_paths`` and
``_operational_memory_prompt``), the latest-only fallback, the
failure-isolation contract (recall failures must never crash the
turn), and the optional-collaborator policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.memory_recall import (
    MemoryRecallCoordinator,
)
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.memory.models.operational import StructuredMemoryPackage
from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.models.conversation import Conversation

# ---------------------------------------------------------------------------
# Collaborator doubles
# ---------------------------------------------------------------------------


class _ClassicRecallStub:
    """Stand-in for :class:`RecallMemoryUseCase`."""

    def __init__(self, memories: list[RelevantMemory] | None = None) -> None:
        self.memories = memories or []
        self.calls: list[dict[str, Any]] = []
        self.should_raise = False

    async def execute(
        self,
        *,
        query: str,
        memory_dir: Path,
        recent_tools: list[str] | None = None,
        already_surfaced: set[str] | None = None,
    ) -> list[RelevantMemory]:
        self.calls.append(
            {
                "query": query,
                "memory_dir": memory_dir,
                "recent_tools": recent_tools,
                "already_surfaced": already_surfaced,
            }
        )
        if self.should_raise:
            raise RuntimeError("classic recall blew up")
        return self.memories


class _MemoryRepositoryStub:
    """Stand-in for :class:`MemoryRepository.get_memory_dir`."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.calls: list[str] = []

    async def get_memory_dir(self, project_slug: str, *args: Any, **kwargs: Any) -> Path:
        self.calls.append(project_slug)
        return self.memory_dir


class _OperationalRecallStub:
    """Stand-in for :class:`OperationalMemoryService.recall_package_for_prompt`."""

    def __init__(
        self,
        packages: list[StructuredMemoryPackage] | None = None,
    ) -> None:
        # One package per call; the coordinator may issue up to two
        # calls per recall (primary, then latest_only fallback).
        self.packages = packages or []
        self.calls: list[dict[str, Any]] = []
        self.should_raise = False

    async def recall_package_for_prompt(self, **kwargs: Any) -> StructuredMemoryPackage:
        self.calls.append(kwargs)
        if self.should_raise:
            raise RuntimeError("operational recall blew up")
        if not self.packages:
            return _empty_package()
        # Repeat the last package when caller exhausts the script.
        index = min(len(self.calls) - 1, len(self.packages) - 1)
        return self.packages[index]


def _empty_package() -> StructuredMemoryPackage:
    return StructuredMemoryPackage(
        formatted="",
        items=[],
        filters_applied={},
        budget_used=0,
        budget_tokens=0,
        omitted_count=0,
        latency_ms=0,
    )


def _package(formatted: str) -> StructuredMemoryPackage:
    return StructuredMemoryPackage(
        formatted=formatted,
        items=[],
        filters_applied={},
        budget_used=42,
        budget_tokens=2048,
        omitted_count=0,
        latency_ms=12,
    )


def _memory(path: str, content: str = "foo") -> RelevantMemory:
    return RelevantMemory(
        path=path,
        content=content,
        mtime_ms=1,
        header="saved just now",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _request(message: str = "do the thing") -> ChatRequestDTO:
    return ChatRequestDTO(
        message=message,
        provider="nvidia",
        model="test-model",
        prompt_mode="code",
    )


def _context(workspace_root: str = "/home/user/MyProject") -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(
            workspace_root=workspace_root,
            cwd=workspace_root,
        ),
        user_context=UserContext(),
        build_duration_ms=0,
    )


# ---------------------------------------------------------------------------
# Optional-collaborator policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_returns_empty_when_no_collaborators_present() -> None:
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=None,
        context_window_tokens=128_000,
    )
    conversation = Conversation(id=uuid4(), title="t")

    result = await coordinator.recall(_request(), _context(), conversation)

    assert result.prompt_memories == []
    # MemoryTraceBuilder collapses the empty-inputs case to ``None``
    # so the UI knows there's nothing to render. The important
    # contract is that the call doesn't raise.
    assert result.trace is None


@pytest.mark.asyncio
async def test_classic_recall_requires_both_use_case_and_repository(
    tmp_path: Path,
) -> None:
    """Either collaborator missing -> classic path is silently skipped."""

    stub_use_case = _ClassicRecallStub(memories=[_memory("notes/foo.md")])
    # Use case present, repository missing -> classic path is skipped.
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=stub_use_case,
        memory_repository=None,
        operational_memory_service=None,
        context_window_tokens=128_000,
    )

    result = await coordinator.recall(_request(), _context(), Conversation())

    assert stub_use_case.calls == []
    assert result.prompt_memories == []


# ---------------------------------------------------------------------------
# Classic recall behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classic_recall_passes_project_slug_and_query(tmp_path: Path) -> None:
    stub_use_case = _ClassicRecallStub(memories=[_memory("notes/foo.md")])
    stub_repo = _MemoryRepositoryStub(memory_dir=tmp_path)
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=stub_use_case,
        memory_repository=stub_repo,
        operational_memory_service=None,
        context_window_tokens=128_000,
    )

    await coordinator.recall(
        _request("explain refactor"),
        _context("/home/user/MyProject"),
        Conversation(),
    )

    assert stub_repo.calls == ["myproject"]
    assert len(stub_use_case.calls) == 1
    assert stub_use_case.calls[0]["query"] == "explain refactor"
    assert stub_use_case.calls[0]["memory_dir"] == tmp_path
    # Per the migrated TODO: recent_tools is currently always [].
    assert stub_use_case.calls[0]["recent_tools"] == []


@pytest.mark.asyncio
async def test_classic_recall_dedupes_via_surfaced_paths(tmp_path: Path) -> None:
    stub_use_case = _ClassicRecallStub(
        memories=[_memory("notes/foo.md"), _memory("notes/bar.md")]
    )
    stub_repo = _MemoryRepositoryStub(memory_dir=tmp_path)
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=stub_use_case,
        memory_repository=stub_repo,
        operational_memory_service=None,
        context_window_tokens=128_000,
    )

    conversation = Conversation()
    conversation.metadata["_surfaced_memory_paths"] = ["notes/baz.md"]

    await coordinator.recall(_request(), _context(), conversation)

    # Both old and new paths are now tracked on the conversation.
    surfaced = set(conversation.metadata["_surfaced_memory_paths"])
    assert surfaced == {"notes/foo.md", "notes/bar.md", "notes/baz.md"}
    # The use case received the previous set as ``already_surfaced``.
    assert stub_use_case.calls[0]["already_surfaced"] == {"notes/baz.md"}


@pytest.mark.asyncio
async def test_classic_recall_failure_is_swallowed(tmp_path: Path) -> None:
    stub_use_case = _ClassicRecallStub()
    stub_use_case.should_raise = True
    stub_repo = _MemoryRepositoryStub(memory_dir=tmp_path)
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=stub_use_case,
        memory_repository=stub_repo,
        operational_memory_service=None,
        context_window_tokens=128_000,
    )

    result = await coordinator.recall(_request(), _context(), Conversation())

    assert result.prompt_memories == []


# ---------------------------------------------------------------------------
# Operational recall behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operational_recall_stamps_metadata_on_conversation() -> None:
    stub_op = _OperationalRecallStub(packages=[_package("OPERATIONAL_BLOCK")])
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )
    conversation = Conversation()

    result = await coordinator.recall(_request(), _context(), conversation)

    assert "OPERATIONAL_BLOCK" in result.prompt_memories
    assert "_operational_memory_prompt" in conversation.metadata
    stamp = conversation.metadata["_operational_memory_prompt"]
    assert stamp["memory_budget_tokens"] == 2048
    assert stamp["memory_budget_used"] == 42


@pytest.mark.asyncio
async def test_operational_recall_falls_back_to_latest_only_when_primary_empty() -> None:
    """When the primary recall returns no formatted block, the
    coordinator retries with ``latest_only=True`` so the agent still
    sees recent execution context."""

    stub_op = _OperationalRecallStub(
        packages=[_empty_package(), _package("FALLBACK_BLOCK")]
    )
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )

    result = await coordinator.recall(_request(), _context(), Conversation())

    assert "FALLBACK_BLOCK" in result.prompt_memories
    assert len(stub_op.calls) == 2
    assert stub_op.calls[0].get("latest_only") in (False, None)
    assert stub_op.calls[1].get("latest_only") is True


@pytest.mark.asyncio
async def test_operational_recall_skips_when_both_passes_empty() -> None:
    stub_op = _OperationalRecallStub(packages=[_empty_package(), _empty_package()])
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )
    conversation = Conversation()

    result = await coordinator.recall(_request(), _context(), conversation)

    assert result.prompt_memories == []
    # The fallback's metadata stamp is what's left on the conversation.
    assert "_operational_memory_prompt" in conversation.metadata


@pytest.mark.asyncio
async def test_operational_recall_clears_stale_metadata_before_running() -> None:
    """The previous turn's stamp shouldn't survive a recall failure."""

    stub_op = _OperationalRecallStub()
    stub_op.should_raise = True
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )
    conversation = Conversation()
    conversation.metadata["_operational_memory_prompt"] = {"stale": True}

    await coordinator.recall(_request(), _context(), conversation)

    # Stale metadata is cleared regardless of whether the new recall
    # succeeded -- the alternative would leave the UI showing stats
    # for a recall that never happened.
    assert "_operational_memory_prompt" not in conversation.metadata


@pytest.mark.asyncio
async def test_operational_recall_failure_is_swallowed() -> None:
    stub_op = _OperationalRecallStub()
    stub_op.should_raise = True
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=None,
        memory_repository=None,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )

    result = await coordinator.recall(_request(), _context(), Conversation())

    assert result.prompt_memories == []
    # Failed recall + no successful recall elsewhere -> no trace.
    assert result.trace is None


# ---------------------------------------------------------------------------
# Combined behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_pipelines_contribute_to_prompt_memories(tmp_path: Path) -> None:
    stub_use_case = _ClassicRecallStub(memories=[_memory("notes/foo.md", "MEM-A")])
    stub_repo = _MemoryRepositoryStub(memory_dir=tmp_path)
    stub_op = _OperationalRecallStub(packages=[_package("MEM-B")])
    coordinator = MemoryRecallCoordinator(
        recall_memory_use_case=stub_use_case,
        memory_repository=stub_repo,
        operational_memory_service=stub_op,
        context_window_tokens=128_000,
    )

    result = await coordinator.recall(_request(), _context(), Conversation())

    joined = "\n".join(result.prompt_memories)
    assert "MEM-A" in joined
    assert "MEM-B" in joined
