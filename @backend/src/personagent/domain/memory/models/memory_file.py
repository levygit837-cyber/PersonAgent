"""Entidades de domínio para arquivos de memória.

Um arquivo de memória é um arquivo Markdown com frontmatter YAML,
armazenado no filesystem. O conteúdo é a fonte da verdade;
o PostgreSQL mantém apenas metadados para scan rápido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType


@dataclass(frozen=True, slots=True)
class MemoryHeader:
    """Metadados de um arquivo de memória (extraídos do frontmatter)."""

    filename: str
    file_path: Path
    mtime_ms: int
    description: str | None = None
    memory_type: MemoryType | None = None
    name: str | None = None


@dataclass
class MemoryFile:
    """Arquivo de memória completo carregado do disco."""

    path: Path
    memory_type: MemoryType
    name: str
    description: str
    content: str  # corpo sem frontmatter
    raw_content: str  # conteúdo original do disco
    frontmatter: dict[str, Any] = field(default_factory=dict)
    scope: MemoryScope = MemoryScope.PRIVATE
    mtime_ms: int = 0
    is_truncated: bool = False

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """Serializa os metadados para frontmatter YAML."""
        return {
            "name": self.name,
            "description": self.description,
            "type": str(self.memory_type),
            **self.frontmatter,
        }


@dataclass
class MemoryIndex:
    """Índice MEMORY.md de um diretório de memória.

    O MEMORY.md serve como ponto de entrada para humanos e
    como fallback quando o recall LLM não está disponível.
    """

    entrypoint_path: Path
    content: str
    line_count: int
    was_truncated: bool = False
    was_byte_truncated: bool = False
