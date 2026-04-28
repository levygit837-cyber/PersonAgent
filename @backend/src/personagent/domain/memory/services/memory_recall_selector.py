"""Serviço de seleção de memórias relevantes.

Implementa o recall inteligente do PersonAgent:
1. Scaneia o diretório de memória
2. Constrói um manifesto com nomes/descrições
3. Chama o LLM para selecionar até N memórias relevantes
4. Lê o conteúdo completo das selecionadas
5. Retorna RelevantMemory formatadas para injeção no contexto
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_file import MemoryHeader
from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_age_tracker import MemoryAgeTracker
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository


# Prompt do selector (adaptado do PersonAgent)
_SELECTOR_SYSTEM_PROMPT = (
    "You are selecting memories that will be useful to PersonAgent as it processes "
    "a user's query. You will be given the user's query and a list of available "
    "memory files with their filenames and descriptions.\n\n"
    "Return a list of filenames for the memories that will clearly be useful (up to {max}).\n"
    "Only include memories that you are certain will be helpful.\n"
    "- If unsure, do not include it. Be selective and discerning.\n"
    "- If no memories would clearly be useful, return an empty list.\n"
    "- If recently used tools are provided, do not select API docs for those tools.\n"
    "  DO select memories with warnings/gotchas about those tools.\n\n"
    'Return only compact JSON: {{"selected_memories": ["filename1.md", "filename2.md"]}}'
)


class MemoryRecallSelector:
    """Seleciona memórias relevantes para uma query do usuário."""

    def __init__(
        self,
        llm_backend: LLMBackendRepository,
        memory_repository: MemoryRepository,
        scanner: MemoryScanner | None = None,
        age_tracker: MemoryAgeTracker | None = None,
        max_recall: int = 5,
        max_tokens: int = 256,
    ) -> None:
        self._llm_backend = llm_backend
        self._memory_repository = memory_repository
        self._scanner = scanner or MemoryScanner()
        self._age_tracker = age_tracker or MemoryAgeTracker()
        self._max_recall = max_recall
        self._max_tokens = max_tokens

    async def select_relevant(
        self,
        query: str,
        memory_dir: Path,
        recent_tools: list[str] | None = None,
        already_surfaced: set[str] | None = None,
    ) -> list[RelevantMemory]:
        """Seleciona memórias relevantes para a query.

        Args:
            query: Mensagem do usuário.
            memory_dir: Diretório de memória a escanear.
            recent_tools: Ferramentas usadas recentemente (para deduplicação).
            already_surfaced: Set de paths já injetados nesta sessão.

        Returns:
            Lista de RelevantMemory selecionadas.
        """
        # 1. Scaneia diretório
        headers = await self._memory_repository.scan(memory_dir)
        if not headers:
            return []

        # 2. Filtra já surfacadas
        already = already_surfaced or set()
        headers = [h for h in headers if str(h.file_path) not in already]
        if not headers:
            return []

        # 3. Constrói manifesto
        manifest = self._scanner.build_manifest(headers)

        # 4. Chama LLM para selecionar
        selected = await self._llm_select(query, manifest, recent_tools or [])
        if not selected:
            return []

        # 5. Lê conteúdo das selecionadas
        relevant: list[RelevantMemory] = []
        for filename in selected[: self._max_recall]:
            header = self._find_header_by_name(headers, filename)
            if not header:
                continue

            memory_file = await self._memory_repository.read(header.file_path)
            if not memory_file:
                continue

            age = self._age_tracker.calculate(header.mtime_ms)
            header_str = age.human_readable()
            stale_warning = self._age_tracker.format_staleness_warning(age)

            content = memory_file.content
            if stale_warning:
                content = f"{stale_warning}\n\n{content}"

            relevant.append(
                RelevantMemory(
                    path=str(memory_file.path),
                    content=content,
                    mtime_ms=header.mtime_ms,
                    header=header_str,
                    relevance_score=0.0,
                    truncated_at_line=None,
                )
            )

        return relevant

    async def _llm_select(
        self,
        query: str,
        manifest: str,
        recent_tools: list[str],
    ) -> list[str]:
        """Chama o LLM para selecionar memórias relevantes.

        Args:
            query: Query do usuário.
            manifest: Manifesto de memórias disponíveis.
            recent_tools: Ferramentas usadas recentemente.

        Returns:
            Lista de filenames selecionados.
        """
        system_prompt = _SELECTOR_SYSTEM_PROMPT.format(max=self._max_recall)

        user_content = f"User query: {query}\n\nAvailable memories:\n{manifest}"
        if recent_tools:
            user_content += f"\n\nRecently used tools: {', '.join(recent_tools)}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            result = await self._llm_backend.chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=self._max_tokens,
                stream=False,
            )
            raw = result.content or ""
            return self._parse_selection(raw)
        except Exception:
            # Falha silenciosa — retorna vazio se o LLM não responder
            return []

    def _parse_selection(self, raw: str) -> list[str]:
        """Parseia a resposta JSON do LLM.

        Args:
            raw: Resposta bruta do LLM.

        Returns:
            Lista de filenames.
        """
        # Tenta extrair JSON
        try:
            # Procura por bloco JSON
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return data.get("selected_memories", [])
            # Tenta parsear diretamente
            data = json.loads(raw)
            return data.get("selected_memories", [])
        except (json.JSONDecodeError, AttributeError):
            # Fallback: parseia linhas que parecem filenames
            lines = [line.strip("- * ") for line in raw.split("\n") if ".md" in line]
            return lines[: self._max_recall]

    def _find_header_by_name(
        self,
        headers: list[MemoryHeader],
        filename: str,
    ) -> MemoryHeader | None:
        """Busca um header pelo filename."""
        for h in headers:
            if h.filename == filename or h.name == filename.replace(".md", ""):
                return h
        return None
