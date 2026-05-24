"""SQL-building and row-conversion helpers for operational memory search.

Extracted from ``recall_retrieval.py`` (Slice 6 — refinement).
Pure functions — no class, no injected dependencies.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from personagent.domain.memory.models.operational import (
    OperationalMemoryFilter,
    StructuredMemoryType,
)
from personagent.infrastructure.persistence.operational_memory.models import (
    StoredMemoryChunk,
    StoredStructuredMemoryItem,
)


def _uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _lexical_query_text(query: str) -> str:
    terms = []
    for token in re.findall(r"[A-Za-z0-9_./:-]+", query):
        normalized = token.strip(".,:;()[]{}'\"`")
        if len(normalized) >= 2:
            terms.append(normalized.replace("/", " ").replace(".", " "))
    return " ".join(terms)[:1_000]


def _normalize_file_path_filter(file_path: str) -> str:
    return str(file_path or "").replace("\\", "/").removeprefix("./").rstrip("/")


def _file_path_filter_variants(file_path: str, workspace_root: str | None) -> list[str]:
    variants = [file_path]
    workspace = _normalize_file_path_filter(workspace_root or "")
    if workspace and file_path.startswith(f"{workspace}/"):
        variants.append(file_path[len(workspace) + 1 :])
    return list(dict.fromkeys(path for path in variants if path))


def _file_path_suffix_patterns(file_path: str) -> list[str]:
    if not file_path or file_path.startswith("/"):
        return []
    return [f"%/{file_path}"]


def _structured_where_clause(
    alias: str,
    filters: OperationalMemoryFilter,
    params: dict[str, Any],
) -> str:
    clauses: list[str] = []
    if not filters.include_raw_chunks:
        clauses.append(f"{alias}.item_type <> 'raw_chunk'")
    if filters.statuses:
        placeholders = []
        for index, status in enumerate(filters.statuses):
            key = f"status_{index}"
            params[key] = status
            placeholders.append(f":{key}")
        clauses.append(f"{alias}.status IN ({', '.join(placeholders)})")
    elif filters.active_only:
        clauses.append(f"{alias}.status = 'active'")
    if filters.latest_only:
        clauses.append(f"{alias}.is_latest = true")
    conversation_id = _uuid_or_none(filters.conversation_id)
    if conversation_id is not None:
        params["conversation_id"] = conversation_id
        clauses.append(f"{alias}.conversation_id = :conversation_id")
    if filters.session_id:
        params["session_id"] = filters.session_id
        clauses.append(f"{alias}.session_id = :session_id")
    if filters.workspace_root:
        params["workspace_root"] = filters.workspace_root
        clauses.append(f"{alias}.workspace_root = :workspace_root")
    if filters.source_types:
        placeholders = []
        for index, source_type in enumerate(filters.source_types):
            key = f"source_type_{index}"
            params[key] = source_type
            placeholders.append(f":{key}")
        joined = ", ".join(placeholders)
        clauses.append(f"({alias}.source_type IN ({joined}) OR {alias}.item_type IN ({joined}))")
    if filters.file_paths:
        exact_placeholders = []
        variant_placeholders = []
        suffix_clauses: list[str] = []
        path_suffix_clauses: list[str] = []
        for index, file_path in enumerate(filters.file_paths):
            key = f"file_path_{index}"
            normalized_path = _normalize_file_path_filter(file_path)
            params[key] = normalized_path
            exact_placeholders.append(f":{key}")
            for variant_index, variant in enumerate(
                variant
                for variant in _file_path_filter_variants(normalized_path, filters.workspace_root)
                if variant != normalized_path
            ):
                variant_key = f"file_path_{index}_variant_{variant_index}"
                params[variant_key] = variant
                variant_placeholders.append(f":{variant_key}")
            for suffix_index, suffix in enumerate(_file_path_suffix_patterns(normalized_path)):
                suffix_key = f"file_path_{index}_suffix_{suffix_index}"
                params[suffix_key] = suffix
                suffix_clauses.append(f"{alias}.primary_path LIKE :{suffix_key}")
                path_suffix_clauses.append(f"memory_path.path LIKE :{suffix_key}")
        exact_joined = ", ".join(exact_placeholders)
        all_placeholders = [*exact_placeholders, *variant_placeholders]
        all_joined = ", ".join(all_placeholders)
        path_match_clauses = [
            f"{alias}.primary_path IN ({exact_joined})",
            f"EXISTS (SELECT 1 FROM jsonb_array_elements_text({alias}.paths) AS memory_path(path) "
            f"WHERE memory_path.path IN ({all_joined})"
            + (f" OR {' OR '.join(path_suffix_clauses)}" if path_suffix_clauses else "")
            + ")",
        ]
        if variant_placeholders:
            path_match_clauses.append(f"{alias}.primary_path IN ({', '.join(variant_placeholders)})")
        path_match_clauses.extend(suffix_clauses)
        clauses.append("(" + " OR ".join(path_match_clauses) + ")")
    if filters.created_after:
        params["created_after"] = filters.created_after
        clauses.append(f"{alias}.created_at >= :created_after")
    if filters.created_before:
        params["created_before"] = filters.created_before
        clauses.append(f"{alias}.created_at <= :created_before")
    if not clauses:
        return ""
    return "AND " + "\n                      AND ".join(clauses)


def _rows_to_structured_candidates(rows: list[Any]) -> list[StoredStructuredMemoryItem]:
    candidates: list[StoredStructuredMemoryItem] = []
    for row in rows:
        evidence = row[4] if isinstance(row[4], list) else []
        paths = row[5] if isinstance(row[5], list) else []
        source_ids = row[6] if isinstance(row[6], list) else []
        source_type = str(row[8] or row[2] or "")
        candidates.append(
            StoredStructuredMemoryItem(
                id=row[0],
                project_slug=str(row[1] or ""),
                item_type=str(row[2] or StructuredMemoryType.FACT.value),
                summary=str(row[3] or ""),
                evidence=[str(item) for item in evidence if str(item).strip()],
                paths=[str(item) for item in paths if str(item).strip()],
                source_ids=[str(item) for item in source_ids if str(item).strip()],
                event_types=[source_type] if source_type else [],
                status=str(row[7] or "active"),
                source_type=source_type,
                source_chunk_id=row[9],
                primary_path=row[10],
                conversation_id=row[11],
                workspace_root=str(row[12]) if row[12] else None,
                trust_level=str(row[13] or "medium"),
                importance=float(row[14] or 0.5),
                created_at=row[15],
                distance=float(row[16]) if row[16] is not None else None,
                lexical_rank=float(row[17] or 0.0),
            )
        )
    return candidates


def _embedding_to_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        return [float(item) for item in to_list()]
    to_numpy = getattr(value, "to_numpy", None)
    if callable(to_numpy):
        return [float(item) for item in to_numpy().tolist()]
    try:
        return [float(item) for item in value]
    except TypeError:
        return None


def _rows_to_candidates(rows: list[Any]) -> list[StoredMemoryChunk]:
    return [
        StoredMemoryChunk(chunk=row[0], event=row[1], embedding=_embedding_to_list(row[2]))
        for row in rows
    ]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8g}" for value in values) + "]"
