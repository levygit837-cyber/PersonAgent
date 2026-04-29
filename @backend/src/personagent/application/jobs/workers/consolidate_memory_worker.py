"""Worker para consolidação automática de memórias (AutoDream).

Processa jobs do tipo AUTO_DREAM:
1. Verifica gates (time + sessions)
2. Adquire lock
3. Lista memórias existentes
4. Chama LLM para reorganizar
5. Executa ações (create/update/delete)
6. Atualiza MEMORY.md
7. Libera lock
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import structlog

from personagent.application.jobs.memory_job import MemoryJob
from personagent.domain.memory.models.memory_types import MemoryScope
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_consolidator import MemoryConsolidator

logger = structlog.get_logger(__name__)


class ConsolidateMemoryWorker:
    """Worker de consolidação de memórias."""

    def __init__(
        self,
        memory_repository: MemoryRepository,
        memory_consolidator: MemoryConsolidator,
    ) -> None:
        self._memory_repository = memory_repository
        self._memory_consolidator = memory_consolidator

    async def __call__(self, job: MemoryJob) -> dict:
        """Processa um job de consolidação.

        Args:
            job: Job com project_slug.

        Returns:
            Dict com resultado da consolidação.
        """
        project_slug = job.project_slug
        memory_dir = await self._memory_repository.get_memory_dir(
            project_slug,
            scope=MemoryScope.PRIVATE,
        )

        # Lock via flock para prevenir concorrência
        lock_path = memory_dir / ".consolidation.lock"
        lock_fd = None
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                logger.info("consolidation_lock_busy", project_slug=project_slug)
                return {"skipped": True, "reason": "lock_busy"}

            actions = await self._memory_consolidator.consolidate(memory_dir)

            executed: list[dict] = []
            for action in actions[:50]:  # limite de segurança
                try:
                    result = await self._execute_action(action, memory_dir)
                    executed.append({"action": action, "result": result})
                except Exception:
                    logger.warning(
                        "consolidation_action_failed",
                        action=action,
                        exc_info=True,
                    )

            # Atualiza MEMORY.md
            await self._update_index(memory_dir)

            return {"actions": len(actions), "executed": len(executed)}
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except OSError:
                    pass

    async def _execute_action(
        self,
        action: dict,
        memory_dir: Path,
    ) -> str:
        """Executa uma ação de consolidação.

        Args:
            action: Dict com action, path, content.
            memory_dir: Diretório base.

        Returns:
            Resultado da ação.
        """
        action_type = action.get("action", "").upper()
        raw_path = action.get("path", "").strip()

        # Sanitiza path: rejeita paths absolutos ou com traversal
        if raw_path.startswith("/") or ".." in raw_path:
            raise ValueError(f"Invalid path in consolidation action: {raw_path}")

        path = memory_dir / raw_path

        if action_type == "DELETE":
            await self._memory_repository.delete(path)
            return "deleted"

        # CREATE ou UPDATE: tenta preservar metadados existentes
        from personagent.domain.memory.models.memory_file import MemoryFile
        from personagent.domain.memory.models.memory_types import MemoryType

        existing = await self._memory_repository.read(path)
        if existing:
            # Preserva type e description do original
            memory = MemoryFile(
                path=path,
                memory_type=existing.memory_type,
                name=existing.name,
                description=existing.description,
                content=action.get("content", existing.content),
                raw_content=existing.raw_content,
                frontmatter=existing.frontmatter,
                scope=existing.scope,
            )
        else:
            memory = MemoryFile(
                path=path,
                memory_type=MemoryType.PROJECT,
                name=path.stem,
                description="Consolidated memory",
                content=action.get("content", ""),
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
        await self._memory_repository.write(memory)
        return "written"

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
            if h.name
        ]
        if entries:
            await self._memory_repository.update_index(memory_dir, entries)
