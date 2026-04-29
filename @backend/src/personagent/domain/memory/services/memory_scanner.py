"""Service for scanning and parsing memory files.

Responsible for:
- Scanning memory directories
- Parsing YAML frontmatter from .md files
- Validating file structure
- Extracting metadata (MemoryHeader)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_file import MemoryFile, MemoryHeader
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType

# Regex for extracting YAML frontmatter between --- delimiters.
# Uses lookbehind to ensure line start and limits matches to 2000 chars.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
# Safer regex: only matches frontmatter at the start of the file.
_FRONTMATTER_RE_SAFE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

# Regex for validating snake_case names.
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FrontmatterParseError(Exception):
    """Error while parsing frontmatter from a memory file."""

    pass


class MemoryScanner:
    """Scan and parse memory files from the filesystem."""

    def __init__(self, max_files: int = 200) -> None:
        self.max_files = max_files

    def scan_directory(
        self,
        memory_dir: Path,
    ) -> list[MemoryHeader]:
        """Scan a directory and return headers for all valid .md files.

        Args:
            memory_dir: Directory to scan.

        Returns:
            List of MemoryHeader values ordered by mtime, newest first.
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
            # Skip log subdirectories; logs are append-only and are not indexed.
            # Skip log subdirectories; logs are append-only and are not indexed.
            rel_parts = file_path.relative_to(memory_dir).parts
            if len(rel_parts) > 1 and rel_parts[0] == "logs":
                continue
            header = self._parse_header_only(file_path)
            if header:
                headers.append(header)

        return headers

    def _parse_header_only(self, file_path: Path) -> MemoryHeader | None:
        """Extract only the header/frontmatter from an .md file.

        Args:
            file_path: File path.

        Returns:
            MemoryHeader or None when the file is invalid.
        """
        try:
            raw = file_path.read_text(encoding="utf-8")
            mtime_ms = int(file_path.stat().st_mtime * 1000)
        except (OSError, UnicodeDecodeError):
            return None

        match = _FRONTMATTER_RE_SAFE.match(raw)
        if not match:
            # Try the fallback regex for compatibility.
            match = _FRONTMATTER_RE.match(raw)
        if not match:
            # Files without frontmatter are invalid for this system.
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
        """Parse a complete memory file.

        Args:
            file_path: File path.
            max_lines: Maximum number of body lines.
            max_bytes: Maximum content bytes.
            scope: Memory scope.

        Returns:
            MemoryFile or None when invalid.
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
        """Parse a simple YAML block with key/value pairs only.

        Supports nested quoted values and preserves them.
        Does not support lists or nested maps.

        Args:
            yaml_text: Frontmatter YAML text.

        Returns:
            Dict with parsed values.

        Raises:
            FrontmatterParseError: If the YAML is invalid.
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
            # Remove external quotes but preserve internal quotes.
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            result[key] = value
        return result

    def _parse_memory_type(self, raw: str | None) -> MemoryType | None:
        """Convert a string to MemoryType."""
        if not raw:
            return None
        try:
            return MemoryType(raw.lower())
        except ValueError:
            return None

    def validate_name(self, name: str) -> bool:
        """Validate whether a memory name follows the snake_case pattern."""
        return bool(_SNAKE_CASE_RE.match(name))

    def build_manifest(
        self,
        headers: list[MemoryHeader],
    ) -> str:
        """Build the memory manifest for the LLM selector.

        Format: "- [type] filename (timestamp): description"

        Args:
            headers: List of memory headers.

        Returns:
            Formatted manifest string.
        """
        lines: list[str] = []
        for h in headers:
            mtype = h.memory_type.value if h.memory_type else "unknown"
            desc = h.description or "(no description)"
            age = self._format_age(h.mtime_ms)
            lines.append(f"- [{mtype}] {h.filename} ({age}): {desc}")
        return "\n".join(lines)

    def _format_age(self, mtime_ms: int) -> str:
        """Format a timestamp as relative age."""
        now = datetime.now(UTC).timestamp() * 1000
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
