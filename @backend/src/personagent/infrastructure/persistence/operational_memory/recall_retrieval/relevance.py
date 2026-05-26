"""Contextual relevance logic for recall retrieval."""

from __future__ import annotations

import re
import unicodedata

from personagent.infrastructure.persistence.operational_memory.models import (
    StoredMemoryChunk,
)

from .constants import (
    _CONTEXT_ANCHOR_TERMS,
    _FOCUS_REQUIREMENTS,
    _RELEVANCE_CANONICAL_TERMS,
    _RELEVANCE_STOPWORDS,
    _WEAK_SINGLE_MATCH_TERMS,
)


def _is_contextually_relevant(query: str, candidate: StoredMemoryChunk) -> bool:
    event_type = str(candidate.event.event_type if candidate.event else candidate.chunk.source_type)
    query_terms = _relevance_terms(query)
    if not query_terms:
        return False
    if event_type in {"assistant_message", "user_message"} and not _conversation_event_requested(query_terms):
        return False

    candidate_text = " ".join(
        str(part or "")
        for part in (
            candidate.chunk.content,
            candidate.chunk.file_path,
            candidate.chunk.source_type,
            event_type,
            candidate.event.tool_name if candidate.event else "",
        )
    )
    candidate_terms = _relevance_terms(candidate_text)
    if not _focus_requirements_satisfied(query_terms, candidate_terms):
        return False
    overlap = query_terms & candidate_terms
    if len(overlap) >= 2:
        return True

    anchor_terms = query_terms & _CONTEXT_ANCHOR_TERMS
    anchor_overlap = anchor_terms & candidate_terms
    return bool(anchor_overlap - _WEAK_SINGLE_MATCH_TERMS)


def _focus_requirements_satisfied(query_terms: set[str], candidate_terms: set[str]) -> bool:
    for focus, required_terms in _FOCUS_REQUIREMENTS.items():
        if focus in query_terms and not (candidate_terms & required_terms):
            return False
    return True


def _conversation_event_requested(query_terms: set[str]) -> bool:
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


def _relevance_terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", ascii_text.lower()):
        if len(token) < 3 or token in _RELEVANCE_STOPWORDS:
            continue
        terms.add(_canonical_relevance_term(token))
    return terms


def _canonical_relevance_term(token: str) -> str:
    return _RELEVANCE_CANONICAL_TERMS.get(token, token)
