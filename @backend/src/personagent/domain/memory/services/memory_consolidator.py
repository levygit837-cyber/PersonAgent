"""Serviço de consolidação automática de memórias (AutoDream).

Periodicamente revisa memórias existentes e as reorganiza:
- Merge de duplicatas
- Update de informações outdated
- Remove memórias obsoletas
- Reorganiza em tópicos semânticos
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from personagent.domain.memory.models.memory_file import MemoryFile, MemoryHeader
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

# Prompt de consolidação
_CONSOLIDATE_SYSTEM_PROMPT = (
    "You are a memory consolidation assistant. Review the current memory files "
    "and produce an improved, organized memory system.\n\n"
    "Goals:\n"
    "1. Merge duplicate memories (same topic, same guidance)\n"
    "2. Update outdated memories with newer information\n"
    "3. Remove memories that are no longer relevant or have been contradicted\n"
    "4. Reorganize into clear topic-based files\n"
    "5. Keep MEMORY.md as a concise index (max 200 lines)\n\n"
    "Return only compact JSON:\n"
    '{"actions":[{"action":"CREATE|UPDATE|DELETE","path":"relative/file.md","content":"full content or empty for delete"}]}\n'
    'If no changes are needed, return {"actions":[]}.'
)


class MemoryConsolidator:
    """Consolida memórias de sessões passadas."""

    def __init__(
        self,
        llm_backend: LLMBackendRepository,
        memory_repository: MemoryRepository,
    ) -> None:
        self._llm_backend = llm_backend
        self._memory_repository = memory_repository

    async def consolidate(
        self,
        memory_dir: Path,
    ) -> list[dict[str, Any]]:
        """Consolida memórias em um diretório.

        Args:
            memory_dir: Diretório de memória a consolidar.

        Returns:
            Lista de ações executadas (create, update, delete).
        """
        headers = await self._memory_repository.scan(memory_dir)
        if len(headers) < 2:
            return []

        # Lê conteúdo das memórias existentes — prioriza as MAIS ANTIGAS
        # (elas são as que mais precisam de consolidação)
        headers_oldest_first = list(reversed(headers))
        memories: list[tuple[MemoryHeader, MemoryFile]] = []
        for header in headers_oldest_first[:20]:  # limite para não exceder contexto
            mf = await self._memory_repository.read(header.file_path)
            if mf:
                memories.append((header, mf))

        if not memories:
            return []

        # Prepara contexto para o LLM
        context = self._build_consolidation_context(memories)

        # Chama LLM
        actions = await self._llm_consolidate(context)
        return actions

    def _build_consolidation_context(
        self,
        memories: list[tuple[MemoryHeader, MemoryFile]],
    ) -> str:
        """Constrói o contexto de consolidação para o LLM."""
        lines: list[str] = ["# Current Memory Files", ""]
        for header, mf in memories:
            age_days = self._age_days(header.mtime_ms)
            lines.append(f"## {mf.path.name}")
            lines.append(f"Type: {mf.memory_type.value}")
            lines.append(f"Age: {age_days} days")
            lines.append(f"Description: {mf.description}")
            # Indica truncamento se o conteúdo foi cortado
            content_preview = mf.content[:1000]
            if len(mf.content) > 1000:
                content_preview += "\n[...truncated at 1000 chars...]"
            lines.append(f"Content:\n{content_preview}")
            lines.append("")
        return "\n".join(lines)

    def _age_days(self, mtime_ms: int) -> int:
        """Calcula idade em dias."""
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        return max(0, (now_ms - mtime_ms) // (1000 * 86400))

    async def _llm_consolidate(self, context: str) -> list[dict[str, Any]]:
        """Chama o LLM para consolidar memórias."""
        messages = [
            {"role": "system", "content": _CONSOLIDATE_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        try:
            result = await self._llm_backend.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                stream=False,
            )
            raw = result.content or ""
            if raw.strip().upper() == "NONE":
                return []
            return self._parse_actions(raw)
        except Exception:
            logger.warning("llm_consolidate_failed", exc_info=True)
            return []

    def _parse_actions(self, raw: str) -> list[dict[str, Any]]:
        """Parseia ações de consolidação."""
        parsed_json = self._parse_actions_json(raw)
        if parsed_json is not None:
            return parsed_json

        actions: list[dict[str, Any]] = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.upper() == "NONE":
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                actions.append({
                    "action": parts[0].upper(),
                    "path": parts[1],
                    "content": " | ".join(parts[2:]),
                })
        return actions

    def _parse_actions_json(self, raw: str) -> list[dict[str, Any]] | None:
        text = raw.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        items = payload.get("actions") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return None
        actions: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").upper().strip()
            path = str(item.get("path") or "").strip()
            if action not in {"CREATE", "UPDATE", "DELETE"} or not path:
                continue
            actions.append(
                {
                    "action": action,
                    "path": path,
                    "content": str(item.get("content") or ""),
                }
            )
        return actions
