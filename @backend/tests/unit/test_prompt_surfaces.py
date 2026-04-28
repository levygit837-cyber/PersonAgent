from __future__ import annotations

import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.prompts.commands import CommandRegistry, parse_slash_invocation
from personagent.domain.prompts.models import PromptProfile
from personagent.domain.prompts.services import PromptBuilder
from personagent.domain.prompts.skills import (
    SkillDefinition,
    discover_enabled_skills,
    discover_skills,
    find_skill,
    set_skill_activation,
)
from personagent.domain.tools import ToolDefinition


def test_command_registry_loads_frontmatter_and_expands_arguments(tmp_path):
    commands_dir = tmp_path / ".personagent" / "commands"
    commands_dir.mkdir(parents=True)
    command_file = commands_dir / "review.md"
    command_file.write_text(
        """---
description: Review a target
allowed-tools: Read, Grep
model: inherit
argument-hint: [target]
when_to_use: when the user wants review
context: inline
---
Review $1 with all args: $ARGUMENTS and owner $owner.
""",
        encoding="utf-8",
    )

    registry = CommandRegistry()
    commands = registry.list_commands(tmp_path)
    resolution = registry.resolve("/review src/app.py owner=levy", tmp_path)

    assert [command.name for command in commands] == ["review"]
    assert commands[0].allowed_tools == ("Read", "Grep")
    assert resolution is not None
    assert "Review src/app.py" in resolution.expanded_prompt
    assert "owner levy" in resolution.expanded_prompt


def test_command_registry_resolves_nested_slash_commands(tmp_path):
    commands_dir = tmp_path / ".personagent" / "commands" / "review"
    commands_dir.mkdir(parents=True)
    (commands_dir / "code.md").write_text(
        """---
description: Review code
---
Review code in $ARGUMENTS.
""",
        encoding="utf-8",
    )

    registry = CommandRegistry()
    resolution = registry.resolve("/review/code src", tmp_path)

    assert parse_slash_invocation("/review/code src") == ("review/code", "src")
    assert resolution is not None
    assert resolution.command.name == "review/code"
    assert "Review code in src." in resolution.expanded_prompt


def test_skill_discovery_finds_nested_codex_style_skills(tmp_path):
    skill_dir = tmp_path / "plugin-dev" / "skills" / "agent-development"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: Agent Development
description: Build local agents
user-invocable: true
---
Follow agent development instructions.
""",
        encoding="utf-8",
    )

    skills = discover_skills(extra_roots=(tmp_path,))
    skill = find_skill("agent-development", extra_roots=(tmp_path,))

    discovered = {item.invocation_name: item for item in skills}
    assert "agent-development" in discovered
    assert discovered["agent-development"].slash_name == "/agent-development"
    assert skill is not None
    assert skill.name == "Agent Development"


def test_skill_activation_filters_prompt_inventory(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace_skill = workspace / ".personagent" / "skills" / "writer"
    codex_skill = home / ".codex" / "skills" / "global-review"
    workspace_skill.mkdir(parents=True)
    codex_skill.mkdir(parents=True)
    (workspace_skill / "SKILL.md").write_text(
        """---
name: Writer
description: Write clean prose
---
Use concise prose.
""",
        encoding="utf-8",
    )
    (codex_skill / "SKILL.md").write_text(
        """---
name: Global Review
description: Review globally
---
Review code.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PERSONAGENT_SKILL_STATE_PATH", str(tmp_path / "state.json"))

    assert [skill.invocation_name for skill in discover_enabled_skills(workspace_root=workspace)] == [
        "writer"
    ]

    set_skill_activation("global-review", True)
    assert [skill.invocation_name for skill in discover_enabled_skills(workspace_root=workspace)] == [
        "global-review",
        "writer",
    ]

    set_skill_activation("writer", False)
    assert [skill.invocation_name for skill in discover_enabled_skills(workspace_root=workspace)] == [
        "global-review"
    ]


@pytest.mark.asyncio
async def test_prompt_builder_composes_surfaces_tool_prompts_memory_and_reminders(tmp_path):
    builder = PromptBuilder(permission_mode="manual")
    profile = PromptProfile(
        primary_mode="writing",
        secondary_modes=("research",),
        intent="write after research",
        surface_hints=("command", "skill", "memory", "next_step"),
        confidence=0.9,
        source="llm",
    )
    command = CommandRegistry().list_commands(tmp_path)
    skill = SkillDefinition(
        name="writer",
        body="Write clean artifacts.",
        path=tmp_path / "writer" / "SKILL.md",
        description="Use for writing",
    )
    tool = ToolDefinition(
        name="Read",
        description="Read files",
        input_schema={"type": "object", "properties": {}},
        usage_prompt="Read before editing.",
    )

    result = await builder.build(
        SystemContext(workspace_root=str(tmp_path)),
        UserContext(current_date="2026-04-26"),
        available_tools=["Read"],
        prompt_profile=profile,
        available_tool_definitions=[tool],
        command_inventory=command,
        skill_inventory=[skill],
        session_memory="# Current State\n\nWorking on prompts.",
        runtime_reminders=["# Slash Command Context\n\nExpanded command."],
    )

    assert "# Mode Overlay: Writing" in result.content
    assert "# Mode Overlay: Research" in result.content
    assert "# Tool Prompts" in result.content
    assert "Read before editing." in result.content
    assert "# Skill Inventory" in result.content
    assert "# Session Memory" in result.content
    assert result.content.index("# Dynamic Context Boundary") < result.content.index("# Session Memory")
    assert result.user_context_message is not None
    assert "Expanded command." in result.user_context_message
    assert result.metadata["prompt_analysis_source"] == "llm"
    assert result.metadata["prompt_analysis_confidence"] == 0.9
    assert "memory" in result.metadata["prompt_surfaces_used"]
    assert "tool_prompts" in result.metadata["prompt_surfaces_used"]
    assert "slash" in result.metadata["prompt_surfaces_used"]
