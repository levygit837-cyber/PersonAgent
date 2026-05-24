# Playbook: Decompose `session_titles.py`

**Target file:** `@backend/src/personagent/application/services/session_titles.py`
(848 lines — 4 classes, 35 functions)

**Target package:** `@backend/src/personagent/application/services/session_titles/`

**Tests:**
- `@backend/tests/test_session_titles.py`

Read `_protocol.md` first.

## Why this file is hard

`session_titles.py` mixes three concerns:

1. **Title generation** — LLM-based title generation from conversation content.
2. **Batching** — grouping multiple title requests for efficient LLM calls.
3. **Caching** — in-memory and persistent caching of generated titles.

## Public contract that must be preserved

Consumed by:
- `interfaces/api/routes/sessions.py`

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract LLM title generation | ⏳ Pending | — | |
| 2 — Extract cache logic | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract LLM title generation to `session_titles/llm_titles.py`

**What moves out (~400 lines):**

- LLM prompt construction for title generation
- Response parsing and validation
- Batch processing logic

**Risk:** Medium.

**Tests:** 15+ cases.

### Slice 2 — Extract cache to `session_titles/cache.py`

**What moves out (~200 lines):**

- In-memory title cache
- Persistent title storage
- Cache invalidation

**Risk:** Low.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_session_titles.py -v
uv run pytest tests/unit/ -q
```
