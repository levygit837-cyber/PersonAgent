"""Tests for :class:`MessagePreparer`.

The preparer renders the OpenAI-shaped ``messages`` list for one LLM
call. It is responsible for:

* Prepending the system prompt (when present).
* Calling ``Message.to_dict`` for every conversation message.
* Carrying through DeepSeek's ``reasoning_content`` and ZenMux's
  ``reasoning_details`` for assistant messages, but only when the
  provider opted into them.
* Estimating the request token count, asking the compactor whether
  compaction is warranted, applying it in-place if so, and re-rendering.
* Injecting a "respond now, do not call more tools" reminder when the
  caller needs to recover from an empty terminal response.

These tests use a hand-rolled compactor stub so the budget gates are
exercised deterministically without depending on the real tokeniser.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.message_preparation import MessagePreparer
from personagent.application.use_cases.chat.messaging.state import PromptPackage
from personagent.domain.conversation.models import Conversation, Message, Role

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _CompactorStub:
    """Drop-in for :class:`ConversationCompactor` with knobs per-call."""

    def __init__(
        self,
        *,
        token_estimate: int | list[int] = 100,
        should_compact: bool | list[bool] = False,
        compacted: bool = False,
        mutation: Any = None,
    ) -> None:
        self._token_estimates = (
            [token_estimate] if isinstance(token_estimate, int) else list(token_estimate)
        )
        self._should_compacts = (
            [should_compact] if isinstance(should_compact, bool) else list(should_compact)
        )
        self._compacted = compacted
        # Optional callable invoked the first time ``compact_conversation``
        # is awaited; lets a test verify the compactor mutates the
        # conversation.
        self._mutation = mutation
        self.estimate_calls: list[tuple[int, int]] = []
        self.should_compact_calls: list[tuple[int, ChatRequestDTO]] = []
        self.compact_calls: list[tuple[Conversation, ChatRequestDTO]] = []

    def estimate_request_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        self.estimate_calls.append((len(messages), len(tools)))
        if not self._token_estimates:
            return 0
        if len(self._token_estimates) == 1:
            return self._token_estimates[0]
        return self._token_estimates.pop(0)

    def should_compact(self, estimated_tokens: int, request: ChatRequestDTO) -> bool:
        self.should_compact_calls.append((estimated_tokens, request))
        if not self._should_compacts:
            return False
        if len(self._should_compacts) == 1:
            return self._should_compacts[0]
        return self._should_compacts.pop(0)

    async def compact_conversation(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
    ) -> bool:
        self.compact_calls.append((conversation, request))
        if self._mutation is not None:
            self._mutation(conversation)
        return self._compacted


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _preparer(
    *,
    compactor: _CompactorStub | None = None,
    context_window_tokens: int = 100_000,
) -> tuple[MessagePreparer, _CompactorStub]:
    comp = compactor or _CompactorStub()
    preparer = MessagePreparer(
        compactor=comp,  # type: ignore[arg-type]
        context_window_tokens=context_window_tokens,
    )
    return preparer, comp


def _conversation(messages: list[Message] | None = None) -> Conversation:
    return Conversation(id=uuid4(), title="t", messages=list(messages or []), metadata={})


def _package(
    *,
    system_prompt: str | None = "SYS",
    metadata: dict[str, Any] | None = None,
) -> PromptPackage:
    return PromptPackage(
        system_prompt=system_prompt,
        user_context_message=None,
        metadata=dict(metadata or {"prompt_mode": "exploring"}),
    )


def _request(provider: str = "llama", **overrides: Any) -> ChatRequestDTO:
    base: dict[str, Any] = {"message": "hi", "provider": provider, "prompt_mode": "exploring"}
    base.update(overrides)
    return ChatRequestDTO(**base)


# ---------------------------------------------------------------------------
# with_prompt
# ---------------------------------------------------------------------------


def test_with_prompt_prepends_system_message_when_present() -> None:
    preparer, _ = _preparer()
    conv = _conversation([Message(role=Role.USER, content="hi")])

    msgs = preparer.with_prompt(conv, _package(system_prompt="SYS"))

    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "hi"


def test_with_prompt_skips_system_message_when_prompt_is_none() -> None:
    preparer, _ = _preparer()
    conv = _conversation([Message(role=Role.USER, content="hi")])

    msgs = preparer.with_prompt(conv, _package(system_prompt=None))

    assert all(m["role"] != "system" for m in msgs)
    assert len(msgs) == 1


def test_with_prompt_skips_system_message_when_prompt_is_empty_string() -> None:
    preparer, _ = _preparer()
    conv = _conversation([Message(role=Role.USER, content="hi")])

    msgs = preparer.with_prompt(conv, _package(system_prompt=""))

    assert all(m["role"] != "system" for m in msgs)


def test_with_prompt_renders_all_messages_in_order() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(role=Role.USER, content="u1"),
            Message(role=Role.ASSISTANT, content="a1"),
            Message(role=Role.USER, content="u2"),
        ]
    )

    msgs = preparer.with_prompt(conv, _package())

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert [m["content"] for m in msgs[1:]] == ["u1", "a1", "u2"]


def test_with_prompt_skips_empty_assistant_messages() -> None:
    """Interrupted/aborted assistant messages with empty content must be
    omitted from the prompt so the LLM API does not return HTTP 400."""
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(role=Role.USER, content="u1"),
            Message(role=Role.ASSISTANT, content=""),
            Message(role=Role.USER, content="u2"),
        ]
    )

    msgs = preparer.with_prompt(conv, _package())

    assert [m["role"] for m in msgs] == ["system", "user", "user"]


def test_with_prompt_skips_whitespace_only_assistant_messages() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(role=Role.USER, content="u1"),
            Message(role=Role.ASSISTANT, content="   \n  "),
            Message(role=Role.USER, content="u2"),
        ]
    )

    msgs = preparer.with_prompt(conv, _package())

    assert [m["role"] for m in msgs] == ["system", "user", "user"]


def test_with_prompt_keeps_assistant_with_tool_calls_even_if_empty_content() -> None:
    """Assistant messages that have tool calls (not just text) must be
    preserved even when content is empty."""
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(role=Role.USER, content="u1"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[{"id": "t1", "function": {"name": "shell", "arguments": "ls"}}],
            ),
            Message(role=Role.USER, content="u2"),
        ]
    )

    msgs = preparer.with_prompt(conv, _package())

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["tool_calls"] is not None


def test_with_prompt_keeps_assistant_with_content() -> None:
    """Normal assistant messages with non-empty content are preserved."""
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(role=Role.USER, content="u1"),
            Message(role=Role.ASSISTANT, content="hello"),
        ]
    )

    msgs = preparer.with_prompt(conv, _package())

    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]


def test_with_prompt_includes_reasoning_content_only_for_assistant_when_enabled() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={"reasoning_content": "thinking..."},
            ),
            Message(
                role=Role.USER,
                content="u",
                metadata={"reasoning_content": "ignored"},
            ),
        ]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_content=True)

    assistant_msg = next(m for m in msgs if m["role"] == "assistant")
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert assistant_msg["reasoning_content"] == "thinking..."
    assert "reasoning_content" not in user_msg


def test_with_prompt_omits_reasoning_content_when_flag_disabled() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [Message(role=Role.ASSISTANT, content="a", metadata={"reasoning_content": "x"})]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_content=False)

    assert "reasoning_content" not in next(m for m in msgs if m["role"] == "assistant")


def test_with_prompt_skips_empty_reasoning_content_strings() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [Message(role=Role.ASSISTANT, content="a", metadata={"reasoning_content": ""})]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_content=True)

    assert "reasoning_content" not in next(m for m in msgs if m["role"] == "assistant")


def test_with_prompt_ignores_non_string_reasoning_content() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [Message(role=Role.ASSISTANT, content="a", metadata={"reasoning_content": 42})]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_content=True)

    assert "reasoning_content" not in next(m for m in msgs if m["role"] == "assistant")


def test_with_prompt_includes_zenmux_reasoning_details_when_enabled() -> None:
    preparer, _ = _preparer()
    details = [{"type": "thought", "text": "x"}]
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="a",
                metadata={"zenmux_reasoning_details": details},
            )
        ]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_details=True)

    assert next(m for m in msgs if m["role"] == "assistant")["reasoning_details"] == details


def test_with_prompt_omits_zenmux_reasoning_details_when_disabled() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="a",
                metadata={"zenmux_reasoning_details": [{"x": 1}]},
            )
        ]
    )

    msgs = preparer.with_prompt(conv, _package(), include_reasoning_details=False)

    assert "reasoning_details" not in next(m for m in msgs if m["role"] == "assistant")


# ---------------------------------------------------------------------------
# prepare (budget-aware async path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_returns_messages_and_metadata_without_compaction() -> None:
    preparer, comp = _preparer(
        compactor=_CompactorStub(token_estimate=500, should_compact=False),
        context_window_tokens=8_000,
    )
    conv = _conversation([Message(role=Role.USER, content="hi")])
    request = _request()
    package = _package(metadata={"prompt_mode": "exploring", "custom": "ok"})

    messages, metadata = await preparer.prepare(conv, request, package, tools=[])

    assert messages[0]["role"] == "system"
    assert metadata["prompt_mode"] == "exploring"
    assert metadata["custom"] == "ok"
    assert metadata["context_tokens_estimated"] == 500
    assert metadata["context_compacted"] is False
    assert metadata["context_window_tokens"] == 8_000
    assert comp.compact_calls == []


@pytest.mark.asyncio
async def test_prepare_runs_compaction_and_re_estimates_when_budget_exceeded() -> None:
    def _drop_first(conv: Conversation) -> None:
        conv.messages.pop(0)

    comp = _CompactorStub(
        token_estimate=[900, 400],
        should_compact=[True],
        compacted=True,
        mutation=_drop_first,
    )
    preparer, _ = _preparer(compactor=comp)
    conv = _conversation(
        [
            Message(role=Role.USER, content="first"),
            Message(role=Role.USER, content="second"),
        ]
    )
    request = _request()

    messages, metadata = await preparer.prepare(conv, request, _package(), tools=[])

    assert metadata["context_compacted"] is True
    assert metadata["context_tokens_estimated"] == 400
    # The compacted conversation is what got re-rendered.
    user_messages = [m for m in messages if m["role"] == "user"]
    assert user_messages == [{"role": "user", "content": "second"}]
    assert len(comp.compact_calls) == 1


@pytest.mark.asyncio
async def test_prepare_skips_re_render_when_compactor_returns_false() -> None:
    comp = _CompactorStub(
        token_estimate=900,
        should_compact=True,
        compacted=False,
    )
    preparer, _ = _preparer(compactor=comp)
    request = _request()
    conv = _conversation([Message(role=Role.USER, content="hi")])

    messages, metadata = await preparer.prepare(conv, request, _package(), tools=[])

    assert metadata["context_compacted"] is False
    assert metadata["context_tokens_estimated"] == 900
    # Only one estimate call (no re-estimate after the failed compaction).
    assert len(comp.estimate_calls) == 1


@pytest.mark.asyncio
async def test_prepare_passes_reasoning_flags_for_deepseek_provider() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="a",
                metadata={"reasoning_content": "thought"},
            )
        ]
    )

    messages, _ = await preparer.prepare(
        conv,
        _request(provider="deepseek"),
        _package(),
        tools=[],
    )

    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "thought"


@pytest.mark.asyncio
async def test_prepare_passes_reasoning_flags_for_zenmux_provider() -> None:
    preparer, _ = _preparer()
    details = [{"text": "trace"}]
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="a",
                metadata={
                    "reasoning_content": "rc",
                    "zenmux_reasoning_details": details,
                },
            )
        ]
    )

    messages, _ = await preparer.prepare(
        conv,
        _request(provider="zenmux"),
        _package(),
        tools=[],
    )

    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "rc"
    assert assistant_msg["reasoning_details"] == details


@pytest.mark.asyncio
async def test_prepare_omits_reasoning_for_other_providers() -> None:
    preparer, _ = _preparer()
    conv = _conversation(
        [
            Message(
                role=Role.ASSISTANT,
                content="a",
                metadata={
                    "reasoning_content": "thought",
                    "zenmux_reasoning_details": [{"x": 1}],
                },
            )
        ]
    )

    messages, _ = await preparer.prepare(
        conv,
        _request(provider="llama"),
        _package(),
        tools=[],
    )

    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert "reasoning_content" not in assistant_msg
    assert "reasoning_details" not in assistant_msg


@pytest.mark.asyncio
async def test_prepare_forwards_tools_to_token_estimator() -> None:
    preparer, comp = _preparer()
    tools: list[dict[str, Any]] = [
        {"type": "function", "function": {"name": "fs.read"}},
        {"type": "function", "function": {"name": "shell.run"}},
    ]

    await preparer.prepare(_conversation(), _request(), _package(), tools)

    assert comp.estimate_calls
    _, tool_count = comp.estimate_calls[0]
    assert tool_count == 2


@pytest.mark.asyncio
async def test_prepare_preserves_prompt_package_metadata_fields() -> None:
    preparer, _ = _preparer()
    metadata = {
        "prompt_mode": "writing",
        "prompt_analysis_source": "fallback_heuristic",
        "memory_recall_strategy": "noop",
    }

    _, out_metadata = await preparer.prepare(
        _conversation(),
        _request(),
        _package(metadata=metadata),
        tools=[],
    )

    for key, value in metadata.items():
        assert out_metadata[key] == value


# ---------------------------------------------------------------------------
# with_final_answer_reminder
# ---------------------------------------------------------------------------


def test_with_final_answer_reminder_appends_to_existing_system_message() -> None:
    preparer, _ = _preparer()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "hi"},
    ]

    out = preparer.with_final_answer_reminder(messages)

    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith("BASE")
    assert "respond now" in out[0]["content"]
    assert out[1:] == messages[1:]


def test_with_final_answer_reminder_handles_none_content_in_system_message() -> None:
    preparer, _ = _preparer()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": None},
        {"role": "user", "content": "hi"},
    ]

    out = preparer.with_final_answer_reminder(messages)

    # Should not include the literal "None" in the merged content.
    assert "None" not in out[0]["content"]
    assert "respond now" in out[0]["content"]


def test_with_final_answer_reminder_inserts_new_system_when_absent() -> None:
    preparer, _ = _preparer()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "hi"},
    ]

    out = preparer.with_final_answer_reminder(messages)

    assert out[0]["role"] == "system"
    assert "respond now" in out[0]["content"]
    assert out[1:] == messages


def test_with_final_answer_reminder_inserts_when_first_message_is_not_system() -> None:
    preparer, _ = _preparer()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "later-system"},
    ]

    out = preparer.with_final_answer_reminder(messages)

    assert out[0]["role"] == "system"
    assert "later-system" not in out[0]["content"]
    assert out[1:] == messages


def test_with_final_answer_reminder_does_not_mutate_input_list() -> None:
    preparer, _ = _preparer()
    original = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    snapshot = [dict(m) for m in original]

    preparer.with_final_answer_reminder(original)

    assert original == snapshot
# ---------------------------------------------------------------------------
# with_synthesis_reminder
# ---------------------------------------------------------------------------


def test_with_synthesis_reminder_appends_evidence_summary_to_system_message() -> None:
    preparer, _ = _preparer()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "hi"},
    ]

    out = preparer.with_synthesis_reminder(
        messages,
        {
            "objective": "explain the repo",
            "phase": "synthesize",
            "read_files": ["src/app.py", "tests/test_app.py"],
            "coverage_status": {"entrypoints": True, "tests": True},
        },
    )

    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith("BASE")
    assert "Use gathered tool evidence" in out[0]["content"]
    assert "Do not call more tools unless evidence is missing" in out[0]["content"]
    assert "Produce the requested concise final answer" in out[0]["content"]
    assert "Name representative files/functions and uncertainty" in out[0]["content"]
    assert "src/app.py" in out[0]["content"]
    assert out[1:] == messages[1:]


def test_with_synthesis_reminder_does_not_mutate_input_list() -> None:
    preparer, _ = _preparer()
    original = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    snapshot = [dict(m) for m in original]

    preparer.with_synthesis_reminder(original, "read src/app.py")

    assert original == snapshot

