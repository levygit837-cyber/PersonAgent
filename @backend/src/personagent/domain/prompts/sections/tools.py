"""Tool-specific system prompt sections.

Seções que instruem o agente sobre como usar ferramentas específicas
disponíveis no sistema.
"""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection


def get_tool_sections(tools: list[str] | None = None) -> tuple[SystemPromptSection, ...]:
    """Retorna seções de instruções de ferramentas.

    Args:
        tools: Lista de nomes de ferramentas disponíveis (opcional).

    Returns:
        Tupla de SystemPromptSection com instruções de ferramentas.
    """

    def tool_usage_section() -> str:
        if tools:
            available = ", ".join(tools)
            return f"""# Using Your Tools

You have access to the following tools: {available}.

When using tools:
- Always provide the required parameters in the correct format
- Read tool results carefully before proceeding
- If a tool fails, analyze the error and adjust your approach
- Prefer using dedicated tools over shell commands when available"""
        return """# Using Your Tools

You have access to various tools to help you complete tasks.

When using tools:
- Always provide the required parameters in the correct format
- Read tool results carefully before proceeding
- If a tool fails, analyze the error and adjust your approach
- Prefer using dedicated tools over shell commands when available"""

    def file_operations_section() -> str:
        return """# File Operations

- Use Read to examine file contents before making changes
- Use Edit or Write to modify files
- Use Glob and Grep for file discovery and text search
- When editing files, provide the exact old_string to match
- Be precise with file paths - use absolute paths or resolve relative paths correctly"""

    def shell_section() -> str:
        return """# Shell Commands

- Shell commands are executed in a read-only mode by default
- For read-only commands (cat, grep, git, etc.), no approval is needed
- For potentially destructive commands, user approval will be required
- Always prefer using dedicated tools over shell commands when available"""

    return (
        SystemPromptSection("tool_usage", tool_usage_section),
        SystemPromptSection("file_operations", file_operations_section),
        SystemPromptSection("shell", shell_section),
    )
