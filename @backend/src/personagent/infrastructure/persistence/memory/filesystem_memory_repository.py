"""Implementação filesystem do MemoryRepository.

Armazena memórias como arquivos Markdown com frontmatter YAML.
O PostgreSQL mantém apenas metadados (não implementado aqui —
usar MemoryFileORM para queries rápidas).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_file import MemoryFile, MemoryHeader, MemoryIndex
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_scanner import MemoryScanner


class FileSystemMemoryRepository(MemoryRepository):
    """Repositório de memória baseado em filesystem.

    Estrutura de diretórios:
        ~/.personagent/
            projects/<slug>/memory/     — memória privada do projeto
            projects/<slug>/team/       — memória compartilhada (team)
            agent-memory/<agent-type>/  — memória do agente (user scope)
    """

    _INDEX_FILENAME = "MEMORY.md"
    _DEFAULT_ROOT = Path.home() / ".personagent"

    def __init__(
        self,
        root_dir: Path | None = None,
        scanner: MemoryScanner | None = None,
    ) -> None:
        self.root_dir = root_dir or self._DEFAULT_ROOT
        self.scanner = scanner or MemoryScanner()

    async def scan(
        self,
        memory_dir: Path,
        max_files: int = 200,
    ) -> list[MemoryHeader]:
        """Escaneia diretório de memória."""
        self._validate_containment(memory_dir)
        old_max = self.scanner.max_files
        self.scanner.max_files = max_files
        try:
            return self.scanner.scan_directory(memory_dir)
        finally:
            self.scanner.max_files = old_max

    async def read(
        self,
        file_path: Path,
        max_lines: int = 200,
        max_bytes: int = 25_000,
    ) -> MemoryFile | None:
        """Lê um arquivo de memória."""
        self._validate_containment(file_path)
        scope = self._infer_scope(file_path)
        return self.scanner.parse_file(file_path, max_lines, max_bytes, scope)

    async def write(
        self,
        memory_file: MemoryFile,
    ) -> Path:
        """Escreve um arquivo de memória com frontmatter."""
        self._validate_containment(memory_file.path)
        memory_file.path.parent.mkdir(parents=True, exist_ok=True)

        frontmatter_lines = ["---"]
        for key, value in memory_file.to_frontmatter_dict().items():
            # Escapa aspas duplas no valor para não quebrar o YAML
            safe_value = str(value).replace('"', '\\"')
            frontmatter_lines.append(f'{key}: "{safe_value}"')
        frontmatter_lines.append("---")

        raw = "\n".join(frontmatter_lines) + "\n\n" + memory_file.content
        memory_file.path.write_text(raw, encoding="utf-8")
        return memory_file.path

    async def delete(self, file_path: Path) -> bool:
        """Remove um arquivo de memória."""
        self._validate_containment(file_path)
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    async def read_index(self, memory_dir: Path) -> MemoryIndex | None:
        """Lê o MEMORY.md de um diretório."""
        self._validate_containment(memory_dir)
        index_path = memory_dir / self._INDEX_FILENAME
        if not index_path.exists():
            return None

        try:
            content = index_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            return MemoryIndex(
                entrypoint_path=index_path,
                content=content,
                line_count=len(lines),
                was_truncated=False,
                was_byte_truncated=False,
            )
        except (OSError, UnicodeDecodeError):
            return None

    async def update_index(
        self,
        memory_dir: Path,
        entries: list[dict[str, Any]],
        max_lines: int = 200,
        max_bytes: int = 25_000,
    ) -> Path:
        """Atualiza o MEMORY.md com a lista de entradas."""
        self._validate_containment(memory_dir)
        index_path = memory_dir / self._INDEX_FILENAME

        lines = ["# Memory Index", ""]
        for entry in entries:
            name = entry.get("name", "unknown")
            desc = entry.get("description", "")
            mtype = entry.get("type", "project")
            lines.append(f"- [{mtype}] **{name}**: {desc}")

        content = "\n".join(lines)
        if len(content.encode("utf-8")) > max_bytes:
            content = content[:max_bytes].rsplit("\n", 1)[0]
            byte_truncated = True
        else:
            byte_truncated = False

        line_list = content.split("\n")
        if len(line_list) > max_lines:
            content = "\n".join(line_list[:max_lines])
            line_truncated = True
        else:
            line_truncated = False

        memory_dir.mkdir(parents=True, exist_ok=True)
        index_path.write_text(content + "\n", encoding="utf-8")

        return index_path

    async def get_memory_dir(
        self,
        project_slug: str,
        scope: MemoryScope = MemoryScope.PRIVATE,
        agent_type: str | None = None,
    ) -> Path:
        """Retorna o diretório de memória para projeto/escopo."""
        if scope == MemoryScope.TEAM:
            return self.root_dir / "projects" / project_slug / "team"
        if scope == MemoryScope.USER_SCOPE and agent_type:
            return self.root_dir / "agent-memory" / agent_type
        if scope == MemoryScope.PROJECT:
            return self.root_dir / "projects" / project_slug / "project"
        if scope == MemoryScope.LOCAL:
            return self.root_dir / "local" / project_slug
        # PRIVATE (padrão)
        return self.root_dir / "projects" / project_slug / "memory"

    async def list_by_type(
        self,
        memory_dir: Path,
        memory_type: MemoryType,
        max_files: int = 200,
    ) -> list[MemoryHeader]:
        """Lista memórias filtradas por tipo."""
        headers = await self.scan(memory_dir, max_files)
        return [h for h in headers if h.memory_type == memory_type]

    def _validate_containment(self, target: Path) -> None:
        """Valida que o target está dentro do root_dir permitido.

        Args:
            target: Path a validar.

        Raises:
            ValueError: Se o path estiver fora do root_dir.
        """
        # Proteções explícitas contra path traversal
        target_str = str(target)
        if ".." in target_str:
            raise ValueError(f"Path traversal detected: {target}")
        if "\x00" in target_str:
            raise ValueError(f"Null byte in path: {target}")

        resolved = target.expanduser().resolve()
        root = self.root_dir.expanduser().resolve()
        if not str(resolved).startswith(str(root)):
            raise ValueError(f"Path {target} is outside memory root {root}")

    def _infer_scope(self, file_path: Path) -> MemoryScope:
        """Infere o escopo a partir da estrutura de diretórios."""
        try:
            rel = file_path.relative_to(self.root_dir)
        except ValueError:
            return MemoryScope.PRIVATE

        parts = rel.parts
        if "team" in parts:
            return MemoryScope.TEAM
        if "agent-memory" in parts:
            return MemoryScope.USER_SCOPE
        if "local" in parts:
            return MemoryScope.LOCAL
        if "project" in parts:
            return MemoryScope.PROJECT
        return MemoryScope.PRIVATE
