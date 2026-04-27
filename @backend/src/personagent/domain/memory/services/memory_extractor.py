"""Serviço de extração automática de memórias.

Analisa mensagens de uma conversa e extrai memórias duráveis,
seguindo as regras do Claude Code sobre o que salvar e o que não salvar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

# Prompt de extração (adaptado do Claude Code)
_EXTRACT_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Analyze the conversation below and "
    "extract durable memories that would be useful for future conversations.\n\n"
    "Rules:\n"
    "- Only extract information that is NOT derivable from the current codebase\n"
    "- Focus on user preferences, project decisions, feedback, and references\n"
    "- Do NOT extract: git history, code patterns, debugging steps, ephemeral details\n"
    "- Do NOT extract: passwords, API keys, tokens, secrets, personal identifiers\n"
    "- Format each memory as: TYPE | NAME | DESCRIPTION | CONTENT\n"
    "- Types: user, feedback, project, reference\n"
    "- Name must be snake_case, unique, without spaces or special chars\n"
    "- If no durable memories found, respond with 'NONE'\n\n"
    "Output format (one per line):\n"
    "TYPE | name | description | content"
)


class MemoryExtractor:
    """Extrai memórias duráveis de conversas."""

    def __init__(
        self,
        llm_backend: LLMBackendRepository,
        memory_repository: MemoryRepository,
    ) -> None:
        self._llm_backend = llm_backend
        self._memory_repository = memory_repository
        self._scanner = MemoryScanner()

    async def extract_from_conversation(
        self,
        conversation: Conversation,
        memory_dir: Path,
        max_turns: int = 5,
    ) -> list[MemoryFile]:
        """Extrai memórias de uma conversa.

        Args:
            conversation: Conversa a analisar.
            memory_dir: Diretório de memória para salvar.
            max_turns: Máximo de turns recentes a analisar.

        Returns:
            Lista de MemoryFile extraídas.
        """
        transcript = self._build_transcript(conversation, max_turns)
        if not transcript:
            return []

        extracted = await self._llm_extract(transcript)
        if not extracted:
            return []

        # Carrega memórias existentes para deduplicação/merge
        existing = await self._memory_repository.scan(memory_dir)
        existing_by_name: dict[str, MemoryFile] = {}
        for h in existing:
            if h.name:
                mf = await self._memory_repository.read(h.file_path)
                if mf:
                    existing_by_name[h.name] = mf

        memories: list[MemoryFile] = []
        for item in extracted:
            name = item.get("name", "").strip()
            if not name:
                logger.warning("extract_memory_empty_name_skipped")
                continue
            if not self._scanner.validate_name(name):
                logger.warning("extract_memory_invalid_name_skipped", name=name)
                continue

            if name in existing_by_name:
                # Merge: atualiza memória existente se conteúdo mudou significativamente
                merged = await self._merge_with_existing(
                    existing_by_name[name], item
                )
                if merged:
                    memories.append(merged)
                continue

            memory = MemoryFile(
                path=memory_dir / f"{name}.md",
                memory_type=item.get("type", MemoryType.PROJECT),
                name=name,
                description=item.get("description", ""),
                content=item.get("content", ""),
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            memories.append(memory)

        return memories

    async def _merge_with_existing(
        self,
        existing: MemoryFile,
        item: dict[str, Any],
    ) -> MemoryFile | None:
        """Merge uma memória extraída com uma existente.

        Se o conteúdo for significativamente diferente, retorna uma
        versão atualizada. Se for muito similar, retorna None.
        """
        new_content = item.get("content", "")
        old_content = existing.content

        # Heurística simples: se o conteúdo novo é subconjunto do velho, skip
        if new_content and new_content in old_content:
            return None

        # Se o conteúdo é muito diferente, atualiza
        # (poderia chamar LLM para merge semântico no futuro)
        merged_content = f"{old_content}\n\n# Updated\n{new_content}"
        return MemoryFile(
            path=existing.path,
            memory_type=item.get("type", existing.memory_type),
            name=existing.name,
            description=item.get("description", existing.description),
            content=merged_content,
            raw_content=existing.raw_content,
            frontmatter=existing.frontmatter,
            scope=existing.scope,
        )

    def _build_transcript(
        self,
        conversation: Conversation,
        max_turns: int,
    ) -> str:
        """Constrói o transcript das últimas N mensagens.

        Inclui todas as mensagens do final da conversa até cobrir
        aproximadamente max_turns interações user/assistant.
        """
        if not conversation.messages:
            return ""

        # Conta backwards para encontrar ~max_turns interações
        turn_count = 0
        start_idx = len(conversation.messages)
        for i in range(len(conversation.messages) - 1, -1, -1):
            msg = conversation.messages[i]
            if msg.role.value in ("user", "assistant"):
                if msg.role.value == "user":
                    turn_count += 1
                if turn_count > max_turns:
                    start_idx = i + 1
                    break
        else:
            start_idx = 0

        lines: list[str] = []
        for msg in conversation.messages[start_idx:]:
            role = msg.role.value if msg.role else "unknown"
            content = msg.content[:2000] if msg.content else ""
            if len(msg.content or "") > 2000:
                content += "\n[...truncated...]"
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    async def _llm_extract(self, transcript: str) -> list[dict[str, Any]]:
        """Chama o LLM para extrair memórias.

        Args:
            transcript: Transcript da conversa.

        Returns:
            Lista de dicts com name, type, description, content.
        """
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Conversation:\n\n{transcript}"},
        ]

        try:
            result = await self._llm_backend.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
                stream=False,
            )
            raw = result.content or ""
            if raw.strip().upper() == "NONE":
                return []
            return self._parse_extraction(raw)
        except Exception:
            logger.warning("llm_extract_failed", exc_info=True)
            return []

    def _parse_extraction(self, raw: str) -> list[dict[str, Any]]:
        """Parseia a resposta do LLM em memórias estruturadas.

        Usa parsing robusto que lida com pipes no conteúdo.
        Espera formato: TYPE | name | description | content
        onde content pode conter pipes adicionais.

        Args:
            raw: Resposta bruta do LLM.

        Returns:
            Lista de dicts parseados.
        """
        memories: list[dict[str, Any]] = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.upper() == "NONE":
                continue
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            try:
                mtype = MemoryType(parts[0].lower())
            except ValueError:
                mtype = MemoryType.PROJECT

            name = parts[1]
            description = parts[2]
            # Reconstroi o conteúdo juntando todas as partes restantes
            content = " | ".join(parts[3:])

            # Valida nome básico
            if not name or not self._scanner.validate_name(name):
                continue

            memories.append({
                "type": mtype,
                "name": name,
                "description": description,
                "content": content,
            })
        return memories
