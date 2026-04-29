from __future__ import annotations

import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.prompts.commands import (
    CommandRegistry,
    CommandService,
    parse_slash_invocation,
)
from personagent.domain.prompts.context_attachments import resolve_context_attachments
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


def test_command_service_exposes_supported_builtins():
    service = CommandService()
    builtins = {command.name: command for command in service.list_builtin_commands()}
    resolution = service.resolve_builtin("/mcp github:list")

    assert {"plan", "memory", "mcp", "skills", "context", "files", "doctor", "help"} <= set(
        builtins
    )
    assert resolution is not None
    assert resolution.command.name == "mcp"
    assert "ReadMcpResourceTool" in resolution.metadata()["allowed_tools"]


def test_context_attachments_expand_file_ranges_as_hidden_context(tmp_path):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("one\nprint('two')\nthree\n", encoding="utf-8")

    result = resolve_context_attachments(
        [
            {
                "type": "viewer_annotation",
                "file_path": str(source),
                "display_path": "src/app.py",
                "start_line": 2,
                "end_line": 2,
                "text": "Update this line",
                "language": "python",
            }
        ],
        workspace_root=tmp_path,
    )

    assert result.metadata == [
        {
            "type": "viewer_annotation",
            "id": 1,
            "label": "@Annotation#1",
            "file_name": "app.py",
            "file_path": str(source.resolve()),
            "display_path": "src/app.py",
            "start_line": 2,
            "end_line": 2,
            "language": "python",
            "text": "Update this line",
            "truncated": False,
        }
    ]
    assert len(result.reminders) == 1
    assert "<attached-context type=\"viewer_annotation\">" in result.reminders[0]
    assert "print('two')" in result.reminders[0]


def test_context_attachments_expand_browser_annotations_without_files(tmp_path):
    result = resolve_context_attachments(
        [
            {
                "type": "browser_annotation",
                "id": 7,
                "url": "https://example.com/search?q=personagent",
                "title": "Search results",
                "node_id": "pa_button_1",
                "selector": "html > body > form > button",
                "role": "button",
                "text": "Use this result",
                "quote": "PersonAgent browser automation",
            }
        ],
        workspace_root=tmp_path,
    )

    assert result.metadata == [
        {
            "type": "browser_annotation",
            "id": 7,
            "label": "@Annotation#1",
            "url": "https://example.com/search?q=personagent",
            "title": "Search results",
            "node_id": "pa_button_1",
            "selector": "html > body > form > button",
            "role": "button",
            "text": "Use this result",
            "content_preview": "PersonAgent browser automation",
            "content_char_count": len("PersonAgent browser automation"),
            "truncated": False,
        }
    ]
    assert "<attached-context type=\"browser_annotation\">" in result.reminders[0]
    assert "Element node_id: pa_button_1" in result.reminders[0]
    assert "User annotation: Use this result" in result.reminders[0]


def test_context_attachments_expand_browser_tab_targets(tmp_path):
    result = resolve_context_attachments(
        [
            {
                "type": "browser_tab",
                "id": "browser_tab:conversation-1:page_github",
                "label": "@Browser",
                "browser_id": "conversation-1",
                "tab_id": "page_github",
                "page_id": "page_github",
                "url": "https://github.com/personagent/personagent",
                "title": "GitHub - PersonAgent",
                "runtime": "lightpanda",
                "active": True,
                "state": {"scroll": {"y": 120}},
            }
        ],
        workspace_root=tmp_path,
    )

    assert result.metadata[0]["type"] == "browser_tab"
    assert result.metadata[0]["browser_id"] == "conversation-1"
    assert result.metadata[0]["page_id"] == "page_github"
    assert result.metadata[0]["scroll"] == {"y": 120}
    assert "shared Browser panel tab" in result.reminders[0]
    assert "page_github" in result.reminders[0]


def test_context_attachments_expand_browser_url_targets_without_page_id(tmp_path):
    result = resolve_context_attachments(
        [
            {
                "type": "browser_tab",
                "id": "browser_tab:conversation-1:github.com",
                "label": "@Browser",
                "browser_id": "conversation-1",
                "url": "https://github.com/",
                "title": "Browser target: github.com",
                "display_path": "https://github.com/",
            }
        ],
        workspace_root=tmp_path,
    )

    assert result.metadata[0]["type"] == "browser_tab"
    assert result.metadata[0]["browser_id"] == "conversation-1"
    assert result.metadata[0]["page_id"] == ""
    assert result.metadata[0]["url"] == "https://github.com/"
    assert "shared Browser window" in result.reminders[0]
    assert "BrowserOpen with the URL above" in result.reminders[0]


def test_context_attachments_reject_paths_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the workspace"):
        resolve_context_attachments(
            [{"type": "file", "file_path": str(outside)}],
            workspace_root=tmp_path,
        )


def test_context_attachments_expand_skill_body_from_backend_inventory(tmp_path):
    skill_dir = tmp_path / ".personagent" / "skills" / "debug-root-cause"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: Debug Root Cause
description: Investigate failures end to end
---
Follow the live runtime path before patching symptoms.
""",
        encoding="utf-8",
    )

    result = resolve_context_attachments(
        [{"type": "skill", "invocation_name": "debug-root-cause"}],
        workspace_root=tmp_path,
    )

    assert result.metadata == [
        {
            "type": "skill",
            "id": 1,
            "label": "@skill:debug-root-cause",
            "name": "Debug Root Cause",
            "invocation_name": "debug-root-cause",
            "slash_name": "/debug-root-cause",
            "description": "Investigate failures end to end",
            "path": str(skill_file.resolve()),
            "display_path": ".personagent/skills/debug-root-cause/SKILL.md",
            "source": "workspace",
            "truncated": False,
        }
    ]
    assert "<attached-context type=\"skill\">" in result.reminders[0]
    assert "Follow the live runtime path before patching symptoms." in result.reminders[0]


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
