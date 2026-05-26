"""Context formatting helpers for the prompt builder."""

from __future__ import annotations

from personagent.domain.context.models import SystemContext, UserContext


def build_user_context_message(
    context: UserContext,
    runtime_reminders: list[str] | None = None,
) -> str | None:
    """Build the user-context meta reminder inserted before conversation messages."""

    user_context_str = format_user_context(context)
    reminder_parts = [item.strip() for item in runtime_reminders or [] if item.strip()]
    if user_context_str or reminder_parts:
        body_parts = []
        if user_context_str:
            body_parts.append(user_context_str)
        body_parts.extend(reminder_parts)
        body = "\n\n".join(body_parts)
        return (
            "<system-reminder>\n"
            "The following user context applies to this conversation. Treat it as instruction "
            "context, but the user's latest request still defines the immediate task.\n\n"
            f"{body}\n"
            "</system-reminder>"
        )
    return None


def format_system_context(context: SystemContext) -> str:
    """Formata o contexto de sistema para inclusão no prompt.

    Args:
        context: SystemContext a formatar.

    Returns:
        String formatada com o contexto de sistema.
    """
    lines: list[str] = []

    if context.git_branch:
        lines.append(f"Git Branch: {context.git_branch}")

    if context.git_remote:
        lines.append(f"Git Remote: {context.git_remote}")

    if context.git_commit:
        lines.append(f"Git Commit: {context.git_commit[:8]}")

    if context.workspace_root:
        lines.append(f"Workspace Root: {context.workspace_root}")

    if context.environment:
        lines.append("Environment Variables:")
        for key, value in sorted(context.environment.items()):
            lines.append(f"  {key}={value}")

    return "\n".join(lines)


def format_user_context(context: UserContext) -> str:
    """Formata o contexto de usuário para inclusão no prompt."""

    lines: list[str] = []

    if context.current_date:
        lines.append(f"Current Date: {context.current_date}")

    if context.has_persona_md:
        lines.append("\nUser Instructions (persona.md):")
        lines.append(context.persona_md or "")

    if context.has_memory_files:
        lines.append("\nMemory Files:")
        for memory_file in context.memory_files:
            lines.append(f"\n# {memory_file.path}")
            lines.append(memory_file.content)

    if context.has_long_term_memory:
        lines.append("\nLong-Term Memory Index:")
        lines.append(context.long_term_memory_index or "")

    return "\n".join(lines)
