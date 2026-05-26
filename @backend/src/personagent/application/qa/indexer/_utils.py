"""Utility constants, dataclasses, and helpers for the code indexer."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass
class _ModuleInfo:
    path: Path
    rel_path: str
    tree: ast.Module
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)


def _node_id(*parts: str) -> str:
    raw = "|".join(parts)
    return f"node:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def _edge_id(source: str, target: str, kind: str, metadata: dict[str, Any]) -> str:
    raw = "|".join([source, target, kind, repr(sorted(metadata.items()))])
    return f"edge:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
