# ADR 0012: Three-Layer Memory (Session + Operational RAG + Filesystem)

Date: 2025-06-10
Status: Accepted

## Context

Long-running conversations need context that exceeds the LLM window. We need a memory architecture that spans the current session, historical project knowledge, and persistent user-defined notes.

## Decision

Organize memory into three layers:

**Layer 1: Session Memory** (`application/services/session_memory.py`)
- Filesystem-backed (`~/.cache/personagent/sessions/{conversation_id}.md`).
- Stores the current session summary, scratchpad, and temporary notes.
- Injected into the prompt via `PromptBuilder` when present.

**Layer 2: Operational Memory (RAG)** (`application/services/operational_memory.py`)
- PostgreSQL + pgvector + embeddings for semantic retrieval.
- Pipeline: extract (from conversation) -> chunk -> embed -> index -> recall.
- `MemoryJobScheduler` runs extraction (`EXTRACT_MEMORIES`) and consolidation (`AUTO_DREAM`) via APScheduler.
- `OpenAICompatibleEmbeddingAdapter` talks to a local embedding server (llama.cpp with `--embedding`).
- `MemoryRecallSelector` ranks candidates by semantic similarity + recency + token budget.

**Layer 3: Filesystem Memory** (`domain/context/services/` + `infrastructure/persistence/memory/filesystem_memory_repository.py`)
- `persona.md`, `.personagent/rules`, git context, and explicit context attachments.
- Loaded by `BuildContextUseCase` and injected into the system prompt.

## Consequences

- **Easier**: session memory is instant; operational memory scales with project size; filesystem memory is version-controlled.
- **Harder**: RAG quality depends on chunking and embedding model quality; operational memory jobs can race with active chat turns.
- **Risk**: embedding server startup failures silently disable recall; memory hallucinations can pollute the prompt.
- **Out of scope**: cross-project memory federation; user-level global memory graph.

## Alternatives Considered

- **Single vector store for everything**: rejected because session-specific notes need fast, synchronous access without a DB round-trip.
- **No structured memory, just context compaction**: rejected because it loses durable project knowledge across sessions.

## Validation

- `@backend/tests/integration/test_memory.py` validates extraction, embedding, and recall end-to-end.
- Memory jobs run daily at 3 AM when `auto_dream_enabled=True`.
