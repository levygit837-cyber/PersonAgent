"""Entidade para memórias selecionadas como relevantes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelevantMemory:
    """Memória selecionada como relevante para uma query do usuário.

    Produzida pelo MemoryRecallSelector e injetada no contexto
    da conversa como attachment ou system-reminder.
    """

    path: str
    content: str
    mtime_ms: int
    header: str  # ex: "saved 3 days ago" — pré-computado para cache
    relevance_score: float = 0.0
    truncated_at_line: int | None = None
