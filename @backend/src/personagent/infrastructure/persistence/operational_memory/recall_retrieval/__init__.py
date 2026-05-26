"""Hybrid recall, scoring, and ranking pipeline for operational memory.

Extracted from ``OperationalMemoryRepository`` (Slice 4).
Owns the read path: semantic/lexical/recent search, hybrid scoring,
deduplication, and structured-item/chunk-to-finding conversion.
"""

from __future__ import annotations

from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _lexical_query_text as _lexical_query_text,
)
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _rows_to_structured_candidates as _rows_to_structured_candidates,
)
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _structured_where_clause as _structured_where_clause,
)
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _uuid_or_none as _uuid_or_none,
)
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _vector_literal as _vector_literal,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    ScoringRanker as ScoringRanker,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _event_type_boost as _event_type_boost,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _lexical_score as _lexical_score,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _low_trust_memory_requested as _low_trust_memory_requested,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _overlap_coefficient as _overlap_coefficient,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _semantic_signature as _semantic_signature,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _semantic_term_set as _semantic_term_set,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _terms as _terms,
)

from .chunk_recall import (
    _ann_candidate_chunk_ids as _ann_candidate_chunk_ids,
)
from .chunk_recall import (
    _dedupe_and_diversify as _dedupe_and_diversify,
)
from .chunk_recall import (
    _score_candidates as _score_candidates,
)
from .chunk_recall import (
    _to_findings as _to_findings,
)
from .helpers import (
    _discarded_candidate_payload as _discarded_candidate_payload,
)
from .helpers import (
    _excerpt as _excerpt,
)
from .helpers import (
    _has_identifier as _has_identifier,
)
from .helpers import (
    _included_reason_payload as _included_reason_payload,
)
from .helpers import (
    _query_intent as _query_intent,
)
from .pipeline import RecallRetrievalPipeline as RecallRetrievalPipeline
from .relevance import (
    _canonical_relevance_term as _canonical_relevance_term,
)
from .relevance import (
    _conversation_event_requested as _conversation_event_requested,
)
from .relevance import (
    _focus_requirements_satisfied as _focus_requirements_satisfied,
)
from .relevance import (
    _is_contextually_relevant as _is_contextually_relevant,
)
from .relevance import (
    _relevance_terms as _relevance_terms,
)

__all__ = [
    "RecallRetrievalPipeline",
    "ScoringRanker",
    "_ann_candidate_chunk_ids",
    "_canonical_relevance_term",
    "_conversation_event_requested",
    "_dedupe_and_diversify",
    "_discarded_candidate_payload",
    "_event_type_boost",
    "_excerpt",
    "_focus_requirements_satisfied",
    "_has_identifier",
    "_included_reason_payload",
    "_is_contextually_relevant",
    "_lexical_query_text",
    "_lexical_score",
    "_low_trust_memory_requested",
    "_overlap_coefficient",
    "_query_intent",
    "_relevance_terms",
    "_rows_to_structured_candidates",
    "_score_candidates",
    "_semantic_signature",
    "_semantic_term_set",
    "_structured_where_clause",
    "_terms",
    "_to_findings",
    "_uuid_or_none",
    "_vector_literal",
]
