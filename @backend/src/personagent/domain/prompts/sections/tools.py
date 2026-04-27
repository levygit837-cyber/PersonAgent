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

    tool_set = {tool for tool in tools or [] if tool}
    if not tool_set:
        return ()

    def tool_usage_section() -> str:
        available = ", ".join(sorted(tool_set))
        return f"""# Available Tools

Callable tools exposed in this request: {available}.

When using tools:
- Provide required parameters in the exact schema.
- Read tool results before deciding the next step.
- If a tool fails, use the error to change approach.
- Prefer the most specific available tool for the job."""

    def file_operations_section() -> str:
        lines = ["# File Operations", ""]
        if "Read" in tool_set:
            lines.append("- Use Read to examine file contents before making claims or edits.")
        if "Edit" in tool_set:
            lines.append("- Use Edit for targeted modifications with exact old_string matches.")
        if "Write" in tool_set:
            lines.append("- Use Write only when creating a new file or replacing a whole file intentionally.")
        if "Glob" in tool_set:
            lines.append("- Use Glob for file discovery when the path is unknown.")
        if "Grep" in tool_set:
            lines.append("- Use Grep for focused text or symbol search before reading many files.")
        lines.append("- Be precise with file paths: use absolute paths or resolve relative paths correctly.")
        return "\n".join(lines)

    def shell_section() -> str:
        return """# Shell Commands

- Shell commands are executed in a read-only mode by default
- For read-only commands (cat, grep, git, etc.), no approval is needed
- For potentially destructive commands, user approval will be required
- Always prefer using dedicated tools over shell commands when available"""

    sections: list[SystemPromptSection] = [SystemPromptSection("tool_usage", tool_usage_section)]
    if tool_set.intersection({"Read", "Write", "Edit", "Glob", "Grep"}):
        sections.append(SystemPromptSection("file_operations", file_operations_section))
    if "shell" in tool_set:
        sections.append(SystemPromptSection("shell", shell_section))
    return tuple(sections)
