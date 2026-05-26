"""Helper functions for recall retrieval."""

from __future__ import annotations

from typing import Any

from personagent.domain.memory.models.operational import (
    StructuredMemoryItem,
)
from personagent.infrastructure.persistence.operational_memory.models import (
    StoredStructuredMemoryItem,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _low_trust_memory_requested,
    _terms,
)


def _discarded_candidate_payload(
    candidates: list[StoredStructuredMemoryItem],
    selected_ids: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    discarded = []
    for candidate in candidates:
        source_ids = candidate.source_ids or [str(candidate.id)]
        if any(source_id in selected_ids for source_id in source_ids):
            continue
        discarded.append(
            {
                "id": str(candidate.id),
                "source_ids": source_ids[:3],
                "score": round(candidate.score, 4),
                "type": candidate.item_type,
                "status": candidate.status,
                "trust_level": candidate.trust_level,
                "reasons": candidate.ranking_reasons or [],
                "summary": _excerpt(candidate.summary, limit=180),
            }
        )
        if len(discarded) >= limit:
            break
    return discarded


def _included_reason_payload(items: list[StructuredMemoryItem]) -> list[dict[str, Any]]:
    return [
        {
            "source_ids": item.source_ids[:3],
            "score": item.score,
            "type": item.type.value,
            "status": item.status,
            "trust_level": item.trust_level,
            "reasons": item.metadata.get("ranking_reasons") or [],
        }
        for item in items
    ]


def _query_intent(query: str) -> str:
    terms = _terms(query)
    if _low_trust_memory_requested(terms):
        return "conversation_or_prior_interaction"
    if any("/" in token or "." in token for token in query.split()):
        return "file_or_path"
    if {"erro", "error", "falha", "failed"} & terms:
        return "error_resolution"
    if {"comando", "command", "test", "teste"} & terms:
        return "command_or_test"
    return "specific"


def _excerpt(text: str, limit: int = 420, query_terms: set[str] | None = None) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    if query_terms:
        lower = compact.lower()
        best: tuple[int, int, int] | None = None
        for term in query_terms:
            if not term:
                continue
            position = lower.find(term)
            while position >= 0:
                start = max(0, position - max(40, limit // 5))
                end = min(len(compact), start + limit)
                if end - start < limit:
                    start = max(0, end - limit)
                window = lower[start:end]
                matched_terms = sum(1 for candidate in query_terms if candidate in window)
                identifier_bonus = 1 if _has_identifier(compact[start:end]) else 0
                score = matched_terms + identifier_bonus
                candidate_window = (score, position, start)
                if best is None or candidate_window > best:
                    best = candidate_window
                position = lower.find(term, position + len(term))
        if best is not None:
            start = best[2]
            end = min(len(compact), start + limit)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(compact) else ""
            return f"{prefix}{compact[start:end]}{suffix}"
    head_size = max(120, limit // 2 - 3)
    tail_size = max(120, limit - head_size - 5)
    return f"{compact[:head_size]} ... {compact[-tail_size:]}"


def _has_identifier(text: str) -> bool:
    for token in text.replace("`", " ").split():
        stripped = token.strip(".,:;()[]{}'\"")
        if "_" in stripped and stripped.upper() == stripped and len(stripped) >= 6:
            return True
    return False
