"""Section builders for the prompt builder."""

from __future__ import annotations

from personagent.domain.prompts.commands import PromptCommand
from personagent.domain.prompts.models import SystemPromptSection
from personagent.domain.prompts.skills import SkillDefinition


def build_context_lifecycle_section() -> SystemPromptSection:
    def render() -> str:
        return """Context Lifecycle Surfaces

Prompt construction uses cacheable stable sections before the dynamic boundary and runtime sections after it. Session memory, slash command reminders, system context, and user context can change per turn and must be treated as current.

Conversation compaction may replace older messages with a structured reminder; use it for continuity and recent messages for exact state. Next-step suggestions are generated outside the main answer and must not affect the final answer unless the user explicitly follows them."""

    return SystemPromptSection("context_lifecycle", render)


def build_command_sections(
    commands: list[PromptCommand] | None,
) -> tuple[SystemPromptSection, ...]:
    visible = [command for command in commands or [] if not command.disable_model_invocation]
    if not visible:
        return ()

    def render() -> str:
        lines = [
            "Prompt Commands",
            "",
            "Markdown slash commands can provide reusable prompt instructions. If the user invokes one, the expanded command content appears as a runtime reminder. This inventory is lookup data; do not imitate it as a final-answer list.",
        ]
        for command in visible[:80]:
            detail = f"{command.slash_name}: {command.description or 'Prompt command'}"
            if command.argument_hint:
                detail += f" Args: {command.argument_hint}"
            if command.when_to_use:
                detail += f" When: {command.when_to_use}"
            lines.append(detail)
        return "\n".join(lines)

    return (SystemPromptSection("command_inventory", render),)


def build_skill_sections(
    skills: list[SkillDefinition] | None,
) -> tuple[SystemPromptSection, ...]:
    visible = [skill for skill in skills or [] if skill.model_invocable]
    if not visible:
        return ()

    def render() -> str:
        lines = [
            "Skill Inventory",
            "",
            "Skills are progressive-disclosure instruction packs. Load a skill with the Skill tool only when its description matches the current task. This inventory is lookup data; do not imitate it as a final-answer list.",
        ]
        for skill in visible[:100]:
            detail = f"{skill.name}: {skill.description or 'Local skill'}"
            if skill.when_to_use:
                detail += f" When: {skill.when_to_use}"
            if skill.user_invocable:
                detail += f" User slash: {skill.slash_name}"
            lines.append(detail)
        return "\n".join(lines)

    return (SystemPromptSection("skill_inventory", render),)


def build_session_memory_section(memory: str) -> SystemPromptSection:
    def render() -> str:
        return (
            "# Session Memory\n\n"
            "The following memory was maintained for this conversation. Treat it as "
            "continuity context, not as a replacement for the latest user request.\n\n"
            f"{memory.strip()}"
        )

    return SystemPromptSection("session_memory", render, cache_break=True)


def build_relevant_memories_section(memories: list[str]) -> SystemPromptSection:
    def render() -> str:
        lines = [
            "# Relevant Memories",
            "",
            "The following memories were selected as relevant to the current query. "
            "Use them as context, but the user's latest request still defines the immediate task.",
            "",
        ]
        for i, memory in enumerate(memories, 1):
            if memory.strip():
                lines.append(f"## Memory {i}")
                lines.append(memory.strip())
                lines.append("")
        return "\n".join(lines)

    return SystemPromptSection("relevant_memories", render, cache_break=True)
