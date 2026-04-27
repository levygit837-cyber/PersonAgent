"""Tipos e escopos de memória.

Taxonomia baseada no sistema de memória do Claude Code:
- user: informações sobre o usuário
- feedback: orientações de como trabalhar
- project: contexto de projeto (bugs, deadlines, decisões)
- reference: ponteiros para sistemas externos
"""

from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    """Os 4 tipos fundamentais de memória do sistema."""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


class MemoryScope(StrEnum):
    """Escopo de persistência da memória.

    Define quem pode ver e como a memória é versionada.
    """

    PRIVATE = "private"  # Só este usuário/agente vê (padrão)
    PROJECT = "project"  # Compartilhado no repo (versionado com git)
    USER_SCOPE = "user"  # Cross-project para este usuário
    LOCAL = "local"  # Privado por máquina (não versionado)
    TEAM = "team"  # Compartilhado entre usuários do projeto
