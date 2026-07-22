"""Assemble actual PersonAgent system prompts for benchmark evaluation.

This module mirrors the PromptBuilder logic to assemble the exact system prompts
that the PersonAgent runtime uses, so benchmarks test the real harness.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend src to path
BACKEND_SRC = Path(__file__).parent.parent.parent / "@backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from personagent.domain.prompts.prompt import (
    core_system_prompt_sections,
    get_mode_prompt_section,
    todo_write_policy_section,
    parallel_tool_use_section,
    provider_boundary_section,
    response_style_runtime_reminder_section,
)
from personagent.domain.prompts.sections.agent import (
    get_agent_sections,
    get_frontloaded_agent_sections,
)
from personagent.domain.prompts.sections.execution import get_execution_sections
from personagent.domain.prompts.sections.states import get_agent_state_sections
from personagent.domain.prompts.sections.tools import get_tool_sections
from personagent.domain.prompts.sections.tool_prompts import get_rich_tool_prompt_sections


def assemble_exploration_prompt(
    mode: str = "exploring",
    states: tuple[str, ...] | None = None,
    tools: list[str] | None = None,
    permission_mode: str = "manual",
) -> str:
    """Assemble a full PersonAgent system prompt for exploration benchmarks.

    This mirrors the PromptBuilder logic for the base + tool + execution + agent
    buckets, using the exact same section functions the runtime uses.
    """
    tools = tools or ["Read", "Grep", "Glob", "shell"]
    states = states or ("intake", "context_discovery", "tool_execution", "finalization")

    # Base sections (always present)
    base = core_system_prompt_sections()
    front = get_frontloaded_agent_sections()

    # Mode overlay
    mode_section = (get_mode_prompt_section(mode),)

    # Tool sections
    tool_secs = get_tool_sections(tools)
    # Rich tool prompts - we pass empty defs since we don't have full tool registry
    # The hardcoded TOOL_PROMPTS dict in tool_prompts.py will still provide guidance
    rich_tool_secs = get_rich_tool_prompt_sections([], tools)

    # Execution sections
    provider_boundary = (provider_boundary_section(provider=None, model=None),)
    todo_policy = (todo_write_policy_section(),)
    parallel_policy = (parallel_tool_use_section(),)
    exec_secs = get_execution_sections(permission_mode)

    # Agent sections
    state_secs = get_agent_state_sections(states)
    agent = get_agent_sections()
    runtime_reminder = (response_style_runtime_reminder_section(),)

    # Assemble in order: base -> front -> mode -> tools -> rich_tools -> provider -> todo -> parallel -> exec -> states -> agent -> reminder
    all_sections = (
        base
        + front
        + mode_section
        + tool_secs
        + rich_tool_secs
        + provider_boundary
        + todo_policy
        + parallel_policy
        + exec_secs
        + state_secs
        + agent
        + runtime_reminder
    )

    parts: list[str] = []
    for section in all_sections:
        computed = section.compute()
        if isinstance(computed, str) and computed.strip():
            parts.append(computed.strip())

    return "\n\n".join(parts)


def get_prompt_stats(prompt: str) -> dict:
    """Return token and character stats for a prompt."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = len(enc.encode(prompt))
    except Exception:
        tokens = None

    return {
        "chars": len(prompt),
        "tokens": tokens,
        "lines": prompt.count("\n") + 1,
    }
