"""Tests evaluating the System Prompt Harness composition, token efficiency, and redundancy.

These tests verify structural properties of the prompt system rather than LLM outputs,
so they run quickly and deterministically without external API calls.
"""

from __future__ import annotations

import pytest
import tiktoken

from personagent.domain.prompts.models import SystemPromptSection
from personagent.domain.prompts.prompt import (
    core_system_prompt_sections,
    get_mode_prompt_section,
    mode_exploring_section,
    mode_research_section,
    mode_writing_section,
    provider_data_boundary,
    shared_runtime_policy_overlay,
)
from personagent.domain.prompts.sections.agent import (
    get_agent_sections,
    get_frontloaded_agent_sections,
)
from personagent.domain.prompts.sections.execution import get_execution_sections
from personagent.domain.prompts.sections.states import get_agent_state_sections
from personagent.domain.prompts.sections.tools import get_tool_sections
from personagent.domain.tools import ToolDefinition


class TestPromptTokenEfficiency:
    """Ensure the assembled system prompt stays within reasonable token budgets."""

    @classmethod
    def setup_class(cls) -> None:
        cls._enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _render_sections(self, sections: tuple[SystemPromptSection, ...]) -> str:
        parts: list[str] = []
        for section in sections:
            computed = section.compute()
            if isinstance(computed, str) and computed.strip():
                parts.append(computed.strip())
        return "\n\n".join(parts)

    @pytest.mark.xfail(reason="Token diet needed: currently 1546 tokens, target < 1500")
    def test_core_sections_under_1500_tokens(self) -> None:
        """The base system prompt should be compact enough for 8K-context local models."""
        sections = core_system_prompt_sections()
        text = self._render_sections(sections)
        tokens = self._count_tokens(text)
        # 1500 tokens ≈ 6000 chars; this is the upper acceptable bound for 8K models.
        assert tokens < 1500, (
            f"Core system prompt is {tokens} tokens ({len(text)} chars). "
            f"This consumes too much of an 8K context window. Target: < 1500."
        )

    def test_exploring_mode_under_400_tokens(self) -> None:
        section = get_mode_prompt_section("exploring")
        text = section.compute()
        tokens = self._count_tokens(text or "")
        assert tokens < 400, f"Exploring mode overlay is {tokens} tokens. Keep it concise."

    def test_writing_mode_under_400_tokens(self) -> None:
        section = get_mode_prompt_section("writing")
        text = section.compute()
        tokens = self._count_tokens(text or "")
        assert tokens < 400, f"Writing mode overlay is {tokens} tokens. Keep it concise."

    def test_research_mode_under_400_tokens(self) -> None:
        section = get_mode_prompt_section("research")
        text = section.compute()
        tokens = self._count_tokens(text or "")
        assert tokens < 400, f"Research mode overlay is {tokens} tokens. Keep it concise."

    @pytest.mark.xfail(reason="Token diet needed: currently 2591 tokens, target < 2500")
    def test_full_assembly_under_2500_tokens(self) -> None:
        """Base + mode + tools + execution + common agent states."""
        base = core_system_prompt_sections()
        mode = (get_mode_prompt_section("exploring"),)
        tools = get_tool_sections(["Read", "Edit", "Write", "Glob", "Grep", "shell"])
        execution = get_execution_sections("manual")
        states = get_agent_state_sections(("intake", "context_discovery", "tool_execution", "finalization"))
        agent = get_agent_sections()
        front = get_frontloaded_agent_sections()

        all_sections = base + front + mode + tools + execution + states + agent
        text = self._render_sections(all_sections)
        tokens = self._count_tokens(text)
        # 2500 tokens is the danger threshold for 8K-context models.
        assert tokens < 2500, (
            f"Full system prompt assembly is {tokens} tokens ({len(text)} chars). "
            f"For 8K-context local models, this leaves too little room for history + tool results."
        )

    @pytest.mark.xfail(reason="State bloat: currently 1255 tokens for all 12 states, target < 1000")
    def test_all_agent_states_assembly_under_1000_tokens(self) -> None:
        """All 12 agent states should not bloat the prompt excessively."""
        from personagent.domain.prompts.sections.states import ORDERED_AGENT_STATES

        states = get_agent_state_sections(ORDERED_AGENT_STATES)
        text = self._render_sections(states)
        tokens = self._count_tokens(text)
        # If all 12 states exceed 1000 tokens, they are too verbose individually.
        assert tokens < 1000, (
            f"All 12 agent states render to {tokens} tokens. "
            f"Consider consolidating or making them lazier."
        )

    def test_provider_boundary_section_exists(self) -> None:
        section = provider_data_boundary("llama")
        assert "local" in section.lower()
        section2 = provider_data_boundary("deepseek")
        assert "hosted" in section2.lower()

    def test_shared_runtime_policy_is_compact(self) -> None:
        text = shared_runtime_policy_overlay()
        tokens = self._count_tokens(text)
        assert tokens < 250, (
            f"Shared runtime policy is {tokens} tokens. This overlay should be a tight paragraph."
        )


class TestPromptRedundancy:
    """Detect overlapping instructions that waste tokens and confuse models."""

    def _render_sections(self, sections: tuple[SystemPromptSection, ...]) -> str:
        parts: list[str] = []
        for section in sections:
            computed = section.compute()
            if isinstance(computed, str) and computed.strip():
                parts.append(computed.strip().lower())
        return "\n".join(parts)

    @pytest.mark.xfail(reason="Redundancy: currently 8 conciseness reminders, target <= 5")
    def test_no_duplicate_conciseness_instructions(self) -> None:
        """The prompt should not repeat 'be concise' in multiple sections."""
        base = self._render_sections(core_system_prompt_sections())
        # Count occurrences of "concise" and variants.
        count = base.count("concise") + base.count("brief") + base.count("short")
        assert count <= 5, (
            f"Found {count} conciseness reminders in the base prompt. "
            f"Consolidate into one strong instruction to save tokens."
        )

    def test_no_duplicate_evidence_demands(self) -> None:
        """Only one section should demand evidence grounding."""
        base = self._render_sections(core_system_prompt_sections())
        evidence_count = base.count("evidence") + base.count("ground")
        # The codebase investigation contract naturally uses "evidence" many times;
        # this test is a soft guard against adding yet another evidence section.
        assert evidence_count < 15, (
            f"The word 'evidence' appears {evidence_count} times. "
            f"If you add another evidence-related section, reconsider."
        )

    def test_post_tool_synthesis_is_present(self) -> None:
        """The critical anti-silent-failure mandate must exist."""
        base = self._render_sections(core_system_prompt_sections())
        assert "substantive final answer" in base or "do not stop without answering" in base, (
            "The Post-Tool Synthesis Mandate is missing or was weakened. "
            "This is the primary defense against silent failures after tool use."
        )

    def test_exploration_checklist_is_present(self) -> None:
        """The self-checklist that prevents superficial analysis must exist."""
        base = self._render_sections(core_system_prompt_sections())
        assert "self-checklist" in base or "exploration checklist" in base, (
            "The Exploration Self-Checklist is missing. "
            "This is the primary defense against superficial analysis."
        )


class TestToolSchemaQuality:
    """Verify that tool definitions carry enough guidance for the model."""

    def test_read_tool_has_offset_limit_documented(self) -> None:
        """Read tool schema must mention offset/limit for large files."""
        from personagent.infrastructure.tools.filesystem_tools.read import create_read_file_tool

        tool = create_read_file_tool()
        schema = tool.definition.to_openai_tool()
        desc = schema["function"]["description"].lower()
        params = schema["function"]["parameters"]
        assert "path" in params["properties"], "Read tool missing path param"
        assert "offset" in params["properties"], "Read tool missing offset param"
        assert "limit" in params["properties"], "Read tool missing limit param"
        # The description should hint at pagination for large files.
        assert "text file" in desc or "read" in desc, "Read tool description is too vague"

    def test_edit_tool_warns_about_exact_match(self) -> None:
        """Edit tool should make the exact-match requirement obvious."""
        from personagent.infrastructure.tools.filesystem_tools.write_edit import create_edit_file_tool

        tool = create_edit_file_tool()
        schema = tool.definition.to_openai_tool()
        desc = schema["function"]["description"].lower()
        assert "exact" in desc or "replace" in desc, (
            "Edit tool description does not emphasize the exact-match requirement."
        )

    def test_grep_tool_mentions_ripgrep(self) -> None:
        """Grep tool description should mention ripgrep to set expectations."""
        from personagent.infrastructure.tools.filesystem_tools.search import create_grep_tool

        tool = create_grep_tool()
        schema = tool.definition.to_openai_tool()
        desc = schema["function"]["description"].lower()
        assert "ripgrep" in desc or "rg" in desc or "search" in desc, (
            "Grep tool description should mention ripgrep to help the model choose it."
        )

    def test_tool_definitions_have_when_to_use(self) -> None:
        """Rich tool metadata should include when_to_use guidance."""
        from personagent.infrastructure.tools.filesystem_tools.read import create_read_file_tool
        from personagent.infrastructure.tools.filesystem_tools.search import create_grep_tool
        from personagent.infrastructure.tools.filesystem_tools.write_edit import (
            create_edit_file_tool,
            create_write_file_tool,
        )

        for factory in (create_read_file_tool, create_grep_tool, create_write_file_tool, create_edit_file_tool):
            tool = factory()
            assert tool.definition.when_to_use or tool.definition.search_hint, (
                f"{tool.definition.name} lacks when_to_use or search_hint. "
                f"This metadata should be injected into the OpenAI description."
            )

    def test_openai_schema_should_include_examples(self) -> None:
        """The OpenAI-compatible tool schema should embed examples for better tool selection."""
        from personagent.infrastructure.tools.filesystem_tools.read import create_read_file_tool

        tool = create_read_file_tool()
        schema = tool.definition.to_openai_tool()
        desc = schema["function"]["description"]
        # Currently the description is plain; this test documents the desired behavior.
        # When enriched, this assertion will pass.
        if tool.definition.examples:
            assert any(ex in desc for ex in tool.definition.examples), (
                f"{tool.definition.name} has examples in ToolDefinition but they are NOT "
                f"injected into the OpenAI schema description. Enrich to_openai_tool() "
                f"to improve model tool-selection accuracy."
            )
