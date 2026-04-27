"""Unit tests for PromptBuilder."""

import json

import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.prompts import infer_prompt_mode
from personagent.domain.prompts.models import SystemPromptSection
from personagent.domain.prompts.prompt import PROMPT_DYNAMIC_BOUNDARY, get_mode_prompt_section
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
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
            claude_md="# Project Instructions\n\nThis is a test project.",
            current_date="2024-01-15",
        )

    @pytest.mark.asyncio
    async def test_build_basic_prompt(self, system_context, user_context):
        """Test building a basic system prompt."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.content is not None
        assert len(result.content) > 0
        assert "# Introduction" in result.content
        assert "# Operating Principles" in result.content

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

    @pytest.mark.asyncio
    async def test_build_with_agent_sections_enabled(self, system_context, user_context):
        """Test building prompt with agent sections enabled."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=True)
        result = await builder.build(system_context, user_context)

        assert "# Agent Identity" in result.content
        assert "PersonAgent" in result.content

    @pytest.mark.asyncio
    async def test_build_with_agent_sections_disabled(self, system_context, user_context):
        """Test building prompt with agent sections disabled."""
        builder = PromptBuilder(permission_mode="manual", enable_agent_sections=False)
        result = await builder.build(system_context, user_context)

        assert "# Agent Identity" not in result.content

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
    async def test_build_without_claude_md(self, system_context):
        """Test building prompt without persona.md."""
        user_context = UserContext(claude_md=None)
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
    async def test_metadata_includes_has_claude_md(self, system_context, user_context):
        """Test that metadata includes has_claude_md."""
        builder = PromptBuilder(permission_mode="manual")
        result = await builder.build(system_context, user_context)

        assert result.metadata["has_claude_md"] is True

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
        assert "intro" in result.sections_used
        assert "operating_principles" in result.sections_used

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
    async def test_prompt_context_analyzer_fallback_has_no_keyword_matching(self):
        llm = FakeAnalysisLLM("not json")
        analyzer = PromptContextAnalyzer(llm)

        profile = await analyzer.analyze(
            message="Implemente o backend",
            requested_mode="auto",
        )

        assert profile.primary_mode == "exploring"
        assert profile.source == "fallback"

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
    async def test_prompt_mode_override(self, system_context, user_context):
        builder = PromptBuilder(permission_mode="manual")

        result = await builder.build(
            system_context,
            user_context,
            prompt_mode="research",
            user_message="Implemente algo",
        )

        assert result.metadata["prompt_mode"] == "research"
        assert "# Research Mode" in result.content

    @pytest.mark.parametrize("mode", ["writing", "exploring", "research"])
    def test_each_mode_prompt_has_500_plus_instruction_lines(self, mode):
        content = get_mode_prompt_section(mode).compute()

        assert isinstance(content, str)
        assert len(content.splitlines()) >= 500

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
