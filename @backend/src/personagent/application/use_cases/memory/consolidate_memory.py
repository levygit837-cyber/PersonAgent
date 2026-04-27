"""Use case para consolidação automática de memórias.

Orquestra o MemoryConsolidator para reorganizar memórias.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.domain.memory.services.memory_consolidator import MemoryConsolidator


class ConsolidateMemoryUseCase:
    """Orquestra a consolidação de memórias."""

    def __init__(
        self,
        memory_consolidator: MemoryConsolidator,
    ) -> None:
        self._memory_consolidator = memory_consolidator

    async def execute(
        self,
        memory_dir: Path,
    ) -> list[dict[str, Any]]:
        """Executa a consolidação de memórias.

        Args:
            memory_dir: Diretório de memória a consolidar.

        Returns:
            Lista de ações executadas.
        """
        return await self._memory_consolidator.consolidate(memory_dir)
