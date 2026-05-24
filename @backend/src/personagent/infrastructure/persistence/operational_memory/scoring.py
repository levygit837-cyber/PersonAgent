"""Candidate scoring, deduplication, and structured-item conversion.

Extracted from ``RecallRetrievalPipeline`` (Slice 5 — refinement).
Pure computation — no injected dependencies.
"""

from __future__ import annotations

import re
from uuid import UUID

from personagent.domain.memory.models.operational import (
    OperationalMemoryFilter,
    StructuredMemoryItem,
    StructuredMemoryType,
)
from personagent.infrastructure.persistence.operational_memory.models import (
    StoredStructuredMemoryItem,
)


class ScoringRanker:
    """Hybrid scoring, diversity dedup, and item conversion.

    Stateless — all state flows through method parameters.
    """

    def score(
        self,
        query: str,
        candidates: list[StoredStructuredMemoryItem],
        *,
        filters: OperationalMemoryFilter,
    ) -> list[StoredStructuredMemoryItem]:
        query_terms = _terms(query)
        query_text = query.lower()
        for candidate in candidates:
            text = " ".join(
                str(part or "")
                for part in (
                    candidate.summary,
                    " ".join(candidate.evidence),
                    " ".join(candidate.paths),
                    candidate.item_type,
                    candidate.source_type,
                    candidate.primary_path,
                )
            )
            lexical = _lexical_score(query_terms, text)
            exact = _exact_anchor_score(query_text, candidate)
            vector = 0.0
            if candidate.distance is not None:
                vector = max(0.0, 1.0 - float(candidate.distance))
            lexical_rank = min(1.0, max(0.0, candidate.lexical_rank) * 4.0)
            recency = 0.05 if lexical > 0 or vector > 0 or lexical_rank > 0 else 0.0
            same_conversation = (
                0.18
                if candidate.conversation_id
                and filters.current_conversation_id
                and str(candidate.conversation_id) == str(filters.current_conversation_id)
                else 0.0
            )
            trust_multiplier = _trust_multiplier(candidate.trust_level)
            raw_score = (
                (vector * 1.7)
                + lexical
                + lexical_rank
                + exact
                + _structured_type_boost(candidate.item_type)
                + same_conversation
                + recency
                + min(0.4, max(0.0, candidate.importance) * 0.2)
            )
            if candidate.trust_level == "low" and not _low_trust_memory_requested(query_terms) and exact < 0.6:
                candidate.score = 0.0
                candidate.ranking_reasons = ["discarded_low_trust_without_conversation_intent"]
                continue
            candidate.score = raw_score * trust_multiplier
            candidate.ranking_reasons = _ranking_reasons(
                vector=vector,
                lexical=lexical,
                lexical_rank=lexical_rank,
                exact=exact,
                same_conversation=same_conversation,
                trust_level=candidate.trust_level,
                item_type=candidate.item_type,
            )
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def dedupe(
        self,
        candidates: list[StoredStructuredMemoryItem],
        *,
        top_k: int,
    ) -> list[StoredStructuredMemoryItem]:
        selected: list[StoredStructuredMemoryItem] = []
        seen_ids: set[UUID] = set()
        seen_sources: set[str] = set()
        seen_signatures: set[str] = set()
        seen_term_sets: list[set[str]] = []

        for candidate in candidates:
            if candidate.score <= 0:
                continue
            if candidate.id in seen_ids:
                continue
            if any(source_id in seen_sources for source_id in candidate.source_ids):
                continue
            signature = _semantic_signature(candidate.summary)
            if signature and signature in seen_signatures:
                continue
            candidate_terms = _semantic_term_set(
                " ".join([candidate.summary, *candidate.evidence, *candidate.paths])
            )
            if any(
                _overlap_coefficient(candidate_terms, selected_terms) >= 0.88
                for selected_terms in seen_term_sets
            ):
                continue
            selected.append(candidate)
            seen_ids.add(candidate.id)
            seen_sources.update(candidate.source_ids)
            if signature:
                seen_signatures.add(signature)
            if candidate_terms:
                seen_term_sets.append(candidate_terms)
            if len(selected) >= top_k:
                break
        return selected

    def to_items(
        self,
        candidates: list[StoredStructuredMemoryItem],
    ) -> list[StructuredMemoryItem]:
        items: list[StructuredMemoryItem] = []
        for candidate in candidates:
            try:
                item_type = StructuredMemoryType(candidate.item_type)
            except ValueError:
                item_type = StructuredMemoryType.FACT
            items.append(
                StructuredMemoryItem(
                    type=item_type,
                    summary=candidate.summary,
                    evidence=candidate.evidence[:4],
                    paths=candidate.paths[:8],
                    source_ids=candidate.source_ids or [str(candidate.id)],
                    event_types=candidate.event_types,
                    score=round(candidate.score, 4),
                    status=candidate.status,
                    trust_level=candidate.trust_level,
                    importance=candidate.importance,
                    created_at=candidate.created_at,
                    metadata={
                        "project_slug": candidate.project_slug,
                        "source_type": candidate.source_type,
                        "source_chunk_id": str(candidate.source_chunk_id)
                        if candidate.source_chunk_id
                        else None,
                        "primary_path": candidate.primary_path,
                        "distance": candidate.distance,
                        "lexical_rank": candidate.lexical_rank,
                        "ranking_reasons": candidate.ranking_reasons or [],
                    },
                )
            )
        return items


# ---------------------------------------------------------------------------
# Scoring helpers (pure functions)
# ---------------------------------------------------------------------------


def _terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in text.replace("_", " ").replace("-", " ").split()
        if len(term.strip(".,:;()[]{}'\"`")) >= 3
        for term in [term.strip(".,:;()[]{}'\"`")]
    }


def _lexical_score(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    lower = text.lower()
    hits = sum(1 for term in query_terms if term in lower)
    return hits / max(1, len(query_terms))


def _exact_anchor_score(query_text: str, candidate: StoredStructuredMemoryItem) -> float:
    score = 0.0
    exact_surfaces = [
        candidate.primary_path or "",
        *candidate.paths,
        candidate.source_type,
        candidate.item_type,
    ]
    for surface in exact_surfaces:
        surface_text = str(surface).lower()
        if surface_text and surface_text in query_text:
            score += 0.7 if "/" in surface_text or "." in surface_text else 0.35
    for token in _identifier_tokens(query_text):
        haystack = " ".join(
            [
                candidate.summary,
                " ".join(candidate.evidence),
                " ".join(candidate.paths),
                candidate.primary_path or "",
            ]
        ).lower()
        if token in haystack:
            score += 0.3
    return min(1.5, score)


def _identifier_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_./:-]{2,}", text)
        if "/" in token or "." in token or "_" in token or "-" in token
    }


def _trust_multiplier(trust_level: str) -> float:
    return {
        "high": 1.0,
        "medium": 0.78,
        "low": 0.25,
    }.get(trust_level, 0.7)


def _ranking_reasons(
    *,
    vector: float,
    lexical: float,
    lexical_rank: float,
    exact: float,
    same_conversation: float,
    trust_level: str,
    item_type: str,
) -> list[str]:
    reasons = []
    if exact > 0:
        reasons.append("exact_anchor_match")
    if lexical_rank > 0:
        reasons.append("tsvector_match")
    if lexical > 0:
        reasons.append("term_overlap")
    if vector > 0:
        reasons.append("semantic_vector_match")
    if same_conversation > 0:
        reasons.append("same_conversation_boost")
    if trust_level == "low":
        reasons.append("low_trust_penalty")
    reasons.append(f"type={item_type}")
    return reasons


def _structured_type_boost(item_type: str) -> float:
    if item_type in {StructuredMemoryType.DECISION.value, StructuredMemoryType.LATEST_STATE.value}:
        return 0.55
    if item_type == StructuredMemoryType.SESSION_SUMMARY.value:
        return 0.45
    if item_type in {
        StructuredMemoryType.ERROR_SOLUTION.value,
        StructuredMemoryType.FILE_STATE.value,
        StructuredMemoryType.COMMAND_RESULT.value,
        StructuredMemoryType.TEST_RESULT.value,
        StructuredMemoryType.TOOL_TRACE.value,
    }:
        return 0.35
    return 0.2


def _event_type_boost(event_type: str) -> float:
    if event_type in {"file_read", "file_created", "file_edited", "diff_applied"}:
        return 0.6
    if event_type in {"operational_summary", "decision"}:
        return 0.5
    if event_type in {"command_executed", "error_found", "dependency_installed", "tool_result"}:
        return 0.35
    return 0.1


def _semantic_signature(text: str, limit: int = 360) -> str:
    """Normalize a chunk enough to collapse repeated synthetic filler."""

    compact = " ".join(text.lower().split())
    if not compact:
        return ""

    normalized: list[str] = []
    current_size = 0
    for raw in compact.replace("_", " ").replace("-", " ").split():
        token = raw.strip(".,:;()[]{}'\"`")
        if not token:
            continue
        if any(char.isdigit() for char in token):
            token = "<num>"
        normalized.append(token)
        current_size += len(token) + 1
        if current_size >= limit:
            break
    return " ".join(normalized)[:limit]


def _semantic_term_set(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in text.lower().replace("_", " ").replace("-", " ").split():
        token = raw.strip(".,:;()[]{}'\"`")
        if len(token) < 4:
            continue
        if any(char.isdigit() for char in token):
            token = "<num>"
        terms.add(token)
    return terms


def _overlap_coefficient(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _low_trust_memory_requested(query_terms: set[str]) -> bool:
    return bool(
        query_terms
        & {
            "assistant",
            "conversa",
            "mensagem",
            "pergunta",
            "resposta",
            "usuario",
            "user",
        }
    )
