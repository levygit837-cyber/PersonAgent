"""Worker para extração automática de memórias.

Processa jobs do tipo EXTRACT_MEMORIES:
1. Carrega a conversa
2. Verifica se o agente já escreveu memória neste turn
3. Extrai memórias duráveis
4. Persiste no filesystem
5. Atualiza MEMORY.md
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from uuid import UUID

import structlog

from personagent.application.jobs.memory_job import MemoryJob
from personagent.domain.memory.models.memory_types import MemoryScope
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_extractor import MemoryExtractor
from personagent.domain.repositories.conversation_repository import ConversationRepository

logger = structlog.get_logger(__name__)


class ExtractMemoryWorker:
    """Worker de extração de memórias."""

    def __init__(
        self,
        memory_repository: MemoryRepository,
        memory_extractor: MemoryExtractor,
        conversation_repo: ConversationRepository | None = None,
        conversation_repo_factory: Callable[
            [],
            AbstractAsyncContextManager[ConversationRepository],
        ]
        | None = None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._conversation_repo_factory = conversation_repo_factory
        self._memory_repository = memory_repository
        self._memory_extractor = memory_extractor

    async def __call__(self, job: MemoryJob) -> dict:
        """Processa um job de extração.

        Args:
            job: Job com conversation_id e project_slug.

        Returns:
            Dict com resultado da extração.
        """
        conversation_id = job.conversation_id
        if not conversation_id:
            logger.warning("extract_memory_no_conversation_id", job_id=job.id)
            return {"extracted": 0, "error": "no conversation_id"}

        try:
            conversation_uuid = UUID(conversation_id)
        except ValueError:
            logger.warning("extract_memory_invalid_conversation_id", conversation_id=conversation_id)
            return {"extracted": 0, "error": "invalid conversation_id"}

        conversation = await self._load_conversation(conversation_uuid)
        if not conversation:
            logger.warning("extract_memory_conversation_not_found", conversation_id=conversation_id)
            return {"extracted": 0, "error": "conversation not found"}

        # Skip se o agente principal já escreveu memória neste turn
        if self._agent_wrote_memory(conversation):
            logger.info("extract_memory_agent_already_wrote", conversation_id=conversation_id)
            return {"extracted": 0, "skipped": "agent_already_wrote"}

        memory_dir = await self._memory_repository.get_memory_dir(
            job.project_slug,
            scope=MemoryScope.PRIVATE,
        )

        memories = await self._memory_extractor.extract_from_conversation(
            conversation,
            memory_dir,
        )

        written: list[str] = []
        for memory in memories:
            try:
                path = await self._memory_repository.write(memory)
                written.append(str(path))
                logger.info("memory_extracted", path=str(path), name=memory.name)
            except Exception:
                logger.warning("memory_write_failed", path=str(memory.path), exc_info=True)

        # Atualiza MEMORY.md
        if written:
            await self._update_index(memory_dir)

        return {"extracted": len(written), "files": written}

    def _agent_wrote_memory(self, conversation) -> bool:
        """Verifica se o agente já escreveu memória na conversa recente.

        Heurística: verifica se houve chamadas a ferramentas de escrita
        de arquivo (write_file, edit_file) com paths no diretório de memória.
        """
        if not conversation.messages:
            return False

        # Olha as últimas 5 mensagens do assistente
        recent_assistant_msgs = [
            m for m in conversation.messages[-10:]
            if m.role.value == "assistant" and m.tool_calls
        ]

        memory_indicators = {"write_file", "edit_file", "create_memory"}
        for msg in recent_assistant_msgs:
            for tc in (msg.tool_calls or []):
                tool_name = tc.get("function", {}).get("name", "") if isinstance(tc, dict) else ""
                if tool_name in memory_indicators:
                    # Verifica se o path está em diretório de memória
                    args = tc.get("function", {}).get("arguments", "") if isinstance(tc, dict) else ""
                    if isinstance(args, str):
                        import json
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            continue
                    path = str(args.get("path", "")) if isinstance(args, dict) else ""
                    if "memory" in path.lower() or ".md" in path.lower():
                        return True
        return False

    async def _update_index(self, memory_dir: Path) -> None:
        """Atualiza o MEMORY.md com as memórias existentes."""
        headers = await self._memory_repository.scan(memory_dir)
        entries = [
            {
                "name": h.name or h.filename.replace(".md", ""),
                "description": h.description or "",
                "type": h.memory_type.value if h.memory_type else "project",
            }
            for h in headers
            if h.name  # pula arquivos sem nome
        ]
        if entries:
            await self._memory_repository.update_index(memory_dir, entries)

    async def _load_conversation(self, conversation_id: UUID):
        if self._conversation_repo_factory is not None:
            async with self._conversation_repo_factory() as repo:
                return await repo.get_by_id(conversation_id)
        if self._conversation_repo is None:
            raise RuntimeError("conversation repository is not configured")
        return await self._conversation_repo.get_by_id(conversation_id)
