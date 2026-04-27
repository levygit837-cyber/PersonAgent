"""Serviço de scan e parse de arquivos de memória.

Responsável por:
- Escaniar diretórios de memória
- Parsear frontmatter YAML de arquivos .md
- Validar estrutura dos arquivos
- Extrair metadados (MemoryHeader)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_file import MemoryFile, MemoryHeader
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType


# Regex para extrair frontmatter YAML entre --- delimiters
# Usa lookbehind para garantir que é início de linha, e limita a 2000 chars
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
# Regex mais seguro: só matcha frontmatter no início do arquivo
_FRONTMATTER_RE_SAFE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

# Regex para validar nome snake_case
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FrontmatterParseError(Exception):
    """Erro ao parsear frontmatter de um arquivo de memória."""

    pass


class MemoryScanner:
    """Escaneia e parseia arquivos de memória no filesystem."""

    def __init__(self, max_files: int = 200) -> None:
        self.max_files = max_files

    def scan_directory(
        self,
        memory_dir: Path,
    ) -> list[MemoryHeader]:
        """Escaneia um diretório e retorna headers de todos os .md válidos.

        Args:
            memory_dir: Diretório a escanear.

        Returns:
            Lista de MemoryHeader ordenada por mtime (mais recente primeiro).
        """
        if not memory_dir.exists():
            return []

        headers: list[MemoryHeader] = []
        md_files = sorted(
            memory_dir.rglob("*.md"),
            key=lambda p: p.stat().st_mtime_ns,
            reverse=True,
        )

        for file_path in md_files[: self.max_files]:
            # Pula subdiretórios de logs (logs são append-only, não entram no índice)
            # Pula subdiretórios de logs (logs são append-only, não entram no índice)
            rel_parts = file_path.relative_to(memory_dir).parts
            if len(rel_parts) > 1 and rel_parts[0] == "logs":
                continue
            header = self._parse_header_only(file_path)
            if header:
                headers.append(header)

        return headers

    def _parse_header_only(self, file_path: Path) -> MemoryHeader | None:
        """Extrai apenas o header (frontmatter) de um arquivo .md.

        Args:
            file_path: Path do arquivo.

        Returns:
            MemoryHeader ou None se o arquivo for inválido.
        """
        try:
            raw = file_path.read_text(encoding="utf-8")
            mtime_ms = int(file_path.stat().st_mtime * 1000)
        except (OSError, UnicodeDecodeError):
            return None

        match = _FRONTMATTER_RE_SAFE.match(raw)
        if not match:
            # Tenta regex fallback para compatibilidade
            match = _FRONTMATTER_RE.match(raw)
        if not match:
            # Arquivo sem frontmatter — trata como inválido para o sistema
            return None

        try:
            frontmatter = self._parse_yaml(match.group(1))
        except FrontmatterParseError:
            return None

        return MemoryHeader(
            filename=file_path.name,
            file_path=file_path,
            mtime_ms=mtime_ms,
            description=frontmatter.get("description"),
            memory_type=self._parse_memory_type(frontmatter.get("type")),
            name=frontmatter.get("name"),
        )

    def parse_file(
        self,
        file_path: Path,
        max_lines: int = 200,
        max_bytes: int = 25_000,
        scope: MemoryScope = MemoryScope.PRIVATE,
    ) -> MemoryFile | None:
        """Parseia um arquivo de memória completo.

        Args:
            file_path: Path do arquivo.
            max_lines: Máximo de linhas do corpo.
            max_bytes: Máximo de bytes do conteúdo.
            scope: Escopo da memória.

        Returns:
            MemoryFile ou None se inválido.
        """
        try:
            raw = file_path.read_text(encoding="utf-8")
            mtime_ms = int(file_path.stat().st_mtime * 1000)
        except (OSError, UnicodeDecodeError):
            return None

        if len(raw.encode("utf-8")) > max_bytes:
            raw = raw[:max_bytes].rsplit("\n", 1)[0]
            is_truncated = True
        else:
            is_truncated = False

        match = _FRONTMATTER_RE_SAFE.match(raw)
        if not match:
            match = _FRONTMATTER_RE.match(raw)
        if not match:
            return None

        try:
            frontmatter = self._parse_yaml(match.group(1))
        except FrontmatterParseError:
            return None

        name = frontmatter.get("name", file_path.stem)
        description = frontmatter.get("description", "")
        memory_type = self._parse_memory_type(frontmatter.get("type"))
        if memory_type is None:
            memory_type = MemoryType.PROJECT  # fallback

        body = match.group(2).strip()
        lines = body.split("\n")
        if len(lines) > max_lines:
            body = "\n".join(lines[:max_lines])
            is_truncated = True

        return MemoryFile(
            path=file_path,
            memory_type=memory_type,
            name=name,
            description=description,
            content=body,
            raw_content=raw,
            frontmatter=frontmatter,
            scope=scope,
            mtime_ms=mtime_ms,
            is_truncated=is_truncated,
        )

    def _parse_yaml(self, yaml_text: str) -> dict[str, Any]:
        """Parseia um bloco YAML simples (apenas pares chave: valor).

        Suporta valores com aspas aninhadas preservando-as.
        Não suporta listas ou nested maps.

        Args:
            yaml_text: Texto YAML do frontmatter.

        Returns:
            Dict com os valores parseados.

        Raises:
            FrontmatterParseError: Se o YAML for inválido.
        """
        result: dict[str, Any] = {}
        for line in yaml_text.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            # Remove aspas externas mas preserva internas
            if len(value) >= 2:
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
            result[key] = value
        return result

    def _parse_memory_type(self, raw: str | None) -> MemoryType | None:
        """Converte string para MemoryType."""
        if not raw:
            return None
        try:
            return MemoryType(raw.lower())
        except ValueError:
            return None

    def validate_name(self, name: str) -> bool:
        """Valida se um nome de memória segue o padrão snake_case."""
        return bool(_SNAKE_CASE_RE.match(name))

    def build_manifest(
        self,
        headers: list[MemoryHeader],
    ) -> str:
        """Constroi o manifesto de memórias para o LLM selector.

        Formato: "- [type] filename (timestamp): description"

        Args:
            headers: Lista de headers de memória.

        Returns:
            String formatada com o manifesto.
        """
        lines: list[str] = []
        for h in headers:
            mtype = h.memory_type.value if h.memory_type else "unknown"
            desc = h.description or "(sem descrição)"
            age = self._format_age(h.mtime_ms)
            lines.append(f"- [{mtype}] {h.filename} ({age}): {desc}")
        return "\n".join(lines)

    def _format_age(self, mtime_ms: int) -> str:
        """Formata o timestamp como idade relativa."""
        now = datetime.now(timezone.utc).timestamp() * 1000
        diff_ms = now - mtime_ms
        diff_hours = diff_ms / (1000 * 3600)
        if diff_hours < 1:
            return "just now"
        if diff_hours < 24:
            return f"{int(diff_hours)}h ago"
        diff_days = diff_hours / 24
        if diff_days < 30:
            return f"{int(diff_days)}d ago"
        diff_months = diff_days / 30
        return f"{int(diff_months)}mo ago"
