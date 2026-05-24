# Playbook: Decompose `operational_memory_repository.py`

**Target file:** `@backend/src/personagent/infrastructure/persistence/operational_memory_repository.py`
(1,938 lines)

**Target package:** `@backend/src/personagent/infrastructure/persistence/operational_memory/`

**Tests:**
- `@backend/tests/integration/memory/test_memory_e2e_flow.py`
- `@backend/tests/integration/memory/test_memory_workers.py`

Read `_protocol.md` first.

## Why this file is hard

`OperationalMemoryRepository` (181–1227, 32 methods) is a single class
that handles four distinct persistence concerns:

1. **Chunk storage** — CRUD for memory chunks (insert, update, delete, list).
2. **Vector search** — embedding-based similarity search via pgvector + HNSW index.
3. **Structured items** — CRUD for structured memory items (preferences, facts).
4. **Chunking logic** — splitting and merging text into appropriately-sized chunks.

The file also contains SQLAlchemy model definitions (`StoredMemoryChunk`,
`StoredStructuredMemoryItem`) that should live in a dedicated models file.

## Public contract that must be preserved

Consumed by:
- `application/services/operational_memory.py`
- `application/jobs/workers/consolidate_memory_worker.py`
- Integration tests

Public surface:
- `OperationalMemoryRepository.__init__(...)`
- All 32 public methods on the repository class.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract models to `models.py` | ⏳ Pending | — | |
| 2 — Extract chunking logic | ⏳ Pending | — | |
| 3 — Extract vector search | ⏳ Pending | — | |
| 4 — Extract structured items | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract SQLAlchemy models to `operational_memory/models.py`

**What moves out:**

- `StoredMemoryChunk` dataclass (46–52)
- `StoredStructuredMemoryItem` dataclass (56–79)
- Related constants and type aliases

**Why first:** Pure data definitions. No behavior. Lowest risk.

**Risk:** Low.

**Tests:** 5 cases — shape validation, default values.

### Slice 2 — Extract chunking logic to `operational_memory/chunking.py`

**What moves out:**

- Methods related to text splitting, chunk merging, overlap calculation
- `_split_text_into_chunks`, `_merge_small_chunks`, related helpers

**Risk:** Medium — chunking affects what gets stored and searched.

**Tests:** 15+ cases — split boundaries, overlap, edge cases (empty, huge).

### Slice 3 — Extract vector search to `operational_memory/vector_search.py`

**What moves out:**

- Methods related to embedding generation, pgvector queries, HNSW index usage
- `search_similar`, `_build_search_query`, related helpers

**Risk:** Medium-high — vector search is the core retrieval path.

**Tests:** 15+ cases — query building, scoring, filtering, empty results.

### Slice 4 — Extract structured items to `operational_memory/structured_items.py`

**What moves out:**

- CRUD methods for structured memory items
- `store_structured_item`, `get_structured_items`, `delete_structured_item`

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/integration/memory/ -v
uv run pytest tests/unit/ -q
```
