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
        return f"""Available Tools

Callable tools exposed in this request: {available}.

Use exact schemas, read tool results before deciding the next step, and change approach when a tool returns an error. Prefer the most specific available tool for the job. This section is operational guidance, not a template for the final response."""

    def file_operations_section() -> str:
        guidance: list[str] = []
        if "Read" in tool_set:
            guidance.append("Read examines file contents before claims or edits")
        if "Edit" in tool_set:
            guidance.append("Edit handles targeted modifications with exact old_string matches")
        if "Write" in tool_set:
            guidance.append("Write is only for creating a new file or intentionally replacing a whole file")
        if "Glob" in tool_set:
            guidance.append("Glob discovers files when the path is unknown")
        if "Grep" in tool_set:
            guidance.append("Grep performs focused text or symbol search before reading many files")
        body = "; ".join(guidance) or "Use file tools according to their schemas"
        return (
            "File Operations\n\n"
            f"{body}. Be precise with file paths: use absolute paths or resolve relative paths correctly."
        )

    def shell_section() -> str:
        return """Shell Commands

Shell commands are read-only by default. Read-only commands such as cat, grep, and git do not need approval, while write/exec/network commands may require approval depending on permission mode. Critical commands are denied instead of being sent for approval. Prefer dedicated tools over shell commands when available."""

    sections: list[SystemPromptSection] = [SystemPromptSection("tool_usage", tool_usage_section)]
    if tool_set.intersection({"Read", "Write", "Edit", "Glob", "Grep"}):
        sections.append(SystemPromptSection("file_operations", file_operations_section))
    if "shell" in tool_set:
        sections.append(SystemPromptSection("shell", shell_section))
    return tuple(sections)
