"""Tests for :class:`StreamingTurnExecutor`.

The executor is the orchestration backbone of a streaming chat turn:
it wires together every chat collaborator and emits the same chunk
sequence the legacy ``_stream_completion_turn`` used to emit. These
tests use a single fixture-builder ``_make_executor`` to mock every
collaborator, then exercise distinct code paths -- happy path, no
user-message append, tool-call iteration, permission flow, plan-
approval flow, empty-tool-response retry, tool-loop-limit exceeded,
and ``LLMBackendError`` propagation -- one per test so failures point
straight at the offending branch.

The executor mutates its ``Conversation`` argument heavily (appending
messages, updating ``metadata``, refreshing ``status``). Each test
inspects either the emitted :class:`StreamChunk` sequence or the final
conversation state -- never both at once, again to keep failure
diagnosis straightforward.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.state import (
    MemoryRecallResult,
    PromptPackage,
    PromptPreparation,
)
from personagent.application.use_cases.chat.streaming import StreamingTurnExecutor
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.exceptions import (
    LLMBackendError,
    ToolLoopLimitExceededError,
)
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult

# -- helpers --------------------------------------------------------------


def _context_result() -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(workspace_root="/tmp", cwd="/tmp"),
        user_context=UserContext(current_date="2025-01-01"),
        build_duration_ms=0,
        metadata={"source": "test"},
    )


def _request(**overrides: Any) -> ChatRequestDTO:
    defaults: dict[str, Any] = {
        "message": "hi",
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.5,
        "max_tokens": 128,
    }
    defaults.update(overrides)
    return ChatRequestDTO(**defaults)


def _prompt_package() -> PromptPackage:
    return PromptPackage(
        system_prompt="sys",
        user_context_message=None,
        metadata={},
    )


async def _empty_pass(**_: Any) -> AsyncIterator[StreamChunk]:
    """Default ``AssistantPassRunner.run`` stub: yields nothing, mutates state."""
    if False:
        yield StreamChunk()


def _make_executor(
    *,
    assistant_pass_chunks: list[StreamChunk] | None = None,
    assistant_pass_state_mutator: Any = None,
    tool_call_lists: list[list[ToolCall]] | None = None,
    orchestrator_events: list[Any] | None = None,
    effective_max_iterations: int = 25,
    next_step_suggestion: str | None = None,
    enforce_tools: bool = False,
) -> tuple[StreamingTurnExecutor, dict[str, Any]]:
    """Build a fully mocked executor.

    ``tool_call_lists`` is an iterable of return values for successive
    ``tool_results.parse_calls`` invocations -- each loop iteration pops
    one entry. The last entry (or the only entry, if just one) is
    repeated indefinitely if more iterations occur than entries.
    """
    conversation_repo = AsyncMock()
    conversation_repo.update = AsyncMock()

    memory_recall = AsyncMock()
    memory_recall.recall = AsyncMock(return_value=MemoryRecallResult())

    prompt_surfaces = MagicMock()
    prompt_surfaces.user_message_metadata = MagicMock(return_value={"slash": False})

    def _prepare(request: ChatRequestDTO, _: ContextBuildResult) -> PromptPreparation:
        return PromptPreparation(request=request)

    prompt_surfaces.prepare = MagicMock(side_effect=_prepare)

    prompt_package_builder = MagicMock()
    prompt_package_builder.build = AsyncMock(return_value=_prompt_package())

    media_policy = MagicMock()
    media_policy.enforce_request_policy = MagicMock()

    operational_memory = MagicMock()
    operational_memory.capture_user_message = MagicMock(
        return_value=AsyncMock()()
    )
    operational_memory.capture_tool_result = AsyncMock()
    operational_memory.capture_assistant_text = AsyncMock()
    operational_memory.trigger_memory_extraction = AsyncMock()

    tool_context_builder = MagicMock()
    tool_context_builder.build = MagicMock(return_value={"workspace_root": "/tmp"})

    message_preparer = MagicMock()
    message_preparer.prepare = AsyncMock(
        return_value=(
            [{"role": "user", "content": "hi"}],
            {"context_tokens_estimated": 10, "context_tokens_used": 5},
        )
    )
    message_preparer.with_final_answer_reminder = MagicMock(
        side_effect=lambda msgs: list(msgs)
    )

    chunks = assistant_pass_chunks or []

    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        if assistant_pass_state_mutator is not None:
            assistant_pass_state_mutator(kwargs["state"])
        for chunk in chunks:
            yield chunk

    assistant_pass_runner = MagicMock()
    assistant_pass_runner.run = _pass_run

    stream_chunk_normalizer = MagicMock()
    stream_chunk_normalizer.empty_model_response_notice = MagicMock(
        return_value="empty notice"
    )

    parse_calls_returns = list(tool_call_lists or [[]])

    def _parse_calls(_: Any) -> list[ToolCall]:
        if len(parse_calls_returns) > 1:
            return parse_calls_returns.pop(0)
        return parse_calls_returns[0]

    tool_results = MagicMock()
    tool_results.parse_calls = MagicMock(side_effect=_parse_calls)
    tool_results.is_user_question = MagicMock(return_value=False)
    tool_results.is_plan_approval = MagicMock(return_value=False)
    tool_results.is_plan_mode = MagicMock(return_value=False)
    tool_results.apply_state = MagicMock()
    tool_results.tool_message_from = MagicMock(
        return_value=Message(role=Role.TOOL, content="tool result")
    )
    tool_results.record_pending_question = MagicMock(return_value={})
    tool_results.record_pending_approval = MagicMock(return_value={})
    tool_results.plan_state_from = MagicMock(return_value={})

    after_turn = MagicMock()
    after_turn.run_services = AsyncMock(return_value=next_step_suggestion)
    after_turn.refresh_session_title = AsyncMock()

    build_context_result = AsyncMock(return_value=_context_result())
    resolve_tool_schemas = MagicMock(
        return_value=[{"name": "tool1"}] if enforce_tools else []
    )

    orchestrator = MagicMock()

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        for event in orchestrator_events or []:
            yield event

    orchestrator.execute = _execute
    new_orchestrator = MagicMock(return_value=orchestrator)

    effective_max_tool_iterations = MagicMock(return_value=effective_max_iterations)
    tool_iteration_limit_source = MagicMock(return_value="runtime_config")
    schedule_background = MagicMock()

    executor = StreamingTurnExecutor(
        conversation_repo=conversation_repo,
        memory_recall=memory_recall,
        prompt_surfaces=prompt_surfaces,
        prompt_package_builder=prompt_package_builder,
        media_policy=media_policy,
        operational_memory=operational_memory,
        tool_context_builder=tool_context_builder,
        message_preparer=message_preparer,
        assistant_pass_runner=assistant_pass_runner,
        stream_chunk_normalizer=stream_chunk_normalizer,
        tool_results=tool_results,
        after_turn=after_turn,
        build_context_result=build_context_result,
        resolve_tool_schemas=resolve_tool_schemas,
        new_orchestrator=new_orchestrator,
        effective_max_tool_iterations=effective_max_tool_iterations,
        tool_iteration_limit_source=tool_iteration_limit_source,
        schedule_background=schedule_background,
    )
    deps = {
        "conversation_repo": conversation_repo,
        "memory_recall": memory_recall,
        "prompt_surfaces": prompt_surfaces,
        "prompt_package_builder": prompt_package_builder,
        "media_policy": media_policy,
        "operational_memory": operational_memory,
        "tool_context_builder": tool_context_builder,
        "message_preparer": message_preparer,
        "assistant_pass_runner": assistant_pass_runner,
        "stream_chunk_normalizer": stream_chunk_normalizer,
        "tool_results": tool_results,
        "after_turn": after_turn,
        "build_context_result": build_context_result,
        "resolve_tool_schemas": resolve_tool_schemas,
        "new_orchestrator": new_orchestrator,
        "effective_max_tool_iterations": effective_max_tool_iterations,
        "tool_iteration_limit_source": tool_iteration_limit_source,
        "schedule_background": schedule_background,
    }
    return executor, deps


async def _drain(
    executor: StreamingTurnExecutor,
    conversation: Conversation,
    request: ChatRequestDTO | None = None,
    *,
    append_user_message: bool = True,
    was_empty: bool = False,
    status: str = "building_prompt",
) -> list[StreamChunk]:
    return [
        chunk
        async for chunk in executor.run(
            request or _request(),
            conversation,
            append_user_message=append_user_message,
            was_empty=was_empty,
            status=status,
        )
    ]


# -- happy path -----------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_no_tools_emits_full_chunk_sequence() -> None:
    executor, _ = _make_executor()
    conv = Conversation()

    chunks = await _drain(executor, conv)

    events = [chunk.metadata.get("event") for chunk in chunks]
    assert events == [
        "status",
        "prompt_context",
        "conversation_saved",
    ]


@pytest.mark.asyncio
async def test_happy_path_status_uses_caller_provided_string() -> None:
    executor, _ = _make_executor()
    conv = Conversation()

    chunks = await _drain(executor, conv, status="resuming_after_tool_approval")

    assert chunks[0].metadata == {
        "event": "status",
        "status": "resuming_after_tool_approval",
    }


@pytest.mark.asyncio
async def test_happy_path_prompt_context_chunk_merges_message_preparer_metadata() -> None:
    executor, _ = _make_executor()
    conv = Conversation()

    chunks = await _drain(executor, conv)

    prompt_context = chunks[1].metadata
    assert prompt_context["event"] == "prompt_context"
    assert prompt_context["context_tokens_estimated"] == 10
    assert prompt_context["context_tokens_used"] == 5


@pytest.mark.asyncio
async def test_happy_path_conversation_saved_carries_final_state() -> None:
    def mutate(state: Any) -> None:
        state.finish_reason = "stop"
        state.usage = {"prompt_tokens": 7}
        state.model = "gpt-4o"
        state.provider = "openai"

    executor, _ = _make_executor(
        assistant_pass_state_mutator=mutate,
        next_step_suggestion="suggest something",
    )
    conv = Conversation()

    chunks = await _drain(executor, conv)

    saved = chunks[-1].metadata
    assert saved["event"] == "conversation_saved"
    assert saved["finish_reason"] == "stop"
    assert saved["usage"] == {"prompt_tokens": 7}
    assert saved["model"] == "gpt-4o"
    assert saved["provider"] == "openai"
    assert saved["next_step_suggestion"] == "suggest something"


# -- user-message appending -----------------------------------------------


@pytest.mark.asyncio
async def test_append_user_message_true_persists_user_message_and_schedules_capture() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv, append_user_message=True)

    assert conv.messages[0].role == Role.USER
    assert conv.messages[0].content == "hi"
    deps["conversation_repo"].update.assert_any_await(conv)
    deps["schedule_background"].assert_called_once()


@pytest.mark.asyncio
async def test_append_user_message_false_does_not_persist_user_message() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv, append_user_message=False)

    user_messages = [m for m in conv.messages if m.role == Role.USER]
    assert user_messages == []
    deps["schedule_background"].assert_not_called()


@pytest.mark.asyncio
async def test_append_user_message_clears_permission_mode_when_request_does_not_set_it() -> None:
    executor, _ = _make_executor()
    conv = Conversation()
    conv.metadata["permission_mode"] = "stale-value"

    await _drain(executor, conv)

    assert "permission_mode" not in conv.metadata


@pytest.mark.asyncio
async def test_append_user_message_preserves_permission_mode_when_request_sets_it() -> None:
    executor, _ = _make_executor()
    conv = Conversation()
    conv.metadata["permission_mode"] = "auto"
    req = _request(tool_context={"permission_mode": "auto"})

    await _drain(executor, conv, req)

    assert conv.metadata["permission_mode"] == "auto"


# -- post-turn bookkeeping ------------------------------------------------


@pytest.mark.asyncio
async def test_session_status_idle_at_end_and_last_request_error_cleared() -> None:
    executor, _ = _make_executor()
    conv = Conversation()
    conv.metadata["session_status"] = "running"
    conv.metadata["last_request_error"] = "stale"

    await _drain(executor, conv)

    assert conv.metadata["session_status"] == "idle"
    assert "last_request_error" not in conv.metadata


@pytest.mark.asyncio
async def test_assistant_message_appended_with_full_metadata() -> None:
    def mutate(state: Any) -> None:
        state.content_chunks.append("hello")
        state.usage = {"prompt_tokens": 3}
        state.finish_reason = "stop"
        state.model = "gpt-4o"
        state.provider = "openai"

    executor, _ = _make_executor(assistant_pass_state_mutator=mutate)
    conv = Conversation()

    await _drain(executor, conv)

    assistant = [m for m in conv.messages if m.role == Role.ASSISTANT]
    assert assistant, "no assistant message persisted"
    msg = assistant[-1]
    assert msg.content == "hello"
    assert msg.metadata["finish_reason"] == "stop"
    assert msg.metadata["usage"] == {"prompt_tokens": 3}
    assert msg.metadata["model"] == "gpt-4o"
    assert msg.metadata["provider"] == "openai"


@pytest.mark.asyncio
async def test_next_step_suggestion_chunk_emitted_when_suggestion_present() -> None:
    executor, _ = _make_executor(next_step_suggestion="try next thing")
    conv = Conversation()

    chunks = await _drain(executor, conv)

    next_step_chunks = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "next_step_suggestion"
    ]
    assert len(next_step_chunks) == 1
    assert next_step_chunks[0].metadata["next_step_suggestion"] == "try next thing"


@pytest.mark.asyncio
async def test_next_step_suggestion_chunk_omitted_when_suggestion_absent() -> None:
    executor, _ = _make_executor(next_step_suggestion=None)
    conv = Conversation()

    chunks = await _drain(executor, conv)

    assert not any(
        chunk.metadata.get("event") == "next_step_suggestion" for chunk in chunks
    )


@pytest.mark.asyncio
async def test_after_turn_refresh_session_title_invoked_with_was_empty_flag() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv, was_empty=True)

    deps["after_turn"].refresh_session_title.assert_awaited_once_with(
        conv, was_empty=True
    )


@pytest.mark.asyncio
async def test_operational_memory_trigger_invoked_after_turn() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv)

    deps["operational_memory"].trigger_memory_extraction.assert_awaited_once()


# -- tool-iteration loop --------------------------------------------------


@pytest.mark.asyncio
async def test_tool_loop_limit_exceeded_yields_chunk_and_marks_session_error() -> None:
    executor, _ = _make_executor(effective_max_iterations=0)
    conv = Conversation()

    chunks = await _drain(executor, conv)

    limit_chunks = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "tool_loop_limit_exceeded"
    ]
    assert len(limit_chunks) == 1
    assert limit_chunks[0].metadata["limit"] == 0
    assert limit_chunks[0].metadata["source"] == "runtime_config"
    saved = chunks[-1].metadata
    assert saved["finish_reason"] == "tool_loop_limit_exceeded"


@pytest.mark.asyncio
async def test_tool_calls_iterate_once_then_break_when_no_tool_context() -> None:
    """Tools enabled but ``tool_context`` is ``None`` -> loop breaks after first pass.

    ``resolve_tool_schemas`` returning [] keeps ``tool_context`` ``None``,
    so even if ``parse_calls`` would return calls, the loop must exit.
    """
    executor, deps = _make_executor(
        tool_call_lists=[
            [ToolCall(id="t1", name="noop", arguments={})],
        ],
    )
    conv = Conversation()

    await _drain(executor, conv)

    deps["new_orchestrator"].assert_not_called()


@pytest.mark.asyncio
async def test_tools_present_with_no_tool_calls_does_not_invoke_orchestrator() -> None:
    executor, deps = _make_executor(enforce_tools=True, tool_call_lists=[[]])
    conv = Conversation()

    await _drain(executor, conv)

    deps["new_orchestrator"].assert_not_called()


# -- error propagation ----------------------------------------------------


@pytest.mark.asyncio
async def test_llm_backend_error_marks_session_error_and_propagates() -> None:
    executor, deps = _make_executor()

    async def _explode(**_: Any) -> AsyncIterator[StreamChunk]:
        raise LLMBackendError("boom")
        yield StreamChunk()  # pragma: no cover

    deps["assistant_pass_runner"].run = _explode
    conv = Conversation()

    with pytest.raises(LLMBackendError):
        await _drain(executor, conv)

    assert conv.metadata["session_status"] == "error"
    assert conv.metadata["last_request_error"] == "boom"


@pytest.mark.asyncio
async def test_tool_loop_limit_falls_through_to_post_loop_cleanup() -> None:
    executor, deps = _make_executor(effective_max_iterations=0)
    conv = Conversation()

    await _drain(executor, conv)

    deps["after_turn"].run_services.assert_awaited_once()
    deps["conversation_repo"].update.assert_awaited()


# -- empty-tool-response retry -------------------------------------------


@pytest.mark.asyncio
async def test_empty_tool_response_retry_yields_status_and_notice() -> None:
    """When tools executed but the second assistant pass produces no
    visible output, the executor must retry once and, if still empty,
    emit the canonical notice chunk."""
    call_count = {"n": 0}

    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            kwargs["state"].tool_calls = [
                {"id": "t1", "function": {"name": "noop", "arguments": "{}"}}
            ]
            kwargs["state"].finish_reason = "tool_calls"
        else:
            # second + third passes are empty -> retry branch activates
            kwargs["state"].finish_reason = "stop"
        if False:
            yield StreamChunk()  # pragma: no cover

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        event = MagicMock()
        event.event = "tool_completed"
        event.call = ToolCall(id="t1", name="noop", arguments={})
        event.result = ToolResult(
            tool_call_id="t1",
            tool_name="noop",
            content="ok",
            status=ToolExecutionStatus.COMPLETED,
        )
        event.to_stream_metadata = MagicMock(return_value={"event": "tool_completed"})
        yield event

    executor, deps = _make_executor(
        enforce_tools=True,
        tool_call_lists=[
            [ToolCall(id="t1", name="noop", arguments={})],
            [],
        ],
    )
    deps["assistant_pass_runner"].run = _pass_run
    deps["new_orchestrator"].return_value.execute = _execute
    conv = Conversation()

    chunks = await _drain(executor, conv)

    retry_status = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("status") == "retrying_empty_tool_response"
    ]
    assert len(retry_status) == 1
    empty_notice = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "empty_model_response"
    ]
    assert len(empty_notice) == 1


# -- permission flow ------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_required_user_question_marks_pending_and_finishes() -> None:
    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        kwargs["state"].tool_calls = [
            {"id": "t1", "function": {"name": "ask", "arguments": "{}"}}
        ]
        kwargs["state"].finish_reason = "tool_calls"
        if False:
            yield StreamChunk()  # pragma: no cover

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        event = MagicMock()
        event.event = "permission_required"
        event.call = ToolCall(id="t1", name="ask", arguments={})
        event.result = ToolResult(
            tool_call_id="t1",
            tool_name="ask",
            content="please confirm",
            status=ToolExecutionStatus.PERMISSION_REQUIRED,
        )
        event.to_stream_metadata = MagicMock(
            return_value={"event": "permission_required"}
        )
        yield event

    executor, deps = _make_executor(
        enforce_tools=True,
        tool_call_lists=[[ToolCall(id="t1", name="ask", arguments={})]],
    )
    deps["assistant_pass_runner"].run = _pass_run
    deps["new_orchestrator"].return_value.execute = _execute
    deps["tool_results"].is_user_question = MagicMock(return_value=True)
    conv = Conversation()

    chunks = await _drain(executor, conv)

    ask_user_question = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "ask_user_question"
    ]
    assert len(ask_user_question) == 1
    saved = chunks[-1].metadata
    assert saved["finish_reason"] == "user_input_required"
    assert conv.metadata["session_status"] == "idle"


@pytest.mark.asyncio
async def test_permission_required_non_question_records_pending_approval() -> None:
    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        kwargs["state"].tool_calls = [
            {"id": "t1", "function": {"name": "edit", "arguments": "{}"}}
        ]
        kwargs["state"].finish_reason = "tool_calls"
        if False:
            yield StreamChunk()  # pragma: no cover

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        event = MagicMock()
        event.event = "permission_required"
        event.call = ToolCall(id="t1", name="edit", arguments={})
        event.result = ToolResult(
            tool_call_id="t1",
            tool_name="edit",
            content="permission needed",
            status=ToolExecutionStatus.PERMISSION_REQUIRED,
        )
        event.to_stream_metadata = MagicMock(
            return_value={"event": "permission_required"}
        )
        yield event

    executor, deps = _make_executor(
        enforce_tools=True,
        tool_call_lists=[[ToolCall(id="t1", name="edit", arguments={})]],
    )
    deps["assistant_pass_runner"].run = _pass_run
    deps["new_orchestrator"].return_value.execute = _execute
    conv = Conversation()

    chunks = await _drain(executor, conv)

    saved = chunks[-1].metadata
    assert saved["finish_reason"] == "permission_required"
    deps["tool_results"].record_pending_approval.assert_called_once()


# -- plan-approval flow ---------------------------------------------------


@pytest.mark.asyncio
async def test_plan_approval_event_emitted_when_tool_result_signals_plan_approval() -> None:
    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        kwargs["state"].tool_calls = [
            {
                "id": "t1",
                "function": {"name": "ExitPlanMode", "arguments": "{}"},
            }
        ]
        kwargs["state"].finish_reason = "tool_calls"
        if False:
            yield StreamChunk()  # pragma: no cover

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        event = MagicMock()
        event.event = "tool_completed"
        event.call = ToolCall(id="t1", name="ExitPlanMode", arguments={})
        event.result = ToolResult(
            tool_call_id="t1",
            tool_name="ExitPlanMode",
            content="plan ready",
            status=ToolExecutionStatus.COMPLETED,
        )
        event.to_stream_metadata = MagicMock(return_value={"event": "tool_completed"})
        yield event

    executor, deps = _make_executor(
        enforce_tools=True,
        tool_call_lists=[[ToolCall(id="t1", name="ExitPlanMode", arguments={})]],
    )
    deps["assistant_pass_runner"].run = _pass_run
    deps["new_orchestrator"].return_value.execute = _execute
    deps["tool_results"].is_plan_approval = MagicMock(return_value=True)
    deps["tool_results"].plan_state_from = MagicMock(
        return_value={"steps": ["a", "b"], "mode": "ready"}
    )
    conv = Conversation()

    chunks = await _drain(executor, conv)

    plan_approval = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "plan_approval_requested"
    ]
    assert plan_approval, "expected plan_approval_requested event"
    saved = chunks[-1].metadata
    assert saved["finish_reason"] == "plan_approval_requested"


@pytest.mark.asyncio
async def test_plan_mode_event_emitted_when_tool_result_signals_plan_mode() -> None:
    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        kwargs["state"].tool_calls = [
            {
                "id": "t1",
                "function": {"name": "EnterPlanMode", "arguments": "{}"},
            }
        ]
        kwargs["state"].finish_reason = "tool_calls"
        if False:
            yield StreamChunk()  # pragma: no cover

    async def _execute(_calls: Any, _ctx: Any) -> AsyncIterator[Any]:
        event = MagicMock()
        event.event = "tool_completed"
        event.call = ToolCall(id="t1", name="EnterPlanMode", arguments={})
        event.result = ToolResult(
            tool_call_id="t1",
            tool_name="EnterPlanMode",
            content="plan mode active",
            status=ToolExecutionStatus.COMPLETED,
        )
        event.to_stream_metadata = MagicMock(return_value={"event": "tool_completed"})
        yield event

    executor, deps = _make_executor(
        enforce_tools=True,
        tool_call_lists=[
            [ToolCall(id="t1", name="EnterPlanMode", arguments={})],
            [],
        ],
    )
    deps["assistant_pass_runner"].run = _pass_run
    deps["new_orchestrator"].return_value.execute = _execute
    deps["tool_results"].is_plan_mode = MagicMock(return_value=True)
    deps["tool_results"].plan_state_from = MagicMock(
        return_value={"steps": [], "mode": "active"}
    )
    conv = Conversation()

    chunks = await _drain(executor, conv)

    plan_mode_chunks = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("event") == "plan_mode_changed"
    ]
    assert plan_mode_chunks, "expected plan_mode_changed event"


# -- collaborator wiring sanity ------------------------------------------


@pytest.mark.asyncio
async def test_media_policy_enforce_request_policy_invoked() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv)

    deps["media_policy"].enforce_request_policy.assert_called_once()


@pytest.mark.asyncio
async def test_message_preparer_prepare_invoked_with_tools_arg() -> None:
    executor, deps = _make_executor(enforce_tools=True, tool_call_lists=[[]])
    conv = Conversation()

    await _drain(executor, conv)

    args, _ = deps["message_preparer"].prepare.call_args
    # signature: prepare(conversation, request, prompt_package, tools)
    assert args[3] == [{"name": "tool1"}]


@pytest.mark.asyncio
async def test_assistant_pass_runner_called_with_iteration_zero() -> None:
    captured_kwargs: dict[str, Any] = {}

    async def _pass_run(**kwargs: Any) -> AsyncIterator[StreamChunk]:
        captured_kwargs.update(kwargs)
        if False:
            yield StreamChunk()  # pragma: no cover

    executor, deps = _make_executor()
    deps["assistant_pass_runner"].run = _pass_run
    conv = Conversation()

    await _drain(executor, conv)

    assert captured_kwargs["iteration"] == 0
    assert captured_kwargs["conversation_id"] == str(conv.id)
    assert isinstance(captured_kwargs["seen_tool_call_ids"], set)


@pytest.mark.asyncio
async def test_resume_after_tool_approval_does_not_call_capture_user_message() -> None:
    executor, deps = _make_executor()
    conv = Conversation()

    await _drain(executor, conv, append_user_message=False)

    deps["operational_memory"].capture_user_message.assert_not_called()


# -- tool_loop limit error class --------------------------------------


@pytest.mark.asyncio
async def test_tool_loop_limit_error_class_raised_and_caught_internally() -> None:
    """The executor raises ``ToolLoopLimitExceededError`` internally and
    handles it; the caller should not see it propagate."""
    executor, _ = _make_executor(effective_max_iterations=0)
    conv = Conversation()

    # Must complete without raising
    try:
        await _drain(executor, conv)
    except ToolLoopLimitExceededError:
        pytest.fail("ToolLoopLimitExceededError must be caught internally")
