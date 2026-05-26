"""Tests for the chat prompt-package builder.

The builder is the last assembly step before the system prompt is
handed to the LLM. It pulls together the prompt profile, the
agent-state, the skill / command inventories, the session memory, the
runtime reminders, and the final ``PromptBuilder.build`` call into a
single :class:`PromptPackage`.

These tests use light stubs (record-and-return doubles) for every
collaborator so the routing rules and metadata propagation are pinned
without depending on the real prompt sections, the real skill loader,
the real LLM context analyzer, etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.state import PromptPreparation
from personagent.application.use_cases.chat.prompt.prompt_package import (
    PromptPackageBuilder,
)
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.prompts.models import (
    AgentStateProfile,
    BuiltSystemPrompt,
    PromptProfile,
)
from personagent.domain.prompts.skills import SkillDefinition
from personagent.domain.tools import ToolDefinition

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _PromptBuilderStub:
    """Stand-in for :class:`PromptBuilder`.

    Records every call and hands back a configurable
    :class:`BuiltSystemPrompt` so the test can assert the metadata
    propagates verbatim.
    """

    def __init__(
        self,
        *,
        content: str = "SYS",
        user_context_message: str | None = None,
        sections_used: tuple[str, ...] = ("base",),
        metadata: dict[str, Any] | None = None,
        build_duration_ms: int = 7,
    ) -> None:
        self._content = content
        self._user_context_message = user_context_message
        self._sections_used = sections_used
        self._metadata: dict[str, Any] = metadata or {
            "prompt_mode": "exploring",
            "requested_prompt_mode": "auto",
            "prompt_analysis_source": "fallback_heuristic",
            "prompt_analysis_confidence": 0.5,
            "prompt_profile": "exploring",
            "prompt_surfaces_used": ("base",),
            "agent_states": ("default",),
            "agent_state_source": "fallback",
            "agent_state_reason": "no-op",
            "agent_state_confidence": 0.0,
            "agent_state_profile": "default",
            "state_sections_used": ["state"],
            "dynamic_sections_used": ("dyn",),
            "provider_data_boundary": "open",
        }
        self._build_duration_ms = build_duration_ms
        self.calls: list[dict[str, Any]] = []

    async def build(
        self,
        system_context: Any,
        user_context: Any,
        available_tools: list[str] | None = None,
        **kwargs: Any,
    ) -> BuiltSystemPrompt:
        self.calls.append(
            {
                "system_context": system_context,
                "user_context": user_context,
                "available_tools": available_tools,
                **kwargs,
            }
        )
        return BuiltSystemPrompt(
            content=self._content,
            user_context_message=self._user_context_message,
            sections_used=self._sections_used,
            metadata=self._metadata,
            build_duration_ms=self._build_duration_ms,
        )


class _AgentStateResolverStub:
    """Stand-in for :class:`AgentStateResolver`."""

    def __init__(self, profile: AgentStateProfile | None = None) -> None:
        self._profile = profile or AgentStateProfile(
            states=("intake", "finalization"),
            confidence=0.9,
            source="stub",
            reason="test",
        )
        self.calls: list[dict[str, Any]] = []

    def resolve(self, **kwargs: Any) -> AgentStateProfile:
        self.calls.append(kwargs)
        return self._profile


class _PromptContextAnalyzerStub:
    """Stand-in for :class:`PromptContextAnalyzer`.

    Returns the profile it was constructed with and records every call.
    """

    def __init__(self, profile: PromptProfile | None = None) -> None:
        self._profile = profile or PromptProfile(
            primary_mode="exploring",
            secondary_modes=(),
            requested_mode="auto",
            confidence=0.5,
            source="stub",
        )
        self.calls: list[dict[str, Any]] = []

    async def analyze(self, **kwargs: Any) -> PromptProfile:
        self.calls.append(kwargs)
        return self._profile


class _CommandRegistryStub:
    """Stand-in for :class:`CommandRegistry`."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_commands(self, workspace_root: str) -> list[Any]:
        self.calls.append(workspace_root)
        return []


class _ToolRegistryStub:
    """Stand-in for :class:`ToolRegistry`."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = tools or []
        self.list_calls: list[tuple[set[str] | None, bool]] = []

    def list_enabled(
        self, allowed_tools: set[str] | None, include_deferred: bool = True
    ) -> list[Any]:
        self.list_calls.append((allowed_tools, include_deferred))
        return [type("T", (), {"definition": t})() for t in self._tools]


class _SessionMemoryServiceStub:
    """Stand-in for :class:`SessionMemoryService`."""

    def __init__(self, value: str | None = None) -> None:
        self._value = value
        self.calls: list[str] = []

    def load(self, conversation_id: str) -> str | None:
        self.calls.append(conversation_id)
        return self._value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _request(
    *,
    message: str = "hello",
    provider: str = "nvidia",
    prompt_mode: str = "exploring",
    tools_enabled: bool = True,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
) -> ChatRequestDTO:
    return ChatRequestDTO(
        message=message,
        provider=provider,
        model="test-model",
        prompt_mode=prompt_mode,
        tools_enabled=tools_enabled,
        allowed_tools=allowed_tools,
        system_prompt=system_prompt,
    )


def _context(workspace_root: str = "/ws") -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(workspace_root=workspace_root, cwd=workspace_root),
        user_context=UserContext(),
        build_duration_ms=0,
        metadata={"source": "stub"},
    )


def _conversation() -> Conversation:
    return Conversation()


def _builder(
    *,
    prompt_builder: _PromptBuilderStub | None = None,
    prompt_context_analyzer: Any = None,
    agent_state_resolver: _AgentStateResolverStub | None = None,
    command_registry: _CommandRegistryStub | None = None,
    tool_registry: _ToolRegistryStub | None = None,
    session_memory_service: _SessionMemoryServiceStub | None = None,
    skill_roots: tuple[str | Path, ...] = (),
) -> tuple[PromptPackageBuilder, dict[str, Any]]:
    pb = prompt_builder or _PromptBuilderStub()
    asr = agent_state_resolver or _AgentStateResolverStub()
    cr = command_registry or _CommandRegistryStub()
    tr = tool_registry  # may be None
    sms = session_memory_service  # may be None
    instance = PromptPackageBuilder(
        prompt_builder=pb,  # type: ignore[arg-type]
        prompt_context_analyzer=prompt_context_analyzer,
        agent_state_resolver=asr,  # type: ignore[arg-type]
        command_registry=cr,  # type: ignore[arg-type]
        tool_registry=tr,  # type: ignore[arg-type]
        session_memory_service=sms,  # type: ignore[arg-type]
        skill_roots_provider=lambda: skill_roots,
    )
    return instance, {
        "prompt_builder": pb,
        "agent_state_resolver": asr,
        "command_registry": cr,
        "tool_registry": tr,
        "session_memory_service": sms,
        "prompt_context_analyzer": prompt_context_analyzer,
    }


def _patch_skills(skills: list[SkillDefinition] | None = None) -> Any:
    return patch(
        "personagent.application.use_cases.chat.prompt.prompt_package.discover_enabled_skills",
        return_value=skills or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_returns_prompt_package_with_system_prompt() -> None:
    pb = _PromptBuilderStub(content="HELLO")
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        pkg = await builder.build(_request(), _conversation(), _context(), tools=[])

    assert pkg.system_prompt == "HELLO"
    assert pkg.user_context_message is None
    assert pkg.metadata["line_count"] == 1
    assert pkg.metadata["char_count"] == len("HELLO")
    assert pkg.metadata["prompt_build_duration_ms"] == 7


@pytest.mark.asyncio
async def test_build_invokes_command_registry_and_skill_discovery() -> None:
    cr = _CommandRegistryStub()
    builder, _ = _builder(command_registry=cr, skill_roots=("/skills",))
    with _patch_skills() as skill_mock:
        await builder.build(_request(), _conversation(), _context(), tools=[])

    assert cr.calls == ["/ws"]
    skill_mock.assert_called_once()
    kwargs = skill_mock.call_args.kwargs
    assert kwargs["workspace_root"] == "/ws"
    assert kwargs["cwd"] == "/ws"
    assert kwargs["extra_roots"] == ("/skills",)


@pytest.mark.asyncio
async def test_build_uses_session_memory_when_service_is_wired() -> None:
    sms = _SessionMemoryServiceStub(value="recent decisions")
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb, session_memory_service=sms)
    convo = _conversation()
    with _patch_skills():
        await builder.build(_request(), convo, _context(), tools=[])

    assert sms.calls == [str(convo.id)]
    assert pb.calls[0]["session_memory"] == "recent decisions"


@pytest.mark.asyncio
async def test_build_skips_session_memory_when_service_missing() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb, session_memory_service=None)
    with _patch_skills():
        await builder.build(_request(), _conversation(), _context(), tools=[])

    assert pb.calls[0]["session_memory"] is None


@pytest.mark.asyncio
async def test_llama_auto_mode_uses_fallback_profile_without_analyzer_call() -> None:
    analyzer = _PromptContextAnalyzerStub()
    builder, _ = _builder(prompt_context_analyzer=analyzer)
    with _patch_skills():
        await builder.build(
            _request(provider="llama", prompt_mode="auto"),
            _conversation(),
            _context(),
            tools=[],
        )
    assert analyzer.calls == []


@pytest.mark.asyncio
async def test_zenmux_auto_mode_uses_fallback_profile_without_analyzer_call() -> None:
    analyzer = _PromptContextAnalyzerStub()
    builder, _ = _builder(prompt_context_analyzer=analyzer)
    with _patch_skills():
        await builder.build(
            _request(provider="zenmux", prompt_mode="auto"),
            _conversation(),
            _context(),
            tools=[],
        )
    assert analyzer.calls == []


@pytest.mark.asyncio
async def test_no_analyzer_with_non_auto_mode_uses_internal_analyzer() -> None:
    builder, _ = _builder(prompt_context_analyzer=None)
    with _patch_skills():
        pkg = await builder.build(
            _request(provider="nvidia", prompt_mode="exploring"),
            _conversation(),
            _context(),
            tools=[],
        )
    assert pkg.metadata["prompt_mode"] == "exploring"


@pytest.mark.asyncio
async def test_analyzer_is_called_when_present_and_not_auto_skip() -> None:
    analyzer = _PromptContextAnalyzerStub()
    builder, _ = _builder(prompt_context_analyzer=analyzer)
    with _patch_skills():
        await builder.build(
            _request(provider="nvidia", prompt_mode="auto"),
            _conversation(),
            _context(),
            tools=[],
        )
    assert len(analyzer.calls) == 1


@pytest.mark.asyncio
async def test_prompt_tool_definitions_empty_when_tools_disabled() -> None:
    tool_def = ToolDefinition(
        name="MyTool", description="d", input_schema={"type": "object"}
    )
    tr = _ToolRegistryStub(tools=[tool_def])
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb, tool_registry=tr)
    with _patch_skills():
        await builder.build(
            _request(tools_enabled=False),
            _conversation(),
            _context(),
            tools=[],
        )

    assert tr.list_calls == []
    assert pb.calls[0]["available_tool_definitions"] == []


@pytest.mark.asyncio
async def test_prompt_tool_definitions_empty_when_registry_missing() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb, tool_registry=None)
    with _patch_skills():
        await builder.build(_request(), _conversation(), _context(), tools=[])
    assert pb.calls[0]["available_tool_definitions"] == []


@pytest.mark.asyncio
async def test_prompt_tool_definitions_returned_when_tools_enabled() -> None:
    tool_def = ToolDefinition(
        name="MyTool", description="d", input_schema={"type": "object"}
    )
    tr = _ToolRegistryStub(tools=[tool_def])
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb, tool_registry=tr)
    with _patch_skills():
        await builder.build(
            _request(tools_enabled=True, allowed_tools=["MyTool"]),
            _conversation(),
            _context(),
            tools=[{"function": {"name": "MyTool"}}],
        )

    assert tr.list_calls == [({"MyTool"}, True)]
    forwarded = pb.calls[0]["available_tool_definitions"]
    assert len(forwarded) == 1 and forwarded[0].name == "MyTool"


@pytest.mark.asyncio
async def test_supports_parallel_tool_calls_false_when_tools_disabled() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        await builder.build(
            _request(tools_enabled=False),
            _conversation(),
            _context(),
            tools=[
                {"function": {"name": "A"}},
                {"function": {"name": "B"}},
            ],
        )
    assert pb.calls[0]["supports_parallel_tool_calls"] is False


@pytest.mark.asyncio
async def test_supports_parallel_tool_calls_true_for_codex_with_one_tool() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        await builder.build(
            _request(provider="codex"),
            _conversation(),
            _context(),
            tools=[{"function": {"name": "A"}}],
        )
    assert pb.calls[0]["supports_parallel_tool_calls"] is True


@pytest.mark.asyncio
async def test_supports_parallel_tool_calls_requires_two_tools_for_others() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        await builder.build(
            _request(provider="nvidia"),
            _conversation(),
            _context(),
            tools=[{"function": {"name": "A"}}],
        )
    assert pb.calls[0]["supports_parallel_tool_calls"] is False

    pb2 = _PromptBuilderStub()
    builder2, _ = _builder(prompt_builder=pb2)
    with _patch_skills():
        await builder2.build(
            _request(provider="nvidia"),
            _conversation(),
            _context(),
            tools=[
                {"function": {"name": "A"}},
                {"function": {"name": "B"}},
            ],
        )
    assert pb2.calls[0]["supports_parallel_tool_calls"] is True


@pytest.mark.asyncio
async def test_runtime_reminders_collect_slash_context_and_browser_target() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    preparation = PromptPreparation(
        request=_request(),
        slash_reminder="run /doit",
        context_reminders=["read FILE.md"],
        browser_target={"profile": "main", "window_id": "w1"},
    )
    with _patch_skills():
        await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[],
            preparation=preparation,
        )
    reminders = pb.calls[0]["runtime_reminders"]
    assert "run /doit" in reminders
    assert "read FILE.md" in reminders
    # The browser_target reminder is built by the helper and includes
    # the profile string.
    assert any("main" in r for r in reminders)


@pytest.mark.asyncio
async def test_browser_cooperation_reminders_appended_from_metadata() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    with (
        _patch_skills(),
        patch(
            "personagent.application.use_cases.chat.prompt.prompt_package."
            "browser_agent_context_reminder",
            return_value="AGENT-CTX",
        ),
        patch(
            "personagent.application.use_cases.chat.prompt.prompt_package."
            "shared_browser_workspace_reminder",
            return_value="SHARED-CTX",
        ),
    ):
        pkg = await builder.build(_request(), _conversation(), _context(), tools=[])

    reminders = pb.calls[0]["runtime_reminders"]
    assert "AGENT-CTX" in reminders
    assert "SHARED-CTX" in reminders
    assert pkg.metadata["has_browser_cooperation_context"] is True
    assert pkg.metadata["has_shared_browser_workspace_context"] is True


@pytest.mark.asyncio
async def test_custom_system_prompt_is_appended_not_replaced() -> None:
    pb = _PromptBuilderStub(content="BASE")
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        pkg = await builder.build(
            _request(system_prompt="EXTRA INSTRUCTIONS"),
            _conversation(),
            _context(),
            tools=[],
        )

    assert pkg.system_prompt is not None
    assert pkg.system_prompt.startswith("BASE")
    assert "EXTRA INSTRUCTIONS" in pkg.system_prompt
    assert pkg.metadata["has_custom_system_prompt"] is True
    assert pkg.metadata["custom_system_prompt_policy"] == "append_to_dynamic_system_prompt"
    assert "custom_system_instructions" in pkg.metadata["prompt_sections_used"]


@pytest.mark.asyncio
async def test_user_context_message_folded_into_system_prompt() -> None:
    pb = _PromptBuilderStub(
        content="BASE", user_context_message="<system-reminder>CTX</system-reminder>"
    )
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        pkg = await builder.build(_request(), _conversation(), _context(), tools=[])

    assert pkg.system_prompt is not None
    assert "User Context and Runtime Reminders" in pkg.system_prompt
    assert "CTX" in pkg.system_prompt
    # The legacy reminder tags are stripped before folding in.
    assert "<system-reminder>" not in pkg.system_prompt
    assert pkg.metadata["user_context_in_system_prompt"] is True
    # The package's own user_context_message is cleared because the
    # caller will read it from the system prompt instead.
    assert pkg.user_context_message is None
    assert "user_context_runtime" in pkg.metadata["prompt_sections_used"]


@pytest.mark.asyncio
async def test_operational_memory_metadata_is_propagated_into_package() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    convo = _conversation()
    convo.metadata["_operational_memory_prompt"] = {
        "memory_budget_tokens": 1000,
        "memory_budget_used": 250,
        "memory_items_injected": 3,
        "memory_items_omitted": 1,
        "memory_latency_ms": 42,
        "memory_filters_applied": ["project"],
        "memory_recall_scope": "project",
        "memory_query_intent": "lookup",
        "memory_candidate_count": 8,
        "memory_discarded_candidates": 5,
        "memory_included_reasons": ["high_score"],
        "memory_ranking_breakdown": {"top": 0.9},
        "memory_token_usage": {"prompt": 250},
    }
    with _patch_skills():
        pkg = await builder.build(_request(), convo, _context(), tools=[])

    for key in (
        "memory_budget_tokens",
        "memory_budget_used",
        "memory_items_injected",
        "memory_items_omitted",
        "memory_latency_ms",
        "memory_filters_applied",
        "memory_recall_scope",
        "memory_query_intent",
        "memory_candidate_count",
        "memory_discarded_candidates",
        "memory_included_reasons",
        "memory_ranking_breakdown",
        "memory_token_usage",
    ):
        assert pkg.metadata[key] == convo.metadata["_operational_memory_prompt"][key]


@pytest.mark.asyncio
async def test_memory_trace_is_propagated_verbatim() -> None:
    builder, _ = _builder()
    trace = {"query": "x", "hits": 3}
    with _patch_skills():
        pkg = await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[],
            memory_trace=trace,
        )
    assert pkg.metadata["memory_trace"] is trace


@pytest.mark.asyncio
async def test_context_attachments_metadata_is_forwarded_from_preparation() -> None:
    builder, _ = _builder()
    preparation = PromptPreparation(
        request=_request(),
        context_attachment_metadata=[{"type": "file", "path": "/ws/README.md"}],
        slash_metadata={"name": "doit"},
    )
    with _patch_skills():
        pkg = await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[],
            preparation=preparation,
        )

    assert pkg.metadata["context_attachments"] == preparation.context_attachment_metadata
    assert pkg.metadata["context_attachment_count"] == 1
    assert pkg.metadata["slash_command"] == {"name": "doit"}


@pytest.mark.asyncio
async def test_agent_state_resolver_receives_recent_tool_names_and_errors() -> None:
    asr = _AgentStateResolverStub()
    builder, _ = _builder(agent_state_resolver=asr)
    convo = _conversation()
    convo.metadata["last_request_error"] = "boom"
    convo.add_message(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                {"function": {"name": "ReadFile"}},
                {"function": {"name": "WriteFile"}},
            ],
        )
    )
    convo.add_message(
        Message(
            role=Role.TOOL,
            content="",
            metadata={"tool_name": "Shell", "status": "error"},
        )
    )
    with _patch_skills():
        await builder.build(_request(), convo, _context(), tools=[])

    call = asr.calls[0]
    assert call["recent_tool_names"] == ["ReadFile", "WriteFile", "Shell"]
    # last_request_error + the TOOL error message both contribute.
    assert call["recent_error_count"] == 2
    assert call["has_relevant_memories"] is False


@pytest.mark.asyncio
async def test_available_tools_names_extracted_from_schemas() -> None:
    pb = _PromptBuilderStub()
    builder, _ = _builder(prompt_builder=pb)
    with _patch_skills():
        await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[
                {"function": {"name": "A"}},
                {"function": {"name": ""}},  # empty name dropped
                {"no_function": True},  # invalid entry dropped
                {"function": {"name": "B"}},
            ],
        )
    assert pb.calls[0]["available_tools"] == ["A", "B"]


@pytest.mark.asyncio
async def test_relevant_memories_flag_passed_to_resolver() -> None:
    asr = _AgentStateResolverStub()
    builder, _ = _builder(agent_state_resolver=asr)
    with _patch_skills():
        await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[],
            relevant_memories=["m1"],
        )
    assert asr.calls[0]["has_relevant_memories"] is True


@pytest.mark.asyncio
async def test_context_compaction_flag_propagated_to_resolver() -> None:
    asr = _AgentStateResolverStub()
    builder, _ = _builder(agent_state_resolver=asr)
    convo = _conversation()
    convo.metadata["context_compaction"] = {"reason": "exceeded"}
    with _patch_skills():
        await builder.build(_request(), convo, _context(), tools=[])
    assert asr.calls[0]["context_compacted"] is True


@pytest.mark.asyncio
async def test_browser_target_is_recorded_in_metadata_when_present() -> None:
    builder, _ = _builder()
    preparation = PromptPreparation(
        request=_request(),
        browser_target={"profile": "main", "window_id": "w1"},
    )
    with _patch_skills():
        pkg = await builder.build(
            _request(),
            _conversation(),
            _context(),
            tools=[],
            preparation=preparation,
        )
    assert pkg.metadata["browser_target"] == {"profile": "main", "window_id": "w1"}


@pytest.mark.asyncio
async def test_no_preparation_yields_empty_attachments_and_no_target() -> None:
    builder, _ = _builder()
    with _patch_skills():
        pkg = await builder.build(_request(), _conversation(), _context(), tools=[])
    assert pkg.metadata["context_attachments"] == []
    assert pkg.metadata["context_attachment_count"] == 0
    assert pkg.metadata["slash_command"] is None
    assert pkg.metadata["browser_target"] is None
