"""Tests for chat routes helpers module."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from personagent.adapters.api.routes.chat.helpers import (
    REASONING_BUDGETS,
    ChatRequest,
    PlanDecisionRequest,
    ToolApprovalDecisionRequest,
    UserQuestionResponseRequest,
    _last_user_message,
    _require_plan_approval,
    _require_tool_approval,
    _require_user_question,
    _update_plan_approval_artifact,
    encode_sse,
    resolve_next_step_suggestion_service,
    resolve_prompt_mode,
    resolve_provider,
    resolve_reasoning_budget,
    resolve_session_memory_service,
    resolve_team_workspace_id,
    resolve_tool_context,
)
from personagent.domain.conversation.models import Role

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubMessage:
    def __init__(self, role: Role, content: str, metadata: dict[str, Any] | None = None):
        self.role = role
        self.content = content
        self.metadata = metadata or {}


class _StubConversation:
    def __init__(self, messages: list[_StubMessage] | None = None):
        self.messages = messages or []


class _StubSettings:
    chat_session_memory_updates_enabled = True
    chat_next_step_suggestions_enabled = True
    nvidia_default_model = "nvidia-model"
    deepseek_default_model = "deepseek-model"
    zenmux_default_model = "zenmux-model"
    vertex_default_model = "vertex-model"
    kimi_default_model = "kimi-model"
    codex_default_model = "codex-model"
    tool_workspace_root_path = "/default/workspace"


class _StubDIContainer:
    def __init__(self, settings: _StubSettings | None = None) -> None:
        self.settings = settings or _StubSettings()
        self.create_session_memory_service_calls: list = []
        self.create_next_step_suggestion_service_calls: list = []

    def create_session_memory_service(self, update_backend: Any) -> Any:
        self.create_session_memory_service_calls.append(update_backend)
        return f"session_memory_service({update_backend})"

    def create_next_step_suggestion_service(self, llm_backend: Any) -> Any:
        self.create_next_step_suggestion_service_calls.append(llm_backend)
        return f"next_step_service({llm_backend})"


class _StubLLMBackend:
    pass


# ---------------------------------------------------------------------------
# encode_sse
# ---------------------------------------------------------------------------

class TestEncodeSse:
    def test_encodes_simple_dict_to_sse_format(self):
        result = encode_sse({"event": "delta", "content": "hello"})
        assert result == 'data: {"event": "delta", "content": "hello"}\n\n'

    def test_preserves_unicode_characters(self):
        result = encode_sse({"content": "coração"})
        assert "coração" in result


# ---------------------------------------------------------------------------
# resolve_reasoning_budget
# ---------------------------------------------------------------------------

class TestResolveReasoningBudget:
    def test_returns_explicit_budget_when_set(self):
        request = ChatRequest(message="hi", reasoning_budget_tokens=5000)
        assert resolve_reasoning_budget(request) == 5000

    def test_returns_none_when_level_is_none_and_no_explicit_budget(self):
        request = ChatRequest(message="hi")
        assert resolve_reasoning_budget(request) is None

    def test_resolves_low_level(self):
        request = ChatRequest(message="hi", reasoning_level="low")
        assert resolve_reasoning_budget(request) == REASONING_BUDGETS["low"]

    def test_resolves_high_level(self):
        request = ChatRequest(message="hi", reasoning_level="high")
        assert resolve_reasoning_budget(request) == REASONING_BUDGETS["high"]

    def test_raises_for_invalid_level(self):
        request = ChatRequest(message="hi", reasoning_level="extreme")
        with pytest.raises(HTTPException) as exc:
            resolve_reasoning_budget(request)
        assert exc.value.status_code == 400

    def test_explicit_budget_overrides_level(self):
        request = ChatRequest(message="hi", reasoning_level="low", reasoning_budget_tokens=999)
        assert resolve_reasoning_budget(request) == 999

    def test_strips_and_lowercases_level(self):
        request = ChatRequest(message="hi", reasoning_level="  HIGH  ")
        assert resolve_reasoning_budget(request) == REASONING_BUDGETS["high"]


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------

class TestResolveProvider:
    @pytest.mark.parametrize("provider", ["llama", "nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"])
    def test_accepts_valid_providers(self, provider):
        assert resolve_provider(provider) == provider

    @pytest.mark.parametrize("provider", ["LLAMA", "  nvidia  ", "DeepSeek"])
    def test_normalizes_provider_case_and_whitespace(self, provider):
        result = resolve_provider(provider)
        assert result == provider.strip().lower()

    def test_raises_for_invalid_provider(self):
        with pytest.raises(HTTPException) as exc:
            resolve_provider("openai")
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# resolve_prompt_mode
# ---------------------------------------------------------------------------

class TestResolvePromptMode:
    @pytest.mark.parametrize("mode", ["auto", "writing", "exploring", "research"])
    def test_accepts_valid_modes(self, mode):
        assert resolve_prompt_mode(mode) == mode

    def test_defaults_to_auto_when_none(self):
        assert resolve_prompt_mode(None) == "auto"

    def test_normalizes_case_and_whitespace(self):
        assert resolve_prompt_mode("  WRITING  ") == "writing"

    def test_raises_for_invalid_mode(self):
        with pytest.raises(HTTPException) as exc:
            resolve_prompt_mode("coding")
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# resolve_tool_context
# ---------------------------------------------------------------------------

class TestResolveToolContext:
    def test_returns_empty_dict_when_no_tool_context_and_no_workspace(self):
        request = ChatRequest(message="hi")
        result = resolve_tool_context(request)
        assert result == {}

    def test_passes_through_tool_context_when_no_workspace(self):
        request = ChatRequest(message="hi", tool_context={"cwd": "/tmp"})
        result = resolve_tool_context(request)
        assert result == {"cwd": "/tmp"}

    def test_raises_403_when_workspace_root_resolution_fails(self, monkeypatch):
        import personagent.adapters.api.routes.chat.helpers as helpers_module

        def _failing_resolve(*, workspace_id, workspace_root):
            raise ValueError("denied")

        monkeypatch.setattr(helpers_module, "resolve_workspace_root", _failing_resolve)
        request = ChatRequest(message="hi", workspace_root="/invalid")
        with pytest.raises(HTTPException) as exc:
            resolve_tool_context(request)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# resolve_team_workspace_id
# ---------------------------------------------------------------------------

class TestResolveTeamWorkspaceId:
    def test_returns_workspace_id_from_tool_context(self):
        request = ChatRequest(message="hi")
        result = resolve_team_workspace_id(request, {"workspace_id": "ws-1"})
        assert result == "ws-1"

    def test_falls_back_to_request_workspace_id(self):
        request = ChatRequest(message="hi", workspace_id="ws-2")
        result = resolve_team_workspace_id(request, {})
        assert result == "ws-2"

    def test_strips_whitespace_from_ids(self):
        request = ChatRequest(message="hi", workspace_id="  ws-3  ")
        result = resolve_team_workspace_id(request, {})
        assert result == "ws-3"

    def test_returns_none_when_no_workspace_id_available(self):
        request = ChatRequest(message="hi")
        result = resolve_team_workspace_id(request, {})
        assert result is None


# ---------------------------------------------------------------------------
# _require_plan_approval
# ---------------------------------------------------------------------------

class TestRequirePlanApproval:
    def test_returns_state_when_valid(self):
        state = {"status": "awaiting_approval", "approval_id": "appr-1"}
        request = PlanDecisionRequest(conversation_id="c1", approval_id="appr-1")
        result = _require_plan_approval(state=state, request=request)
        assert result is state

    def test_raises_when_status_is_not_awaiting_approval(self):
        state = {"status": "draft", "approval_id": "appr-1"}
        request = PlanDecisionRequest(conversation_id="c1", approval_id="appr-1")
        with pytest.raises(HTTPException) as exc:
            _require_plan_approval(state=state, request=request)
        assert exc.value.status_code == 409

    def test_raises_when_approval_id_mismatches(self):
        state = {"status": "awaiting_approval", "approval_id": "appr-1"}
        request = PlanDecisionRequest(conversation_id="c1", approval_id="appr-2")
        with pytest.raises(HTTPException) as exc:
            _require_plan_approval(state=state, request=request)
        assert exc.value.status_code == 409

    def test_raises_when_approval_id_is_missing_from_state(self):
        state = {"status": "awaiting_approval"}
        request = PlanDecisionRequest(conversation_id="c1")
        with pytest.raises(HTTPException) as exc:
            _require_plan_approval(state=state, request=request)
        assert exc.value.status_code == 409

    def test_allows_request_without_approval_id_when_state_has_one(self):
        state = {"status": "awaiting_approval", "approval_id": "appr-1"}
        request = PlanDecisionRequest(conversation_id="c1")
        result = _require_plan_approval(state=state, request=request)
        assert result is state


# ---------------------------------------------------------------------------
# _require_tool_approval
# ---------------------------------------------------------------------------

class TestRequireToolApproval:
    def test_returns_pending_when_valid(self):
        metadata = {
            "pending_tool_approval": {
                "approval_id": "tid-1",
                "status": "awaiting_approval",
                "tool_name": "bash",
            }
        }
        result = _require_tool_approval(metadata, "tid-1")
        assert result["tool_name"] == "bash"

    def test_raises_when_no_pending_tool(self):
        with pytest.raises(HTTPException) as exc:
            _require_tool_approval({}, "tid-1")
        assert exc.value.status_code == 409

    def test_raises_when_approval_id_mismatches(self):
        metadata = {
            "pending_tool_approval": {
                "approval_id": "tid-1",
                "status": "awaiting_approval",
            }
        }
        with pytest.raises(HTTPException) as exc:
            _require_tool_approval(metadata, "tid-2")
        assert exc.value.status_code == 409

    def test_raises_when_status_is_not_awaiting_approval(self):
        metadata = {
            "pending_tool_approval": {
                "approval_id": "tid-1",
                "status": "approved",
            }
        }
        with pytest.raises(HTTPException) as exc:
            _require_tool_approval(metadata, "tid-1")
        assert exc.value.status_code == 409

    def test_returns_copy_not_reference(self):
        pending = {"approval_id": "tid-1", "status": "awaiting_approval"}
        metadata = {"pending_tool_approval": pending}
        result = _require_tool_approval(metadata, "tid-1")
        assert result is not pending
        assert result == pending


# ---------------------------------------------------------------------------
# _require_user_question
# ---------------------------------------------------------------------------

class TestRequireUserQuestion:
    def test_returns_pending_when_valid(self):
        metadata = {
            "pending_user_question": {
                "approval_id": "qid-1",
                "status": "awaiting_answer",
                "tool_name": "ask_user_question",
            }
        }
        result = _require_user_question(metadata, "qid-1")
        assert result["tool_name"] == "ask_user_question"

    def test_raises_when_no_pending_question(self):
        with pytest.raises(HTTPException) as exc:
            _require_user_question({}, "qid-1")
        assert exc.value.status_code == 409

    def test_raises_when_status_is_not_awaiting_answer(self):
        metadata = {
            "pending_user_question": {
                "approval_id": "qid-1",
                "status": "answered",
            }
        }
        with pytest.raises(HTTPException) as exc:
            _require_user_question(metadata, "qid-1")
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# _last_user_message
# ---------------------------------------------------------------------------

class TestLastUserMessage:
    def test_returns_last_user_message_content(self):
        conv = _StubConversation(
            messages=[
                _StubMessage(Role.USER, "first question"),
                _StubMessage(Role.ASSISTANT, "answer"),
                _StubMessage(Role.USER, "second question"),
            ]
        )
        assert _last_user_message(conv) == "second question"

    def test_returns_empty_string_when_no_user_messages(self):
        conv = _StubConversation(
            messages=[_StubMessage(Role.ASSISTANT, "only assistant")]
        )
        assert _last_user_message(conv) == ""

    def test_returns_empty_string_when_no_messages(self):
        conv = _StubConversation()
        assert _last_user_message(conv) == ""

    def test_skips_empty_user_messages(self):
        conv = _StubConversation(
            messages=[
                _StubMessage(Role.USER, "real question"),
                _StubMessage(Role.USER, "   "),
            ]
        )
        assert _last_user_message(conv) == "real question"


# ---------------------------------------------------------------------------
# _update_plan_approval_artifact
# ---------------------------------------------------------------------------

class TestUpdatePlanApprovalArtifact:
    def test_noop_when_approval_id_is_empty(self):
        conv = _StubConversation()
        _update_plan_approval_artifact(conv, "", {})
        # Should not raise

    def test_updates_matching_artifact_in_last_assistant_message(self):
        conv = _StubConversation(
            messages=[
                _StubMessage(
                    Role.ASSISTANT,
                    "plan",
                    metadata={
                        "plan_approval": {
                            "approvalId": "plan-1",
                            "planStatus": "awaiting_approval",
                        }
                    },
                )
            ]
        )
        _update_plan_approval_artifact(conv, "plan-1", {"status": "approved", "feedback": "ok"})
        artifact = conv.messages[0].metadata["plan_approval"]
        assert artifact["planStatus"] == "approved"
        assert artifact["feedback"] == "ok"

    def test_noop_when_no_plan_approval_artifact_found(self):
        conv = _StubConversation(
            messages=[_StubMessage(Role.ASSISTANT, "plain text")]
        )
        _update_plan_approval_artifact(conv, "plan-1", {"status": "approved"})

    def test_finds_artifact_in_reversed_order(self):
        conv = _StubConversation(
            messages=[
                _StubMessage(
                    Role.ASSISTANT,
                    "first plan",
                    metadata={"plan_approval": {"approvalId": "plan-1"}},
                ),
                _StubMessage(
                    Role.ASSISTANT,
                    "second plan",
                    metadata={"plan_approval": {"approvalId": "plan-2"}},
                ),
            ]
        )
        _update_plan_approval_artifact(conv, "plan-2", {"status": "cancelled"})
        assert conv.messages[1].metadata["plan_approval"]["planStatus"] == "cancelled"
        # First message should be untouched
        assert "planStatus" not in conv.messages[0].metadata["plan_approval"]

    def test_skips_non_assistant_messages(self):
        conv = _StubConversation(
            messages=[
                _StubMessage(
                    Role.USER,
                    "user message",
                    metadata={"plan_approval": {"approvalId": "plan-1"}},
                )
            ]
        )
        _update_plan_approval_artifact(conv, "plan-1", {"status": "approved"})
        # User message artifact should not be updated
        assert "planStatus" not in conv.messages[0].metadata["plan_approval"]


# ---------------------------------------------------------------------------
# resolve_session_memory_service
# ---------------------------------------------------------------------------

class TestResolveSessionMemoryService:
    def test_creates_service_with_update_backend_when_enabled(self):
        container = _StubDIContainer()
        backend = _StubLLMBackend()
        result = resolve_session_memory_service(container, backend)
        assert container.create_session_memory_service_calls == [backend]
        assert result == f"session_memory_service({backend})"

    def test_creates_service_without_update_backend_when_disabled(self):
        settings = _StubSettings()
        settings.chat_session_memory_updates_enabled = False
        container = _StubDIContainer(settings=settings)
        backend = _StubLLMBackend()
        result = resolve_session_memory_service(container, backend)
        assert container.create_session_memory_service_calls == [None]
        assert result == f"session_memory_service({None})"


# ---------------------------------------------------------------------------
# resolve_next_step_suggestion_service
# ---------------------------------------------------------------------------

class TestResolveNextStepSuggestionService:
    def test_creates_service_when_enabled(self):
        container = _StubDIContainer()
        backend = _StubLLMBackend()
        result = resolve_next_step_suggestion_service(container, backend)
        assert result is not None
        assert container.create_next_step_suggestion_service_calls == [backend]

    def test_returns_none_when_disabled(self):
        settings = _StubSettings()
        settings.chat_next_step_suggestions_enabled = False
        container = _StubDIContainer(settings=settings)
        backend = _StubLLMBackend()
        result = resolve_next_step_suggestion_service(container, backend)
        assert result is None
        assert container.create_next_step_suggestion_service_calls == []


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------

class TestChatRequestModel:
    def test_minimal_request(self):
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.stream is True
        assert req.provider == "llama"

    def test_message_min_length_validation(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_temperature_range(self):
        req = ChatRequest(message="hi", temperature=0.0)
        assert req.temperature == 0.0
        req = ChatRequest(message="hi", temperature=2.0)
        assert req.temperature == 2.0

    def test_default_values(self):
        req = ChatRequest(message="test")
        assert req.reasoning_budget_tokens is None
        assert req.tools_enabled is True
        assert req.context_attachments == []
        assert req.plan_mode_requested is False


class TestPlanDecisionRequestModel:
    def test_minimal_request(self):
        req = PlanDecisionRequest(conversation_id="conv-1")
        assert req.conversation_id == "conv-1"
        assert req.approval_id is None
        assert req.feedback is None


class TestToolApprovalDecisionRequestModel:
    def test_minimal_request(self):
        req = ToolApprovalDecisionRequest(conversation_id="conv-1", approval_id="tid-1")
        assert req.conversation_id == "conv-1"
        assert req.approval_id == "tid-1"


class TestUserQuestionResponseRequestModel:
    def test_accepts_dict_answers(self):
        req = UserQuestionResponseRequest(
            conversation_id="conv-1",
            approval_id="qid-1",
            answers={"q1": "answer1"},
        )
        assert req.answers == {"q1": "answer1"}

    def test_accepts_list_answers(self):
        req = UserQuestionResponseRequest(
            conversation_id="conv-1",
            approval_id="qid-1",
            answers=["a", "b"],
        )
        assert req.answers == ["a", "b"]
