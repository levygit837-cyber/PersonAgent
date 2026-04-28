from __future__ import annotations

from types import SimpleNamespace

from personagent.application.services.operational_memory import _should_recall_operational_memory
from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryFormatter,
    OperationalMemoryRedactor,
)
from personagent.infrastructure.persistence.operational_memory_repository import (
    OperationalMemoryRepository,
    StoredMemoryChunk,
    _excerpt,
    _is_contextually_relevant,
    _overlap_coefficient,
    _semantic_signature,
    _semantic_term_set,
)


def test_redactor_removes_known_secret_shapes() -> None:
    redactor = OperationalMemoryRedactor()

    text = "token=nvapi-secretvalue123456789 Authorization: Bearer sk-secretvalue123456789"
    redacted = redactor.redact_text(text)

    assert "nvapi-secretvalue" not in redacted
    assert "sk-secretvalue" not in redacted
    assert "[REDACTED]" in redacted


def test_redactor_masks_secret_keys_in_structured_data() -> None:
    redactor = OperationalMemoryRedactor()

    data = redactor.redact_data({"api_key": "abc123", "nested": {"password": "secret"}})

    assert data["api_key"] == "[REDACTED]"
    assert data["nested"]["password"] == "[REDACTED]"


def test_chunker_preserves_hash_and_overlap_contract() -> None:
    chunker = OperationalMemoryChunker(max_chars=40, overlap_chars=5)

    chunks = chunker.chunk_text(
        project_slug="personagent",
        source_type="diff_applied",
        source_id="event-1",
        content="line one\nline two mentions orchestrator\nline three mentions registry",
        file_path="src/agents/orchestrator.ts",
    )

    assert len(chunks) >= 2
    assert all(chunk.content_hash for chunk in chunks)
    assert chunks[0].file_path == "src/agents/orchestrator.ts"
    assert chunks[0].source_type == "diff_applied"


def test_formatter_outputs_relevant_execution_memory_section() -> None:
    formatted = OperationalMemoryFormatter.format_findings(
        [
            RecallFinding(
                finding="Na sessão anterior, o agente adicionou timeout no orchestrator.",
                source_ids=["chunk-1"],
                evidence=["diff em src/agents/orchestrator.ts"],
                paths=["src/agents/orchestrator.ts"],
                decisions=["planner delega ao executor (active)"],
                cautions=["registry já possui dispatch"],
            )
        ]
    )

    assert "# Relevant Execution Memory" in formatted
    assert "Finding 1:" in formatted
    assert "src/agents/orchestrator.ts" in formatted
    assert "Source ids: chunk-1" in formatted


def test_repository_excerpt_prefers_query_context_inside_long_chunk() -> None:
    text = (
        "session incident filler " * 120
        + "LIVE_EARLY_CANARY TenantBoundary: isolate tenant_id, project_slug, "
        "workspace_root, and conversation_id before recall injection. "
        + "tail " * 120
    )

    excerpt = _excerpt(
        text,
        query_terms={"session", "incident", "tenant", "project_slug", "conversation_id"},
    )

    assert "LIVE_EARLY_CANARY" in excerpt
    assert "conversation_id" in excerpt
    assert len(excerpt) <= 426


def test_semantic_signature_collapses_whitespace_and_number_noise() -> None:
    first = "Operational summary 123: captures diffs, tool outputs, architecture decisions."
    second = " operational-summary 999 captures diffs tool outputs architecture decisions "

    assert _semantic_signature(first) == _semantic_signature(second)


def test_recall_diversification_removes_duplicate_hashes_and_signatures() -> None:
    repository = OperationalMemoryRepository(session_factory=None)  # type: ignore[arg-type]
    duplicated_content = (
        "Operational summary captures diffs, tool outputs, architecture decisions, "
        "errors, dependency installs, and recall evidence across session 123."
    )
    candidates = [
        _stored_candidate("hash-a", duplicated_content, 0.99),
        _stored_candidate("hash-a", duplicated_content, 0.98),
        _stored_candidate("hash-b", duplicated_content.replace("123", "999"), 0.97),
        _stored_candidate("hash-c", "Decision: planner delegates tool calls to executor.", 0.95),
    ]

    selected = repository._dedupe_and_diversify(candidates, top_k=6)

    assert [candidate.chunk.content_hash for candidate in selected] == ["hash-a", "hash-c"]


def test_semantic_overlap_detects_shifted_repetitive_chunks() -> None:
    broad = _semantic_term_set(
        "LIVE_EARLY_CANARY TenantBoundary isolate tenant_id project_slug workspace_root "
        "conversation_id before recall injection. Live benchmark operational filler captures "
        "diffs tool outputs architecture decisions errors dependency installs recall evidence."
    )
    shifted = _semantic_term_set(
        "benchmark operational filler captures diffs tool outputs architecture decisions "
        "errors dependency installs recall evidence across sessions."
    )

    assert _overlap_coefficient(broad, shifted) >= 0.82


def test_operational_memory_intent_gate_skips_generic_memory_capability_query() -> None:
    assert not _should_recall_operational_memory("quais memorias você tem acesso?")
    assert not _should_recall_operational_memory("que tipos de memória existem no sistema?")


def test_operational_memory_intent_gate_allows_specific_project_queries() -> None:
    assert _should_recall_operational_memory(
        "Qual header foi escolhido para evitar duplicar incidentes em retries?"
    )
    assert _should_recall_operational_memory("Quais memórias sobre retry budget?")
    assert _should_recall_operational_memory("O que lembra sobre frontend/src/lib/api.ts?")


def test_contextual_relevance_filters_noise_and_conversation_echoes() -> None:
    query = "Qual header foi escolhido para evitar duplicar incidentes em retries?"

    assert _is_contextually_relevant(
        query,
        _stored_candidate(
            "hash-header",
            "The idempotency header is X-Request-Fingerprint for retry-safe incidents.",
            0.9,
            source_type="operational_summary",
        ),
    )
    assert not _is_contextually_relevant(
        query,
        _stored_candidate(
            "hash-command",
            "find . -name memory_rag_benchmark.py",
            0.9,
            source_type="command_executed",
        ),
    )
    assert not _is_contextually_relevant(
        query,
        _stored_candidate(
            "hash-user",
            query,
            0.9,
            source_type="user_message",
        ),
    )
    assert not _is_contextually_relevant(
        query,
        _stored_candidate(
            "hash-filler",
            "Live benchmark filler mentions incident SSE delivery and outbox lag.",
            0.9,
            source_type="operational_summary",
        ),
    )
    assert not _is_contextually_relevant(
        query,
        _stored_candidate(
            "hash-retry-budget",
            "LIVE_LATE_CANARY final caution: do not remove retry budget from the PostgreSQL outbox stream processor.",
            0.9,
            source_type="operational_summary",
        ),
    )


def test_contextual_relevance_tokenizes_file_paths() -> None:
    assert _is_contextually_relevant(
        "O que lembra sobre frontend/src/lib/api.ts?",
        _stored_candidate(
            "hash-path",
            "frontend/src/lib/api.ts must be preserved because it contains the fetch wrapper.",
            0.9,
            source_type="operational_summary",
        ),
    )


def _stored_candidate(
    content_hash: str,
    content: str,
    score: float,
    *,
    source_type: str = "operational_summary",
) -> StoredMemoryChunk:
    chunk = SimpleNamespace(
        content_hash=content_hash,
        content=content,
        file_path=None,
        source_type=source_type,
    )
    return StoredMemoryChunk(chunk=chunk, event=None, embedding=None, score=score)
