"""Use case para recall de memórias relevantes.

Orquestra o MemoryRecallSelector para selecionar memórias
relevantes a uma query do usuário.
"""

from __future__ import annotations

from pathlib import Path

from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector


class RecallMemoryUseCase:
    """Orquestra o recall de memórias relevantes."""

    def __init__(
        self,
        recall_selector: MemoryRecallSelector,
    ) -> None:
        self._recall_selector = recall_selector

    async def execute(
        self,
        query: str,
        memory_dir: Path,
        recent_tools: list[str] | None = None,
        already_surfaced: set[str] | None = None,
    ) -> list[RelevantMemory]:
        """Executa o recall de memórias relevantes.

        Args:
            query: Mensagem do usuário.
            memory_dir: Diretório de memória a escanear.
            recent_tools: Ferramentas usadas recentemente.
            already_surfaced: Paths já injetados nesta sessão.

        Returns:
            Lista de memórias relevantes selecionadas.
        """
        return await self._recall_selector.select_relevant(
            query=query,
            memory_dir=memory_dir,
            recent_tools=recent_tools,
            already_surfaced=already_surfaced,
        )
