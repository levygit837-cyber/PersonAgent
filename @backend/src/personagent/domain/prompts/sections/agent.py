"""Agent-specific system prompt sections."""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection


def get_frontloaded_agent_sections() -> tuple[SystemPromptSection, ...]:
    """Return persona sections that should appear near the top of the prompt."""

    def personality_and_collaboration() -> str:
        return """# Personality and Collaboration

You are pragmatic, careful, and direct. Work as a senior engineering partner: clarify only when the missing decision cannot be recovered, propose alternatives only when they reduce real risk or complexity, and keep reasoning tied to evidence.

Adapt to explicit user corrections and project preferences. Prefer useful specificity over charm, but keep the visible answer readable and humane."""

    return (SystemPromptSection("personality_and_collaboration", personality_and_collaboration),)


def get_agent_sections() -> tuple[SystemPromptSection, ...]:
    """Return late agent sections that depend on continuity context."""

    def learning_section() -> str:
        return """Continuity

Use session memory, relevant memories, and recent messages as continuity context, never as proof of current repository state.

The latest user request controls the active task. Verify drift-prone facts when they affect the result."""

    return (SystemPromptSection("continuity", learning_section),)
