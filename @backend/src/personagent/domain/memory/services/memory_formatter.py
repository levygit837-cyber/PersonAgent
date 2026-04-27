"""Serviço de formatação de memórias para injeção no prompt.

Converte RelevantMemory em strings formatadas para o contexto
da conversa, seguindo o padrão do Claude Code.
"""

from __future__ import annotations

from personagent.domain.memory.models.relevant_memory import RelevantMemory


class MemoryFormatter:
    """Formata memórias relevantes para injeção no contexto."""

    @staticmethod
    def format_for_attachment(memory: RelevantMemory) -> str:
        """Formata uma memória relevante como attachment no prompt.

        Args:
            memory: Memória relevante selecionada.

        Returns:
            String formatada para injeção como system-reminder.
        """
        lines = [
            f"# Memory: {memory.path}",
            f"_Saved {memory.header}_",
            "",
            memory.content,
        ]
        if memory.truncated_at_line:
            lines.append(
                f"\n[...truncated at line {memory.truncated_at_line}...]"
            )
        return "\n".join(lines)

    @staticmethod
    def format_relevant_memories(memories: list[RelevantMemory]) -> list[str]:
        """Formata uma lista de memórias relevantes.

        Args:
            memories: Lista de memórias selecionadas.

        Returns:
            Lista de strings formatadas, uma por memória.
        """
        return [MemoryFormatter.format_for_attachment(m) for m in memories]

    @staticmethod
    def format_memory_index(index_content: str | None) -> str | None:
        """Formata o conteúdo do MEMORY.md para inclusão no contexto.

        Args:
            index_content: Conteúdo do MEMORY.md.

        Returns:
            String formatada ou None se não houver conteúdo.
        """
        if not index_content or not index_content.strip():
            return None
        return f"# Memory Index\n\n{index_content.strip()}"
