# Playbook: Decompose `operational_memory.py` (Service)

**Target file:** `@backend/src/personagent/application/services/operational_memory.py`
(1,075 lines — 1 class, 28 methods)

**Target package:** `@backend/src/personagent/application/services/operational_memory/`

**Tests:**
- `@backend/tests/unit/test_chat_operational_memory.py`
- `@backend/tests/unit/test_chat_memory_recall.py`
- `@backend/tests/integration/memory/`

Read `_protocol.md` first.

## Why this file is hard

`OperationalMemoryService` (163–871, 28 methods) handles three
distinct memory concerns in one class:

1. **Context extraction** — extracting salient context from conversation
   turns for short-term memory.
2. **Recall** — retrieving relevant memories for a new conversation turn
   using vector similarity and recency.
3. **Capture/persist** — writing extracted memories to the repository,
   scheduling background consolidation jobs.

## Public contract that must be preserved

Consumed by:
- `application/use_cases/chat/memory/` (memory recall coordinator)
- `application/use_cases/chat/bookkeeping/` (after-turn coordinator)
- `application/jobs/` (background workers)

Public surface:
- `OperationalMemoryService.__init__(...)`
- All 28 public methods

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract extraction logic | ⏳ Pending | — | |
| 2 — Extract recall logic | ⏳ Pending | — | |
| 3 — Extract capture/persist logic | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract context extraction to `operational_memory/extraction.py`

**What moves out (~350 lines):**

- Methods related to extracting context from conversation turns
- LLM-based extraction pipeline
- Extraction formatting and filtering

**Risk:** Medium — involves LLM calls.

**Tests:** 15+ cases — extraction with/without LLM, filtering, empty input.

### Slice 2 — Extract recall to `operational_memory/recall.py`

**What moves out (~300 lines):**

- Memory recall and ranking methods
- Relevance scoring and merge logic
- Recency weighting

**Risk:** Medium — recall quality is critical.

**Tests:** 15+ cases — relevance ranking, empty results, recency weighting.

### Slice 3 — Extract capture to `operational_memory/capture.py`

**What moves out (~200 lines):**

- Write/persist methods
- Background job scheduling
- Consolidation triggers

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/unit/test_chat_operational_memory.py tests/unit/test_chat_memory_recall.py -v
uv run pytest tests/integration/memory/ -v
uv run pytest tests/unit/ -q
```
