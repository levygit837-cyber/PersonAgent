"""Tests for :class:`ToolResultHandler`.

The handler coordinates the *result* side of the chat use case's tool
loop: parsing OpenAI tool_calls, renaming duplicate ids, running the
orchestrator, capturing operational memory, mutating the conversation
(plan state, todos, pending approvals, pending user questions, tool
messages), and computing the forwarded streaming finish reason.

These tests pin the contract method-by-method using light stubs that
record their calls.  No real orchestrator, memory service, or
:class:`Conversation` repository is involved -- each test exercises a
single behaviour rule.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
)
from personagent.application.use_cases.chat.tooling.tool_results import ToolResultHandler
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    ToolUseContext,
)

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _OrchestratorStub:
    """Records ``execute_collect`` calls and returns a canned list."""

    def __init__(self, results: list[ToolResult] | None = None) -> None:
        self.results = results or []
        self.calls: list[tuple[list[ToolCall], ToolUseContext]] = []

    async def execute_collect(
        self,
        calls: list[ToolCall],
        context: ToolUseContext,
    ) -> list[ToolResult]:
        self.calls.append((list(calls), context))
        return list(self.results)


class _OperationalMemoryStub:
    """Records ``capture_tool_result`` invocations."""

    def __init__(self) -> None:
        self.captures: list[
            tuple[
                ChatRequestDTO | None,
                Conversation,
                ToolCall,
                ToolResult,
                ToolUseContext,
            ]
        ] = []

    async def capture_tool_result(
        self,
        request: ChatRequestDTO | None,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        tool_context: ToolUseContext,
    ) -> None:
        self.captures.append((request, conversation, call, result, tool_context))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _handler(
    *,
    orchestrator: _OrchestratorStub | None = None,
    memory: _OperationalMemoryStub | None = None,
) -> tuple[ToolResultHandler, _OrchestratorStub, _OperationalMemoryStub]:
    orch = orchestrator or _OrchestratorStub()
    mem = memory or _OperationalMemoryStub()
    handler = ToolResultHandler(
        orchestrator_factory=lambda: orch,
        operational_memory=mem,  # type: ignore[arg-type]
    )
    return handler, orch, mem


def _conversation() -> Conversation:
    return Conversation(id=uuid4(), title="t", messages=[], metadata={})


def _tool_context(**overrides: Any) -> ToolUseContext:
    base = ToolUseContext(
        conversation_id="conv-1",
        workspace_root=Path("/ws"),
        cwd=Path("/ws"),
        allowed_roots=(Path("/ws"),),
    )
    return replace(base, **overrides) if overrides else base


def _request(**overrides: Any) -> ChatRequestDTO:
    base_kwargs: dict[str, Any] = {
        "message": "hi",
        "system_prompt": "PROMPT",
        "temperature": 0.4,
        "max_tokens": 256,
        "provider": "llama",
        "model": "test-model",
        "prompt_mode": "exploring",
        "reasoning_level": "medium",
        "reasoning_budget_tokens": 1024,
        "tools_enabled": True,
        "allowed_tools": ["fs.read"],
        "tool_context": {"workspace_root": "/ws"},
        "max_tool_iterations": 5,
        "context_attachments": [],
    }
    base_kwargs.update(overrides)
    return ChatRequestDTO(**base_kwargs)


def _call(call_id: str = "call-1", name: str = "fs.read", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {"a": 1})


def _result(
    *,
    tool_call_id: str = "call-1",
    tool_name: str = "fs.read",
    content: str = "ok",
    status: ToolExecutionStatus = ToolExecutionStatus.COMPLETED,
    is_error: bool = False,
    data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=content,
        status=status,
        is_error=is_error,
        data=data or {},
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# parse_calls
# ---------------------------------------------------------------------------


def test_parse_calls_returns_empty_list_when_input_is_none() -> None:
    handler, _, _ = _handler()
    assert handler.parse_calls(None) == []


def test_parse_calls_returns_empty_list_when_input_is_empty() -> None:
    handler, _, _ = _handler()
    assert handler.parse_calls([]) == []


def test_parse_calls_drops_calls_without_id_or_name() -> None:
    handler, _, _ = _handler()
    raw = [
        {"id": "good", "type": "function", "function": {"name": "fs.read", "arguments": "{}"}},
        {"id": "", "type": "function", "function": {"name": "fs.read", "arguments": "{}"}},
        {"id": "missing-name", "type": "function", "function": {"name": "", "arguments": "{}"}},
    ]

    parsed = handler.parse_calls(raw)

    assert [c.id for c in parsed] == ["good"]


def test_parse_calls_uses_from_openai_for_arguments() -> None:
    handler, _, _ = _handler()
    raw = [
        {
            "id": "abc",
            "type": "function",
            "function": {"name": "fs.read", "arguments": "{\"path\": \"/etc/hosts\"}"},
        },
    ]

    parsed = handler.parse_calls(raw)

    assert len(parsed) == 1
    assert parsed[0].arguments == {"path": "/etc/hosts"}


# ---------------------------------------------------------------------------
# unique_call_ids
# ---------------------------------------------------------------------------


def test_unique_call_ids_passes_through_unseen_ids() -> None:
    handler, _, _ = _handler()
    seen: set[str] = set()
    out = handler.unique_call_ids(
        [{"id": "a"}, {"id": "b"}],
        seen,
        iteration=0,
    )

    assert [c["id"] for c in out] == ["a", "b"]
    assert seen == {"a", "b"}


def test_unique_call_ids_renames_duplicates_and_records_original() -> None:
    handler, _, _ = _handler()
    seen: set[str] = {"a"}

    out = handler.unique_call_ids(
        [{"id": "a"}],
        seen,
        iteration=3,
    )

    assert out[0]["id"] == "a-3-0"
    assert out[0]["extra_content"] == {"original_tool_call_id": "a"}
    assert "a-3-0" in seen


def test_unique_call_ids_falls_back_when_id_is_missing() -> None:
    handler, _, _ = _handler()
    seen: set[str] = set()
    out = handler.unique_call_ids(
        [{"id": ""}],
        seen,
        iteration=2,
    )

    assert out[0]["id"] == "tool-call-2-0"
    assert "tool-call-2-0" in seen


def test_unique_call_ids_keeps_other_fields_when_renaming() -> None:
    handler, _, _ = _handler()
    out = handler.unique_call_ids(
        [{"id": "a", "function": {"name": "fs.read"}}],
        {"a"},
        iteration=1,
    )

    assert out[0]["function"] == {"name": "fs.read"}
    assert out[0]["id"] != "a"


# ---------------------------------------------------------------------------
# tool_message_from
# ---------------------------------------------------------------------------


def test_tool_message_from_carries_status_and_metadata() -> None:
    handler, _, _ = _handler()
    result = _result(
        content="hello",
        data={"k": "v"},
        metadata={"trace": "abc"},
    )

    msg = handler.tool_message_from(result)

    assert msg.role == Role.TOOL
    assert msg.content == "hello"
    assert msg.tool_call_id == "call-1"
    assert msg.metadata["tool_name"] == "fs.read"
    assert msg.metadata["status"] == "completed"
    assert msg.metadata["is_error"] is False
    assert msg.metadata["data"] == {"k": "v"}
    assert msg.metadata["trace"] == "abc"


def test_tool_message_from_marks_error_status() -> None:
    handler, _, _ = _handler()
    result = _result(status=ToolExecutionStatus.ERROR, is_error=True)

    msg = handler.tool_message_from(result)

    assert msg.metadata["status"] == "error"
    assert msg.metadata["is_error"] is True


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_appends_completed_results_and_captures_memory() -> None:
    call = _call("c1", "fs.read")
    result = _result(tool_call_id="c1", tool_name="fs.read", content="content")
    handler, orch, mem = _handler(orchestrator=_OrchestratorStub(results=[result]))
    conversation = _conversation()

    await handler.execute([call], _tool_context(), conversation)

    assert len(conversation.messages) == 1
    assert conversation.messages[0].role == Role.TOOL
    assert conversation.messages[0].tool_call_id == "c1"
    assert orch.calls and orch.calls[0][0] == [call]
    assert mem.captures and mem.captures[0][2].id == "c1"


@pytest.mark.asyncio
async def test_execute_skips_appending_for_permission_required_results() -> None:
    call = _call("c1", "fs.write")
    result = _result(
        tool_call_id="c1",
        tool_name="fs.write",
        status=ToolExecutionStatus.PERMISSION_REQUIRED,
    )
    handler, _, _ = _handler(orchestrator=_OrchestratorStub(results=[result]))
    conversation = _conversation()

    await handler.execute([call], _tool_context(), conversation)

    assert conversation.messages == []


@pytest.mark.asyncio
async def test_execute_applies_plan_mode_state_from_result_data() -> None:
    call = _call("c1", "plan_mode_tool")
    result = _result(
        tool_call_id="c1",
        tool_name="plan_mode_tool",
        data={
            "type": "plan_mode",
            "active": True,
            "plan_id": "p-1",
            "plan_content": "do it",
        },
    )
    handler, _, _ = _handler(orchestrator=_OrchestratorStub(results=[result]))
    conversation = _conversation()

    await handler.execute([call], _tool_context(), conversation)

    plan_state = conversation.metadata["plan_mode"]
    assert plan_state["active"] is True
    assert plan_state["plan_id"] == "p-1"
    assert plan_state["plan_content"] == "do it"


@pytest.mark.asyncio
async def test_execute_writes_todos_from_result_data() -> None:
    call = _call("c1", "todos_tool")
    todos = [{"task": "foo", "done": False}]
    result = _result(
        tool_call_id="c1",
        tool_name="todos_tool",
        data={"type": "todos", "todos": todos},
    )
    handler, _, _ = _handler(orchestrator=_OrchestratorStub(results=[result]))
    conversation = _conversation()

    await handler.execute([call], _tool_context(), conversation)

    assert conversation.metadata["todos"] == todos


@pytest.mark.asyncio
async def test_execute_skips_memory_capture_when_call_id_unknown() -> None:
    call = _call("c1")
    orphan = _result(tool_call_id="other", tool_name="fs.read")
    handler, _, mem = _handler(orchestrator=_OrchestratorStub(results=[orphan]))
    conversation = _conversation()

    await handler.execute([call], _tool_context(), conversation)

    assert mem.captures == []
    # but the result still becomes a message
    assert len(conversation.messages) == 1


@pytest.mark.asyncio
async def test_execute_invokes_orchestrator_factory_each_call() -> None:
    call_count = {"n": 0}

    def factory() -> _OrchestratorStub:
        call_count["n"] += 1
        return _OrchestratorStub()

    handler = ToolResultHandler(
        orchestrator_factory=factory,  # type: ignore[arg-type]
        operational_memory=_OperationalMemoryStub(),  # type: ignore[arg-type]
    )
    await handler.execute([], _tool_context(), _conversation())
    await handler.execute([], _tool_context(), _conversation())

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# apply_state
# ---------------------------------------------------------------------------


def test_apply_state_writes_plan_mode_from_explicit_state_dict() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(
        data={
            "type": "plan_mode",
            "state": {
                "active": True,
                "status": "draft",
                "plan_id": "p-99",
                "plan_content": "yo",
            },
        },
    )

    handler.apply_state(result, conversation)

    assert conversation.metadata["plan_mode"]["plan_id"] == "p-99"
    assert conversation.metadata["plan_mode"]["status"] == "draft"


def test_apply_state_inferred_status_when_active_without_status() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(data={"type": "plan_mode", "active": True})

    handler.apply_state(result, conversation)

    plan_state = conversation.metadata["plan_mode"]
    assert plan_state["status"] == "draft"
    assert plan_state["active"] is True


def test_apply_state_inferred_status_when_inactive() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(data={"type": "plan_mode", "active": False})

    handler.apply_state(result, conversation)

    plan_state = conversation.metadata["plan_mode"]
    assert plan_state["status"] == "inactive"


def test_apply_state_ignores_unknown_types() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    handler.apply_state(_result(data={"type": "unknown"}), conversation)
    assert "plan_mode" not in conversation.metadata
    assert "todos" not in conversation.metadata


# ---------------------------------------------------------------------------
# is_* classifiers
# ---------------------------------------------------------------------------


def test_is_plan_mode_true_for_plan_mode_results() -> None:
    handler, _, _ = _handler()
    assert handler.is_plan_mode(_result(data={"type": "plan_mode"})) is True


def test_is_plan_mode_false_for_other_results() -> None:
    handler, _, _ = _handler()
    assert handler.is_plan_mode(_result(data={"type": "todos"})) is False
    assert handler.is_plan_mode(_result(data={})) is False


def test_is_plan_approval_requires_request_approval_action() -> None:
    handler, _, _ = _handler()
    plain = _result(data={"type": "plan_mode"})
    request_approval = _result(
        data={"type": "plan_mode", "action": "request_approval"}
    )
    other_action = _result(data={"type": "plan_mode", "action": "draft"})
    assert handler.is_plan_approval(plain) is False
    assert handler.is_plan_approval(request_approval) is True
    assert handler.is_plan_approval(other_action) is False


def test_is_user_question_recognises_ask_user_question() -> None:
    handler, _, _ = _handler()
    assert (
        handler.is_user_question(_result(data={"type": "ask_user_question"})) is True
    )
    assert handler.is_user_question(_result(data={"type": "todos"})) is False


# ---------------------------------------------------------------------------
# plan_state_from
# ---------------------------------------------------------------------------


def test_plan_state_from_uses_state_dict_when_present() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(
        data={
            "type": "plan_mode",
            "state": {"active": True, "plan_id": "p-7"},
        },
    )

    state = handler.plan_state_from(result, conversation)

    assert state["plan_id"] == "p-7"
    assert state["active"] is True


def test_plan_state_from_falls_back_to_conversation_metadata() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    conversation.metadata["plan_mode"] = {"active": True, "plan_id": "from-meta"}

    state = handler.plan_state_from(_result(data={"type": "plan_mode"}), conversation)

    assert state["plan_id"] == "from-meta"


# ---------------------------------------------------------------------------
# record_pending_approval
# ---------------------------------------------------------------------------


def test_record_pending_approval_creates_new_id_when_no_existing() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request()
    call = _call()
    result = _result(content="needs approval")

    out = handler.record_pending_approval(conversation, call, result, request)

    assert out["approval_id"]
    assert conversation.metadata[PENDING_TOOL_APPROVAL_KEY]["tool_call_id"] == "call-1"
    assert conversation.metadata[PENDING_TOOL_APPROVAL_KEY]["status"] == "awaiting_approval"
    assert (
        conversation.metadata[PENDING_TOOL_APPROVAL_KEY]["resume_request"]["model"]
        == request.model
    )


def test_record_pending_approval_reuses_existing_id_for_same_tool_call() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request()
    call = _call()
    conversation.metadata[PENDING_TOOL_APPROVAL_KEY] = {
        "approval_id": "preexisting",
        "tool_call_id": call.id,
    }

    out = handler.record_pending_approval(conversation, call, _result(), request)

    assert out["approval_id"] == "preexisting"


def test_record_pending_approval_attaches_browser_arbiter_when_present() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request()
    call = _call()
    result = _result(
        content="proposal",
        metadata={
            "browser_action_arbiter": {
                "browser_id": "browser-1",
                "policy": "ask",
                "policy_decision": "ask",
                "action": "open",
                "tool_name": "browser",
                "mode": "ask",
                "target": {"selector": "#btn"},
            }
        },
    )

    handler.record_pending_approval(conversation, call, result, request)

    # The helper writes the proposal under the browser_cooperation root,
    # keyed by browser_id.
    cooperation = conversation.metadata["browser_cooperation"]
    assert "browser-1" in cooperation
    proposals = cooperation["browser-1"]["pending_action_proposals"]
    assert proposals
    proposal = proposals[0]
    assert proposal["target"] == {"selector": "#btn"}
    assert proposal["status"] == "awaiting_approval"


def test_record_pending_approval_skips_arbiter_attachment_without_browser_id() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request()
    call = _call()
    result = _result(
        metadata={
            "browser_action_arbiter": {
                # Missing browser_id -> helper bails out.
                "policy": "ask",
            }
        },
    )

    handler.record_pending_approval(conversation, call, result, request)

    assert "browser_cooperation" not in conversation.metadata


def test_record_pending_approval_ignores_non_dict_arbiter_metadata() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request()
    call = _call()
    result = _result(metadata={"browser_action_arbiter": "not-a-dict"})

    handler.record_pending_approval(conversation, call, result, request)

    # No-op on cooperation metadata; the pending approval is still set.
    assert "browser_cooperation" not in conversation.metadata
    assert PENDING_TOOL_APPROVAL_KEY in conversation.metadata


def test_record_pending_approval_serialises_full_resume_request() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    request = _request(
        reasoning_level="high",
        reasoning_budget_tokens=2048,
        allowed_tools=["fs.read", "shell.run"],
    )
    call = _call()

    handler.record_pending_approval(conversation, call, _result(), request)

    pending = conversation.metadata[PENDING_TOOL_APPROVAL_KEY]
    assert pending["resume_request"]["reasoning_level"] == "high"
    assert pending["resume_request"]["reasoning_budget_tokens"] == 2048
    assert pending["resume_request"]["allowed_tools"] == ["fs.read", "shell.run"]
    assert pending["resume_request"]["context_attachments"] == []


# ---------------------------------------------------------------------------
# record_pending_question
# ---------------------------------------------------------------------------


def test_record_pending_question_uses_data_approval_id_when_provided() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(data={"approval_id": "from-data", "questions": [{"id": "q1"}]})

    out = handler.record_pending_question(conversation, _call(), result, _request())

    assert out["approval_id"] == "from-data"
    assert conversation.metadata[PENDING_USER_QUESTION_KEY]["approval_id"] == "from-data"


def test_record_pending_question_generates_id_when_missing() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(data={"questions": [{"id": "q1"}]})

    out = handler.record_pending_question(conversation, _call(), result, _request())

    assert out["approval_id"]
    assert out["approval_id"] != ""


def test_record_pending_question_uses_default_title_when_missing() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(data={"questions": [{"id": "q1"}]})

    out = handler.record_pending_question(conversation, _call(), result, _request())

    assert out["question_title"] == "User input requested"


def test_record_pending_question_passes_through_title_and_questions() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()
    result = _result(
        data={
            "questions": [{"id": "q1", "text": "ok?"}],
            "title": "Approve?",
        },
    )

    out = handler.record_pending_question(conversation, _call(), result, _request())

    assert out["question_title"] == "Approve?"
    assert out["questions"] == [{"id": "q1", "text": "ok?"}]


def test_record_pending_question_persists_to_conversation_metadata() -> None:
    handler, _, _ = _handler()
    conversation = _conversation()

    handler.record_pending_question(
        conversation,
        _call(),
        _result(data={"questions": [], "title": "Hi"}),
        _request(),
    )

    assert PENDING_USER_QUESTION_KEY in conversation.metadata
    assert conversation.metadata[PENDING_USER_QUESTION_KEY]["status"] == "awaiting_answer"


# ---------------------------------------------------------------------------
# forwarded_finish_reason
# ---------------------------------------------------------------------------


def test_forwarded_finish_reason_swallows_tool_calls() -> None:
    handler, _, _ = _handler()
    chunk = StreamChunk(finish_reason="tool_calls")
    assert handler.forwarded_finish_reason(chunk, has_pending_tool_calls=False) is None


def test_forwarded_finish_reason_swallows_pending_empty_terminal_chunk() -> None:
    handler, _, _ = _handler()
    chunk = StreamChunk(finish_reason="stop", content="", reasoning_content="")
    assert handler.forwarded_finish_reason(chunk, has_pending_tool_calls=True) is None


def test_forwarded_finish_reason_passes_through_when_content_present() -> None:
    handler, _, _ = _handler()
    chunk = StreamChunk(finish_reason="stop", content="hi")
    assert (
        handler.forwarded_finish_reason(chunk, has_pending_tool_calls=True) == "stop"
    )


def test_forwarded_finish_reason_passes_through_with_no_pending_calls() -> None:
    handler, _, _ = _handler()
    chunk = StreamChunk(finish_reason="length", content="")
    assert (
        handler.forwarded_finish_reason(chunk, has_pending_tool_calls=False) == "length"
    )


def test_forwarded_finish_reason_returns_none_for_none_finish() -> None:
    handler, _, _ = _handler()
    chunk = StreamChunk(finish_reason=None)
    assert handler.forwarded_finish_reason(chunk, has_pending_tool_calls=False) is None
