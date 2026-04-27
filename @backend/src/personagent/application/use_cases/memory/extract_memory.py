"""Use case para extração automática de memórias.

Orquestra o MemoryExtractor para extrair memórias de uma conversa.
"""

from __future__ import annotations

from pathlib import Path

from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.services.memory_extractor import MemoryExtractor
from personagent.domain.models.conversation import Conversation


class ExtractMemoryUseCase:
    """Orquestra a extração de memórias de uma conversa."""

    def __init__(
        self,
        memory_extractor: MemoryExtractor,
    ) -> None:
        self._memory_extractor = memory_extractor

    async def execute(
        self,
        conversation: Conversation,
        memory_dir: Path,
        max_turns: int = 5,
    ) -> list[MemoryFile]:
        """Executa a extração de memórias.

        Args:
            conversation: Conversa a analisar.
            memory_dir: Diretório de memória.
            max_turns: Máximo de turns a analisar.

        Returns:
            Lista de memórias extraídas.
        """
        return await self._memory_extractor.extract_from_conversation(
            conversation,
            memory_dir,
            max_turns=max_turns,
        )
