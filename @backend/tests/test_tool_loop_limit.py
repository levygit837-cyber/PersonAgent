"""Tests for the tool-iteration safety cap in the chat completion loop.

These tests cover the runaway protection added on top of the existing
``max_tool_iterations`` field: the chat loop now resolves an effective cap from
the request, the runtime config, and a hard safety ceiling -- and raises
``ToolLoopLimitExceededError`` when the loop would otherwise iterate forever.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.application.tools.runtime_config import (
    SAFETY_TOOL_ITERATION_CEILING,
    resolve_effective_tool_iterations,
)
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.conversation.models import Conversation
from personagent.domain.conversation.repositories import ConversationRepository
from personagent.domain.exceptions import ToolLoopLimitExceededError
from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.infrastructure.tools import create_read_file_tool


class _AlwaysToolCallingLLM(LLMBackendRepository):
    """LLM stub that emits a fresh tool call on every turn.

    This is the adversarial shape the safety cap protects against: a model that
    would otherwise keep the chat loop running indefinitely.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, *args: object, **kwargs: object) -> InferenceResult:
        self.calls += 1
        return InferenceResult(
            content="",
            finish_reason="tool_calls",
            tool_calls=[
                {
                    "id": f"call_{self.calls}",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"notes.txt"}',
                    },
                }
            ],
        )

    async def chat_completion_stream(self, *args: object, **kwargs: object):
        self.calls += 1
        yield StreamChunk(
            tool_calls=[
                {
                    "index": 0,
                    "id": f"call_{self.calls}",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"notes.txt"}',
                    },
                }
            ]
        )
        yield StreamChunk(finish_reason="tool_calls")

    async def health_check(self) -> dict[str, str]:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict[str, str]:
        return {}


class _MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return [
            conv
            for conv in self.conversations.values()
            if query in conv.title
        ][:limit]


def _make_use_case(tmp_path: Path, llm: LLMBackendRepository) -> ChatCompletionUseCase:
    (tmp_path / "notes.txt").write_text("ok\n", encoding="utf-8")
    return ChatCompletionUseCase(
        conversation_repo=_MemoryConversationRepository(),
        llm_backend=llm,
        tool_registry=ToolRegistry([create_read_file_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )


def test_resolve_effective_tool_iterations_prefers_request() -> None:
    assert (
        resolve_effective_tool_iterations(request_max=4, config_max=100)
        == 4
    )


def test_resolve_effective_tool_iterations_falls_back_to_config() -> None:
    assert (
        resolve_effective_tool_iterations(request_max=None, config_max=12)
        == 12
    )


def test_resolve_effective_tool_iterations_uses_safety_ceiling_when_none() -> None:
    assert (
        resolve_effective_tool_iterations(request_max=None, config_max=None)
        == SAFETY_TOOL_ITERATION_CEILING
    )


def test_resolve_effective_tool_iterations_floors_to_at_least_one() -> None:
    assert (
        resolve_effective_tool_iterations(request_max=0, config_max=None)
        == 1
    )
    assert (
        resolve_effective_tool_iterations(request_max=-5, config_max=None)
        == 1
    )


@pytest.mark.asyncio
async def test_execute_raises_when_request_cap_is_exceeded(tmp_path: Path) -> None:
    llm = _AlwaysToolCallingLLM()
    use_case = _make_use_case(tmp_path, llm)

    with pytest.raises(ToolLoopLimitExceededError) as excinfo:
        await use_case.execute(
            ChatRequestDTO(
                message="loop forever please",
                tools_enabled=True,
                max_tool_iterations=2,
            )
        )

    assert excinfo.value.metadata["limit"] == 2
    assert excinfo.value.metadata["source"] == "request"
    # Two tool iterations executed plus a third LLM call attempted is what would
    # have happened previously; the cap stops us after exactly two.
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_execute_stream_emits_tool_loop_limit_event(tmp_path: Path) -> None:
    llm = _AlwaysToolCallingLLM()
    use_case = _make_use_case(tmp_path, llm)

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(
                message="loop forever please",
                tools_enabled=True,
                max_tool_iterations=1,
            )
        )
    ]
    events = [chunk.metadata.get("event") for chunk in chunks if chunk.metadata]

    assert "tool_loop_limit_exceeded" in events
    limit_chunk = next(
        chunk for chunk in chunks if chunk.metadata.get("event") == "tool_loop_limit_exceeded"
    )
    assert limit_chunk.metadata["limit"] == 1
    assert limit_chunk.metadata["source"] == "request"


@pytest.mark.asyncio
async def test_execute_stream_falls_back_to_config_cap(tmp_path: Path) -> None:
    llm = _AlwaysToolCallingLLM()
    repo = _MemoryConversationRepository()
    (tmp_path / "notes.txt").write_text("ok\n", encoding="utf-8")
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_read_file_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(
            workspace_root=tmp_path,
            max_tool_iterations=1,
        ),
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(message="loop forever please", tools_enabled=True)
        )
    ]
    events = [chunk.metadata.get("event") for chunk in chunks if chunk.metadata]
    limit_chunk = next(
        chunk for chunk in chunks if chunk.metadata.get("event") == "tool_loop_limit_exceeded"
    )

    assert "tool_loop_limit_exceeded" in events
    assert limit_chunk.metadata["source"] == "runtime_config"
    assert limit_chunk.metadata["limit"] == 1


@pytest.mark.asyncio
async def test_execute_stream_uses_safety_ceiling_when_unbounded(tmp_path: Path) -> None:
    """When neither request nor config caps tool iterations the safety ceiling kicks in."""

    llm = _AlwaysToolCallingLLM()
    repo = _MemoryConversationRepository()
    (tmp_path / "notes.txt").write_text("ok\n", encoding="utf-8")
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_read_file_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(
            workspace_root=tmp_path,
            max_tool_iterations=None,
        ),
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(message="loop forever please", tools_enabled=True)
        )
    ]
    limit_chunk = next(
        chunk for chunk in chunks if chunk.metadata.get("event") == "tool_loop_limit_exceeded"
    )

    assert limit_chunk.metadata["source"] == "safety_ceiling"
    assert limit_chunk.metadata["limit"] == SAFETY_TOOL_ITERATION_CEILING
    # Defense in depth: never run more iterations than the safety ceiling.
    assert llm.calls <= SAFETY_TOOL_ITERATION_CEILING
