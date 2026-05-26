"""Tests for the context compactor extracted from ``chat_completion.py``.

The compactor used to live as four methods + three module constants on
:class:`ChatCompletionUseCase`; now it is a tiny standalone service.
These tests pin the externally observable behavior we relied on while
the surface was still entangled with the use case.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.lifecycle.compaction import ConversationCompactor
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository


class _StubLLM(LLMBackendRepository):
    """Returns whatever ``content`` is configured at construction time.

    Set ``raise_exc=True`` to exercise the fallback summary path.
    """

    def __init__(self, content: str = "summary OK", *, raise_exc: bool = False) -> None:
        self.content = content
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(self, *args: object, **kwargs: object) -> InferenceResult:
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.raise_exc:
            raise RuntimeError("provider down")
        return InferenceResult(content=self.content)

    async def chat_completion_stream(
        self, *args: object, **kwargs: object
    ) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk()

    async def health_check(self) -> dict[str, str]:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict[str, str]:
        return {}


def _request(**overrides: Any) -> ChatRequestDTO:
    base: dict[str, Any] = {
        "message": "hi",
        "provider": "nvidia",
        "model": "test-model",
        "max_tokens": None,
        "reasoning_budget_tokens": 0,
    }
    base.update(overrides)
    return ChatRequestDTO(**base)


# ---------------------------------------------------------------------------
# Configuration / floors
# ---------------------------------------------------------------------------


def test_compactor_floors_context_window_to_4096() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=100, default_output_tokens=8
    )
    assert compactor.context_window_tokens == 4_096


def test_compactor_floors_default_output_to_one() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=8_192, default_output_tokens=0
    )
    assert compactor.default_output_tokens == 1


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def test_estimate_request_tokens_returns_zero_for_empty_payload() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=8_192, default_output_tokens=512
    )
    assert compactor.estimate_request_tokens([], []) == 0


def test_estimate_request_tokens_accounts_for_role_content_and_tools() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=8_192, default_output_tokens=512
    )
    messages = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 50, "tool_calls": [{"id": "x"}]},
    ]
    tools = [{"function": {"name": "read_file"}}]

    estimate = compactor.estimate_request_tokens(messages, tools)
    # Each character ~ 0.25 token (we use ceil(chars / 4) with a small
    # role overhead). The exact integer isn't important; we just want
    # to lock in that the estimate scales with input size.
    assert estimate > 30


# ---------------------------------------------------------------------------
# Threshold math
# ---------------------------------------------------------------------------


def test_compaction_threshold_uses_request_max_tokens_when_provided() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=100_000, default_output_tokens=10_000
    )
    threshold = compactor.compaction_threshold(_request(max_tokens=5_000))
    # 100k - 5k (output reserve) = 95k * 0.9 = 85_500
    assert threshold == int(95_000 * 0.9)


def test_compaction_threshold_falls_back_to_quarter_of_window() -> None:
    """When ``max_tokens`` is unset, the reserve is min(default, window/4)."""

    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=100_000, default_output_tokens=10_000
    )
    threshold = compactor.compaction_threshold(_request(max_tokens=None))
    # min(10_000, 25_000) = 10_000 reserve; (100_000 - 10_000) * 0.9 = 81_000
    assert threshold == int(90_000 * 0.9)


def test_compaction_threshold_subtracts_reasoning_budget() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=100_000, default_output_tokens=5_000
    )
    base = compactor.compaction_threshold(_request(reasoning_budget_tokens=0))
    with_reasoning = compactor.compaction_threshold(
        _request(reasoning_budget_tokens=10_000)
    )
    assert with_reasoning < base


def test_compaction_threshold_never_drops_below_2048() -> None:
    """Pathological config -> the floor must protect us."""

    compactor = ConversationCompactor(
        _StubLLM(),
        context_window_tokens=4_096,
        default_output_tokens=64_000,
    )
    threshold = compactor.compaction_threshold(
        _request(max_tokens=64_000, reasoning_budget_tokens=64_000)
    )
    assert threshold >= 2_048


def test_should_compact_returns_true_above_threshold() -> None:
    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=8_192, default_output_tokens=512
    )
    threshold = compactor.compaction_threshold(_request())
    assert compactor.should_compact(threshold + 1, _request()) is True
    assert compactor.should_compact(threshold, _request()) is False


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def test_render_messages_for_summary_truncates_long_messages() -> None:
    long_content = "x" * 6_000
    messages = [Message(role=Role.USER, content=long_content)]

    rendered = ConversationCompactor.render_messages_for_summary(messages)

    assert "[truncated]" in rendered
    assert len(rendered) < 6_500


def test_render_messages_for_summary_includes_tool_calls() -> None:
    msg = Message(role=Role.ASSISTANT, content="ok", tool_calls=[{"id": "x"}])
    rendered = ConversationCompactor.render_messages_for_summary([msg])
    assert "Tool calls:" in rendered


def test_fallback_summary_includes_message_count_and_excerpts() -> None:
    messages = [
        Message(role=Role.USER, content=f"msg {i}") for i in range(10)
    ]

    fallback = ConversationCompactor.fallback_summary(messages)

    assert "10 earlier messages" in fallback
    assert "msg 0" in fallback
    assert "msg 9" in fallback


def test_fallback_summary_normalizes_whitespace() -> None:
    """Multi-line + tab-laden content -> single normalized line per excerpt."""

    messages = [Message(role=Role.USER, content="line1\n\nline2\t\tline3")]
    fallback = ConversationCompactor.fallback_summary(messages)
    assert "line1 line2 line3" in fallback


# ---------------------------------------------------------------------------
# Compaction lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_conversation_returns_false_when_below_recent_threshold() -> None:
    """Conversations <= 10 messages (recent_count + 2) are never compacted."""

    compactor = ConversationCompactor(
        _StubLLM(), context_window_tokens=8_192, default_output_tokens=512
    )
    conversation = Conversation()
    for i in range(5):
        conversation.add_message(Message(role=Role.USER, content=f"msg {i}"))

    result = await compactor.compact_conversation(conversation, _request())

    assert result is False
    assert len(conversation.messages) == 5


@pytest.mark.asyncio
async def test_compact_conversation_collapses_older_into_system_summary() -> None:
    compactor = ConversationCompactor(
        _StubLLM(content="SUMMARY"),
        context_window_tokens=8_192,
        default_output_tokens=512,
    )
    conversation = Conversation()
    for i in range(20):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        conversation.add_message(Message(role=role, content=f"message {i}"))
    original_count = len(conversation.messages)

    result = await compactor.compact_conversation(conversation, _request())

    assert result is True
    # First message is now the SYSTEM continuity summary.
    assert conversation.messages[0].role == Role.SYSTEM
    assert "SUMMARY" in conversation.messages[0].content
    assert conversation.messages[0].metadata.get("context_compaction") is True
    # The 8 most recent messages are preserved verbatim.
    assert conversation.messages[-1].content == "message 19"
    # The conversation got shorter.
    assert len(conversation.messages) < original_count
    # The conversation metadata records the compaction.
    assert conversation.metadata["context_compaction"]["compacted"] is True


@pytest.mark.asyncio
async def test_compact_conversation_preserves_plan_approval_messages() -> None:
    """Plan-approval artifacts must survive compaction verbatim.

    The frontend reconstructs the plan panel from these messages, so
    summarizing them away would break the UI.
    """

    compactor = ConversationCompactor(
        _StubLLM(content="SUMMARY"),
        context_window_tokens=8_192,
        default_output_tokens=512,
    )
    conversation = Conversation()
    for i in range(20):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        msg = Message(role=role, content=f"message {i}")
        # Mark the third message as a plan approval artifact.
        if i == 3:
            msg.metadata["plan_approval"] = {
                "approvalId": "a1",
                "planContent": "1. ship",
            }
        conversation.add_message(msg)

    await compactor.compact_conversation(conversation, _request())

    plan_messages = [
        m
        for m in conversation.messages
        if isinstance(m.metadata, dict) and m.metadata.get("plan_approval")
    ]
    assert len(plan_messages) == 1
    assert plan_messages[0].metadata["plan_approval"]["approvalId"] == "a1"


@pytest.mark.asyncio
async def test_compact_conversation_falls_back_when_llm_raises() -> None:
    """Provider failure -> deterministic fallback summary, not an exception."""

    compactor = ConversationCompactor(
        _StubLLM(raise_exc=True),
        context_window_tokens=8_192,
        default_output_tokens=512,
    )
    conversation = Conversation()
    for i in range(20):
        conversation.add_message(Message(role=Role.USER, content=f"msg {i}"))

    result = await compactor.compact_conversation(conversation, _request())

    assert result is True
    summary_msg = conversation.messages[0]
    assert summary_msg.role == Role.SYSTEM
    assert "earlier messages were compacted" in summary_msg.content


@pytest.mark.asyncio
async def test_compact_conversation_does_not_orphan_tool_results() -> None:
    """A TOOL message at the recent-window boundary stays with its caller."""

    compactor = ConversationCompactor(
        _StubLLM(content="SUMMARY"),
        context_window_tokens=8_192,
        default_output_tokens=512,
    )
    conversation = Conversation()
    # Layout: 12 plain messages followed by a TOOL message at position
    # -8 (boundary). Without the pull-back logic the TOOL message would
    # start the recent window with no parent assistant call.
    for i in range(12):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        conversation.add_message(Message(role=role, content=f"msg {i}"))
    conversation.add_message(Message(role=Role.ASSISTANT, content="calling tool"))
    conversation.add_message(Message(role=Role.TOOL, content="tool result"))
    for i in range(7):
        conversation.add_message(Message(role=Role.USER, content=f"after {i}"))

    await compactor.compact_conversation(conversation, _request())

    # The TOOL message must still be paired with an ASSISTANT message
    # before it.
    tool_indices = [
        i for i, m in enumerate(conversation.messages) if m.role == Role.TOOL
    ]
    assert tool_indices, "TOOL message dropped after compaction"
    for tool_idx in tool_indices:
        # Either right after the SYSTEM summary (not allowed) or after
        # an ASSISTANT message (allowed).
        previous = conversation.messages[tool_idx - 1]
        assert previous.role in {Role.ASSISTANT, Role.SYSTEM}
        # If previous is SYSTEM it must be the summary (compaction
        # boundary), but that means the tool got orphaned -- fail.
        if previous.role == Role.SYSTEM:
            assert previous.metadata.get("context_compaction") is not True, (
                "TOOL message orphaned: directly follows compaction summary"
            )
