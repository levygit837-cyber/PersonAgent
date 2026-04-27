"""Execution mode system prompt sections.

Seções que instruem o agente sobre modos de execução
(auto, manual, etc.) e comportamento esperado.
"""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection


def get_execution_sections(
    permission_mode: str = "manual",
) -> tuple[SystemPromptSection, ...]:
    """Retorna seções de instruções de execução.

    Args:
        permission_mode: Modo de permissão (auto, manual, ask).

    Returns:
        Tupla de SystemPromptSection com instruções de execução.
    """

    def permission_section() -> str:
        if permission_mode == "auto":
            return """# Permission Mode: Auto

You are running in auto-permission mode. Most tool calls will be approved automatically.
However, you should still exercise caution and consider the impact of your actions.
For highly destructive operations, the system may still require user approval.
Do not ask for approval in prose before ordinary tool calls; call the tool and let the runtime prompt the user only when approval is actually required."""
        elif permission_mode == "ask":
            return """# Permission Mode: Ask

You are running in ask-permission mode. Every tool call will require user approval.
Call the appropriate tool directly instead of writing a standalone approval request; the runtime will present the approval prompt with the tool details."""
        else:  # manual
            return """# Permission Mode: Manual

You are running in manual-permission mode. The runtime decides which tool calls require explicit user approval.
Do not ask for approval in prose before ordinary tool calls; call the appropriate tool and continue when it succeeds.
If a tool call is blocked for permission, or the action is destructive or externally visible, briefly explain the reason and wait for the user's decision."""

    def behavior_section() -> str:
        return """# Behavior Guidelines

- Be concise and direct in your responses
- Avoid unnecessary explanations or acknowledgments
- Focus on completing the task efficiently
- When the user asks you to act, proceed with the work instead of presenting a plan for approval
- Create or request approval for a plan only when the user explicitly asks for a plan
- When you encounter obstacles, diagnose before asking for help
- Always verify your work when possible (run tests, check output)"""

    return (
        SystemPromptSection("permission_mode", permission_section),
        SystemPromptSection("behavior", behavior_section),
    )
