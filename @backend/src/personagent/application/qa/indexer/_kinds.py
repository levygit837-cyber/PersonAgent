"""Node kind classification helpers for the code indexer."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from personagent.application.qa.contracts import CodeNodeKind


def _function_kind(rel_path: str, name: str, *, has_route: bool) -> CodeNodeKind:
    normalized = rel_path.replace("\\", "/")
    if has_route or "/interfaces/api/routes/" in f"/{normalized}":
        return CodeNodeKind.CONTROLLER
    if "middleware" in normalized:
        return CodeNodeKind.MIDDLEWARE
    if "repository" in normalized or "repositories" in normalized or "persistence" in normalized:
        return CodeNodeKind.REPOSITORY
    if "service" in normalized or "services" in normalized or "use_cases" in normalized:
        return CodeNodeKind.SERVICE
    if normalized.endswith(".py") and Path(normalized).name.startswith("test_"):
        return CodeNodeKind.TEST
    if name.startswith("test_"):
        return CodeNodeKind.TEST
    return CodeNodeKind.FUNCTION


def _class_kind(rel_path: str, bases: Iterable[str]) -> CodeNodeKind:
    normalized = rel_path.replace("\\", "/")
    base_set = set(bases)
    if "BaseModel" in base_set:
        return CodeNodeKind.SCHEMA
    if "BaseSettings" in base_set or normalized.endswith("settings.py"):
        return CodeNodeKind.CONFIG
    if normalized.endswith("models.py") or "/domain/models/" in f"/{normalized}":
        return CodeNodeKind.MODEL
    if "repository" in normalized or "repositories" in normalized or "persistence" in normalized:
        return CodeNodeKind.REPOSITORY
    if "service" in normalized or "services" in normalized:
        return CodeNodeKind.SERVICE
    return CodeNodeKind.FUNCTION
