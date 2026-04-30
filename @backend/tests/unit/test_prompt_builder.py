"""Unit tests for PromptBuilder."""

import asyncio
import json
from pathlib import Path

import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.prompts import infer_prompt_mode
from personagent.domain.prompts.models import AgentStateProfile, PromptProfile, SystemPromptSection
from personagent.domain.prompts.prompt import PROMPT_DYNAMIC_BOUNDARY, get_mode_prompt_section
from personagent.domain.prompts.sections.states import (
    ORDERED_AGENT_STATES,
    get_agent_state_sections,
)
from personagent.domain.prompts.services import (
    AgentStateResolver,
    PromptBuilder,
    PromptContextAnalyzer,
)
from personagent.domain.prompts.skills import discover_skills
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository


class TestPromptBuilder:
    """Tests for PromptBuilder."""

    @pytest.fixture
    def system_context(self):
        """Create a sample SystemContext."""
        return SystemContext(
            git_branch="main",
            git_remote="origin",
            git_commit="abc123def456",
            workspace_root="/workspace",
            environment={"PATH": "/usr/bin", "HOME": "/home/user"},
        )

    @pytest.fixture
    def user_context(self):
        """Create a sample UserContext."""
        return UserContext(
            persona_md="# Project Instructions\n\nThis is a test project.",
            current_date="2024-01-15",
        )

    @pytest.mark.asyncio
    async def test_build_basic_prompt(self, system_context, user_context):
        """Test building a basic system prompt."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.content is not None
        assert len(result.content) > 0
        assert result.content.startswith("# Response Style Contract")
        assert "# Personality and Collaboration" in result.content
        assert "# Identity and Objective" in result.content
        assert "# Acting Contract" in result.content
        assert "# Final Response Contract" in result.content
        assert "Provider Data Boundary" in result.content

    @pytest.mark.asyncio
    async def test_response_style_and_personality_are_frontloaded(
        self, system_context, user_context
    ):
        """Response style and personality should have priority before identity/action rules."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=True)
        result = await builder.build(system_context, user_context)

        response_index = result.content.index("# Response Style Contract")
        personality_index = result.content.index("# Personality and Collaboration")
        identity_index = result.content.index("# Identity and Objective")
        acting_index = result.content.index("# Acting Contract")
        final_index = result.content.index("# Final Response Contract")

        assert response_index < personality_index < identity_index < acting_index < final_index

    @pytest.mark.asyncio
    async def test_response_style_contract_discourages_report_bloat(
        self, system_context, user_context
    ):
        """The stable prompt should explicitly prefer concise prose over report formatting."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=True)
        result = await builder.build(
            system_context,
            user_context,
            available_tools=["Read", "Grep", "Glob", "TodoWrite"],
            supports_parallel_tool_calls=True,
        )

        assert "Default final answers should be easy to read" in result.content
        assert "Avoid long wall-of-text paragraphs" in result.content
        assert "paragraph labels like `Resultado:`" in result.content
        assert "flat dash bullets exactly as `- conteudo`" in result.content
        assert "do not convert it into `1.`, `2.`, `3.` steps" in result.content
        assert "Do not use tables or diagrams by default" in result.content
        assert "Avoid emoji markers" in result.content
        assert "constant tables" in result.content
        assert "If the user asks for result, evidence, uncertainty, and validation" in result.content
        assert "Response Style Runtime Reminder" in result.content
        assert "response_style_runtime_reminder" in result.sections_used
        bullet_lines = [
            line for line in result.content.splitlines() if line.lstrip().startswith("- ")
        ]
        assert len(bullet_lines) == 0

    @pytest.mark.asyncio
    async def test_build_with_tools(self, system_context, user_context):
        """Test building prompt with available tools."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(
            system_context, user_context, available_tools=["read_file", "write_file"]
        )

        assert "read_file" in result.content
        assert "write_file" in result.content

    @pytest.mark.asyncio
    async def test_build_with_permission_mode_auto(self, system_context, user_context):
        """Test building prompt with auto permission mode."""
        builder = PromptBuilder(permission_mode="auto")
        result = await builder.build(system_context, user_context)

        assert "auto-permission mode" in result.content

    @pytest.mark.asyncio
    async def test_build_with_permission_mode_ask(self, system_context, user_context):
        """Test building prompt with ask permission mode."""
        builder = PromptBuilder(permission_mode="ask")
        result = await builder.build(system_context, user_context)

        assert "ask-permission mode" in result.content

    @pytest.mark.asyncio
    async def test_build_with_permission_mode_manual(self, system_context, user_context):
        """Test building prompt with manual permission mode."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert "manual-permission mode" in result.content
        assert "Do not ask for approval in prose before ordinary tool calls" in result.content
        assert "Tool calls require explicit user approval" not in result.content

    @pytest.mark.asyncio
    async def test_plan_mode_tool_prompt_requires_explicit_user_request(
        self, system_context, user_context
    ):
        """PlanMode should not be advertised as the default execution path."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(
            system_context,
            user_context,
            available_tools=["EnterPlanMode", "ExitPlanMode"],
        )

        assert "Use EnterPlanMode only when the user explicitly asks" in result.content
        assert "Do not use it for ordinary implementation" in result.content
        assert "generic approval request for normal tool use" in result.content
        assert "implementation needs explicit approval" not in result.content

    @pytest.mark.asyncio
    async def test_build_with_agent_sections_enabled(self, system_context, user_context):
        """Test building prompt with agent sections enabled."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=True)
        result = await builder.build(system_context, user_context)

        assert "# Personality and Collaboration" in result.content
        assert "Continuity" in result.content
        assert "PersonAgent" in result.content

    @pytest.mark.asyncio
    async def test_build_with_agent_sections_disabled(self, system_context, user_context):
        """Test building prompt with agent sections disabled."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=False)
        result = await builder.build(system_context, user_context)

        assert "# Personality and Collaboration" not in result.content
        assert "Continuity" not in result.content

    @pytest.mark.asyncio
    async def test_build_includes_system_context(self, system_context, user_context):
        """Test that system context is included in prompt."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert "# System Context" in result.content
        assert "Git Branch: main" in result.content
        assert "Git Remote: origin" in result.content
        assert "Git Commit: abc123de" in result.content
        assert "Workspace Root: /workspace" in result.content

    @pytest.mark.asyncio
    async def test_build_includes_user_context(self, system_context, user_context):
        """Test that user context is included in prompt."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.user_context_message is not None
        assert "Current Date: 2024-01-15" in result.user_context_message
        assert "Project Instructions" in result.user_context_message
        assert "Project Instructions" not in result.content

    @pytest.mark.asyncio
    async def test_build_without_persona_md(self, system_context):
        """Test building prompt without persona.md."""
        user_context = UserContext(persona_md=None)
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert "User Instructions (persona.md)" not in result.content

    @pytest.mark.asyncio
    async def test_build_with_empty_system_context(self, user_context):
        """Test building prompt with empty system context."""
        system_context = SystemContext()
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        # Should still build successfully
        assert result.content is not None
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_build_with_empty_user_context(self, system_context):
        """Test building prompt with empty user context."""
        user_context = UserContext()
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        # Should still build successfully
        assert result.content is not None
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_metadata_includes_permission_mode(self, system_context, user_context):
        """Test that metadata includes permission mode."""
        builder = PromptBuilder(permission_mode="auto")
        result = await builder.build(system_context, user_context)

        assert result.metadata["permission_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_metadata_includes_has_persona_md(self, system_context, user_context):
        """Test that metadata includes has_persona_md."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.metadata["has_persona_md"] is True

    @pytest.mark.asyncio
    async def test_metadata_includes_has_memory_files(self, system_context, user_context):
        """Test that metadata includes has_memory_files."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.metadata["has_memory_files"] is False

    @pytest.mark.asyncio
    async def test_metadata_includes_is_git_repo(self, system_context, user_context):
        """Test that metadata includes is_git_repo."""
        # Ensure git_status is set
        system_context = SystemContext(
            git_status={"is_git_repo": True},
            git_branch="main",
            git_remote="origin",
            git_commit="abc123def456",
            workspace_root="/workspace",
            environment={"PATH": "/usr/bin", "HOME": "/home/user"},
        )

        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.metadata["is_git_repo"] is True

    @pytest.mark.asyncio
    async def test_sections_used(self, system_context, user_context):
        """Test that sections_used is populated."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=True)
        result = await builder.build(system_context, user_context)

        assert len(result.sections_used) > 0
        assert "response_style_contract" in result.sections_used
        assert "personality_and_collaboration" in result.sections_used
        assert "identity_and_objective" in result.sections_used
        assert "acting_contract" in result.sections_used
        assert "provider_data_boundary" in result.sections_used

    @pytest.mark.asyncio
    async def test_todo_write_policy_is_conditional(self, system_context, user_context):
        """TodoWrite policy should appear only when the tool is available."""
        builder = PromptBuilder(permission_mode="manual")

        without_todo = await builder.build(
            system_context,
            user_context,
            available_tools=["Read"],
            supports_parallel_tool_calls=False,
        )
        with_todo = await builder.build(
            system_context,
            user_context,
            available_tools=["Read", "TodoWrite"],
            supports_parallel_tool_calls=False,
        )

        assert "TodoWrite Policy" not in without_todo.content
        assert "todo_write_policy" not in without_todo.sections_used
        assert "TodoWrite Policy" in with_todo.content
        assert "todo_write_policy" in with_todo.sections_used
        assert "Keep exactly one todo in progress" in with_todo.content

    @pytest.mark.asyncio
    async def test_parallel_tool_use_policy_is_conditional(self, system_context, user_context):
        """Parallel tool policy should reflect actual tool/capability availability."""
        builder = PromptBuilder(permission_mode="manual")

        single_tool = await builder.build(
            system_context,
            user_context,
            available_tools=["Read"],
            supports_parallel_tool_calls=False,
        )
        multiple_tools = await builder.build(
            system_context,
            user_context,
            available_tools=["Read", "Grep"],
            supports_parallel_tool_calls=False,
        )
        provider_supported = await builder.build(
            system_context,
            user_context,
            available_tools=["Read"],
            supports_parallel_tool_calls=True,
        )

        assert "Parallel Tool Use" not in single_tool.content
        assert "Parallel Tool Use" in multiple_tools.content
        assert "Parallel Tool Use" in provider_supported.content
        assert "parallel_tool_use" in multiple_tools.sections_used

    @pytest.mark.asyncio
    async def test_build_includes_agent_state_sections_and_metadata(
        self, system_context, user_context
    ):
        """State overlays should be appended after mode overlays and surfaced in metadata."""
        builder = PromptBuilder(permission_mode="manual")
        agent_state_profile = AgentStateProfile(
            states=("intake", "implementation", "runtime_validation", "finalization"),
            source="test",
            reason="explicit test",
            confidence=1.0,
        )

        result = await builder.build(
            system_context,
            user_context,
            prompt_mode="writing",
            agent_state_profile=agent_state_profile,
            available_tools=["Read"],
        )

        assert "Mode Overlay: Writing" in result.content
        assert "Agent State: Implementation" in result.content
        assert "Agent State: Runtime Validation" in result.content
        assert "state_implementation" in result.sections_used
        assert result.metadata["agent_states"] == [
            "intake",
            "implementation",
            "runtime_validation",
            "finalization",
        ]
        assert result.metadata["agent_state_source"] == "test"
        assert result.metadata["agent_state_reason"] == "explicit test"
        assert result.metadata["state_sections_used"] == [
            "state_intake",
            "state_implementation",
            "state_runtime_validation",
            "state_finalization",
        ]
        assert "agent_state" in result.metadata["prompt_surfaces_used"]
        assert "state:implementation" in result.metadata["prompt_surfaces_used"]

    def test_agent_state_resolver_maps_writing_tools_and_validation(self):
        """Implementation requests with tools and validation terms should activate work states."""
        resolver = AgentStateResolver()

        profile = resolver.resolve(
            message="Implemente e valide com testes",
            prompt_profile=PromptProfile(
                primary_mode="writing",
                intent="implement and validate",
                confidence=0.8,
                source="llm",
            ),
            available_tools=["Read", "Edit", "TodoWrite"],
        )

        assert "intake" in profile.states
        assert "implementation" in profile.states
        assert "tool_execution" in profile.states
        assert "runtime_validation" in profile.states
        assert "finalization" in profile.states
        assert profile.source == "heuristic"
        assert profile.reason

    def test_agent_state_resolver_detects_debug_long_context_memory_and_plan_mode(self):
        """Resolver should combine execution states from metadata, context, errors, and memory."""
        resolver = AgentStateResolver()

        profile = resolver.resolve(
            message="Analise a causa do erro em uma tarefa complexa",
            prompt_profile=PromptProfile(
                primary_mode="exploring",
                intent="inspect complex failure",
                confidence=0.6,
                source="fallback",
            ),
            conversation_metadata={
                "plan_mode": {"active": True},
                "context_compaction": {"compacted": True},
            },
            context_size_chars=250_000,
            conversation_message_count=90,
            recent_error_count=1,
            has_session_memory=True,
            has_relevant_memories=True,
        )

        assert "plan_mode" in profile.states
        assert "planning" in profile.states
        assert "context_discovery" in profile.states
        assert "debug_recovery" in profile.states
        assert "context_compaction" in profile.states
        assert "memory_recall" in profile.states
        assert "user_checkpoint" in profile.states
        assert "finalization" in profile.states

    @pytest.mark.asyncio
    async def test_provider_boundary_changes_by_provider(self, system_context, user_context):
        """Provider boundary should not make absolute local-only privacy claims."""
        builder = PromptBuilder(permission_mode="manual")

        local = await builder.build(system_context, user_context, provider="llama", model="local")
        hosted = await builder.build(system_context, user_context, provider="nvidia", model="hosted")
        deepseek = await builder.build(system_context, user_context, provider="deepseek", model="deepseek-v4-flash")
        codex = await builder.build(system_context, user_context, provider="codex", model="gpt-5.5")
        unknown = await builder.build(system_context, user_context, provider="custom", model="custom")

        assert local.metadata["provider_data_boundary"] == "local_model_local_tools"
        assert hosted.metadata["provider_data_boundary"] == "hosted_model_external_provider_local_tools"
        assert deepseek.metadata["provider_data_boundary"] == "hosted_model_external_provider_local_tools"
        assert codex.metadata["provider_data_boundary"] == "codex_subscription_external_model_local_tools"
        assert unknown.metadata["provider_data_boundary"] == "unknown_provider_local_tools"
        assert "Do not claim that all data stays local" in hosted.content
        assert "Do not claim that all data stays local" in codex.content
        assert "provider boundary is not recognized" in unknown.content

    @pytest.mark.asyncio
    async def test_size_chars(self, system_context, user_context):
        """Test that size_chars is calculated correctly."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.size_chars == len(result.content)
        assert result.size_chars > 0

    @pytest.mark.asyncio
    async def test_build_duration_ms(self, system_context, user_context):
        """Test that build_duration_ms is recorded."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.build_duration_ms >= 0
        assert isinstance(result.build_duration_ms, int)

    @pytest.mark.asyncio
    async def test_environment_variables_in_prompt(self, system_context, user_context):
        """Test that environment variables are included."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert "Environment Variables:" in result.content
        assert "PATH=/usr/bin" in result.content
        assert "HOME=/home/user" in result.content

    @pytest.mark.asyncio
    async def test_empty_environment_variables(self, system_context, user_context):
        """Test with empty environment variables."""
        system_context = SystemContext(environment={})
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        # Should not include environment section if empty
        assert "Environment Variables:" not in result.content

    def test_infer_prompt_mode_is_only_safe_fallback(self):
        assert infer_prompt_mode("Implemente essa alteração no backend") == "exploring"
        assert infer_prompt_mode("Pesquise na web as fontes mais recentes") == "exploring"

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_uses_llm_json(self):
        llm = FakeAnalysisLLM(
            {
                "primary_mode": "writing",
                "secondary_modes": ["research"],
                "intent": "implement researched prompt surfaces",
                "surface_hints": ["tool", "memory", "next_step"],
                "confidence": 0.86,
            }
        )
        analyzer = PromptContextAnalyzer(llm)

        profile = await analyzer.analyze(
            message="Implemente com pesquisa externa",
            requested_mode="auto",
            available_tools=["Read", "BrowserSearch"],
            workspace_root="/workspace",
        )

        assert profile.primary_mode == "writing"
        assert profile.secondary_modes == ("research",)
        assert profile.source == "llm"
        assert profile.confidence == 0.86
        assert llm.calls[0]["kwargs"]["tools"] is None
        assert llm.calls[0]["kwargs"]["reasoning_level"] == "low"

    def test_discover_skills_can_skip_global_roots(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        global_skill = home / ".codex" / "skills" / "global-skill" / "SKILL.md"
        workspace_skill = workspace / ".personagent" / "skills" / "local-skill" / "SKILL.md"
        global_skill.parent.mkdir(parents=True)
        workspace_skill.parent.mkdir(parents=True)
        global_skill.write_text("---\nname: Global Skill\n---\nGlobal body", encoding="utf-8")
        workspace_skill.write_text("---\nname: Local Skill\n---\nLocal body", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: home)

        skills = discover_skills(workspace_root=workspace, include_global=False)

        assert [skill.name for skill in skills] == ["Local Skill"]

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_reuses_llm_cache(self):
        llm = FakeAnalysisLLM(
            {
                "primary_mode": "research",
                "secondary_modes": [],
                "intent": "research current docs",
                "surface_hints": ["tool", "memory"],
                "confidence": 0.92,
            }
        )
        analyzer = PromptContextAnalyzer(llm)

        first = await analyzer.analyze(
            message="Pesquise a documentação atual",
            requested_mode="auto",
            available_tools=["BrowserSearch", "BrowserOpen"],
            workspace_root="/workspace",
        )
        second = await analyzer.analyze(
            message="Pesquise a documentação atual",
            requested_mode="auto",
            available_tools=["BrowserOpen", "BrowserSearch"],
            workspace_root="/workspace",
        )

        assert first.source == "llm"
        assert second.source == "llm_cache"
        assert second.primary_mode == "research"
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_override_wins_without_llm_call(self):
        llm = FakeAnalysisLLM({"primary_mode": "writing"})
        analyzer = PromptContextAnalyzer(llm)

        profile = await analyzer.analyze(
            message="Analise o repo",
            requested_mode="research",
        )

        assert profile.primary_mode == "research"
        assert profile.source == "override"
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_fallback_uses_local_heuristic(self):
        llm = FakeAnalysisLLM("not json")
        analyzer = PromptContextAnalyzer(llm)

        profile = await analyzer.analyze(
            message="Implemente o backend",
            requested_mode="auto",
        )

        assert profile.primary_mode == "writing"
        assert profile.source == "fallback_heuristic"
        assert profile.raw["reason"] == "invalid_response"

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_treats_missing_mode_as_exploring(self):
        llm = FakeAnalysisLLM(
            {
                "primary_mode": None,
                "secondary_modes": [],
                "intent": "greeting",
                "surface_hints": [],
                "confidence": 0.01,
            }
        )
        analyzer = PromptContextAnalyzer(llm)

        profile = await analyzer.analyze(
            message="olá, tudo bem?",
            requested_mode="auto",
        )

        assert profile.primary_mode == "exploring"
        assert profile.source == "llm"
        assert profile.intent == "greeting"

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_uses_cooldown_after_timeout(self):
        llm = SlowAnalysisLLM()
        analyzer = PromptContextAnalyzer(
            llm,
            timeout_seconds=0.01,
            failure_cooldown_seconds=60,
        )

        first = await analyzer.analyze(
            message="Pesquise fontes recentes",
            requested_mode="auto",
            provider="test",
            model="slow-model",
        )
        second = await analyzer.analyze(
            message="Implemente a correcao",
            requested_mode="auto",
            provider="test",
            model="slow-model",
        )

        assert first.source == "fallback_heuristic"
        assert second.source == "fallback_heuristic"
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_extends_timeout_for_long_context(self):
        llm = SlowAnalysisLLM()
        analyzer = PromptContextAnalyzer(
            llm,
            timeout_seconds=0.01,
            long_timeout_seconds=1,
            failure_cooldown_seconds=60,
            long_context_chars=100,
        )

        profile = await analyzer.analyze(
            message="Pesquise fontes recentes",
            requested_mode="auto",
            provider="vertex",
            model="gemini-3.1-pro-preview",
            context_size_chars=500_000,
            conversation_message_count=120,
        )

        assert profile.primary_mode == "research"
        assert profile.source == "llm"
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_prompt_context_analyzer_truncates_large_payload(self):
        llm = FakeAnalysisLLM({"primary_mode": "exploring"})
        analyzer = PromptContextAnalyzer(llm, max_payload_chars=1_000)

        await analyzer.analyze(
            message="A" * 3_000,
            requested_mode="auto",
            provider="vertex",
            model="gemini-2.5-flash",
        )

        payload = json.loads(llm.calls[0]["messages"][1]["content"])
        assert payload["message_was_truncated"] is True
        assert payload["message_chars"] == 3_000
        assert len(payload["message"]) < 1_200

    @pytest.mark.asyncio
    async def test_prompt_mode_override(self, system_context, user_context):
        builder = PromptBuilder(permission_mode="manual")

        result = await builder.build(
            system_context,
            user_context,
            prompt_mode="research",
            user_message="Implemente algo",
        )

        assert result.metadata["prompt_mode"] == "research"
        assert "Mode Overlay: Research" in result.content

    @pytest.mark.parametrize("mode", ["writing", "exploring", "research"])
    def test_each_mode_prompt_has_compact_instruction_lines(self, mode):
        content = get_mode_prompt_section(mode).compute()

        assert isinstance(content, str)
        lines = content.splitlines()
        assert 5 <= len(lines) <= 12
        assert lines[0] == f"Mode Overlay: {mode.title()}"
        assert "80" not in content

    def test_agent_state_overlays_are_compact(self):
        """Each state overlay should stay behavior-focused and visually light."""
        sections = get_agent_state_sections(ORDERED_AGENT_STATES)

        for section in sections:
            content = section.compute()
            assert isinstance(content, str)
            bullet_lines = [
                line for line in content.splitlines() if line.lstrip().startswith("- ")
            ]
            assert len(bullet_lines) <= 3, section.name

    @pytest.mark.asyncio
    async def test_dynamic_boundary_is_inserted(self, system_context, user_context):
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert PROMPT_DYNAMIC_BOUNDARY in result.content
        assert result.content.index(PROMPT_DYNAMIC_BOUNDARY) < result.content.index("# System Context")

    @pytest.mark.asyncio
    async def test_cacheable_sections_reuse_and_dynamic_sections_recompute(
        self,
        monkeypatch,
        system_context,
        user_context,
    ):
        calls = {"stable": 0, "dynamic": 0}

        def stable_section():
            calls["stable"] += 1
            return "stable section"

        def dynamic_section():
            calls["dynamic"] += 1
            return "dynamic section"

        monkeypatch.setattr(
            "personagent.domain.prompts.services.prompt_builder.get_default_prompt_sections",
            lambda: (
                SystemPromptSection("stable_test", stable_section),
                SystemPromptSection("dynamic_test", dynamic_section, cache_break=True),
            ),
        )
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=False)

        await builder.build(system_context, user_context, prompt_mode="exploring")
        await builder.build(system_context, user_context, prompt_mode="exploring")

        assert calls == {"stable": 1, "dynamic": 2}


class FakeAnalysisLLM(LLMBackendRepository):
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def chat_completion(self, messages, *args, **kwargs) -> InferenceResult:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return InferenceResult(content=content)

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(content="")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class SlowAnalysisLLM(FakeAnalysisLLM):
    def __init__(self):
        super().__init__({"primary_mode": "research"})

    async def chat_completion(self, messages, *args, **kwargs) -> InferenceResult:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        await asyncio.sleep(0.2)
        return InferenceResult(content=json.dumps(self.payload))
