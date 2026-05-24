# Playbook: Decompose `persistence/models.py`

**Target file:** `@backend/src/personagent/infrastructure/persistence/models.py`
(919 lines — 31 ORM classes for the entire system)

**Target package:** `@backend/src/personagent/infrastructure/persistence/models/`
(new directory; `__init__.py` re-exports all ORM classes for backward
compatibility)

**Tests:**
- `@backend/tests/test_alembic_setup.py`
- All integration tests that create DB records

Read `_protocol.md` first.

## Why this file is hard

`models.py` is the single-file ORM registry for the entire backend.
It contains 31 SQLAlchemy ORM classes spanning 6 unrelated domains:

1. **Core** (3 classes, ~60L): `TenantORM`, `ConversationORM`,
   `MessageORM` — fundamental entities.
2. **Browser** (7 classes, ~200L): `BrowserWorkspaceORM`,
   `BrowserTabORM`, `BrowserAnnotationORM`,
   `BrowserTimelineEventORM`, `BrowserCooperationEventORM`,
   `BrowserAutomationRunORM`, `BrowserAutomationStepORM`.
3. **Team mode** (3 classes, ~90L): `TeamRunORM`,
   `TeamBlackboardEventORM`, `TeamMemorySnapshotORM`.
4. **QA** (6 classes, ~210L): `QASessionORM`, `QACodeNodeORM`,
   `QACodeEdgeORM`, `QARequestRunORM`, `QARuntimeEventORM`,
   `QAArtifactORM`.
5. **Memory** (11 classes, ~320L): `MemoryFileORM`, `MemoryJobORM`,
   `MemorySessionORM`, `MemoryConsolidationLockORM`,
   `OperationalMemoryEventORM`, `OperationalMemoryChunkORM`,
   `MemoryEmbeddingORM`, `StructuredMemoryItemORM`,
   `MemoryDecisionORM`, `MemoryRecallLogORM`, `MemoryOutboxORM`.
6. **Tasks** (1 class, ~30L): `TaskRecordORM`.

The problems:
1. **Every domain imports from the same file** — changing any model
   forces every consumer to re-read 919 lines of context.
2. **No domain boundaries** — browser models sit next to memory models
   sit next to QA models with no organizational structure.
3. **Growing risk** — every new feature that needs persistence adds
   another class to this file.

## Public contract that must be preserved

Consumed by (direct imports):
- `interfaces/api/routes/chat.py` — uses conversation/message ORMs
- `infrastructure/persistence/postgres_conversation_repository.py`
- `infrastructure/persistence/operational_memory_repository.py`
- `infrastructure/persistence/task_store.py`
- `application/services/browser_workspace.py`
- `application/services/browser_cooperation.py`
- `application/qa/service.py`

All 31 ORM class names must remain importable from
`personagent.infrastructure.persistence.models` after extraction
(via `__init__.py` re-exports).

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract browser ORM models | ⏳ Pending | — | |
| 2 — Extract team mode ORM models | ⏳ Pending | — | |
| 3 — Extract QA ORM models | ⏳ Pending | — | |
| 4 — Extract memory ORM models | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract browser ORM models to `models/browser.py`

**What moves out (~200 lines):**

- `BrowserWorkspaceORM` (97–150)
- `BrowserTabORM` (150–179)
- `BrowserAnnotationORM` (179–214)
- `BrowserTimelineEventORM` (214–244)
- `BrowserCooperationEventORM` (244–301)
- `BrowserAutomationRunORM` (301–335)
- `BrowserAutomationStepORM` (335–366)

**Shared imports that move:** `Base`, `Column`, `DateTime`, `Float`,
`ForeignKey`, `Index`, `Integer`, `String`, `Text`, `func`,
`UUID`, `JSONB`, `relationship`.

**Why first:** Browser models form a self-contained cluster with
foreign keys only to `conversations` and `tenants` (core). No
cross-references to memory, QA, or team models.

**Risk:** Low. ORM models are declarative — moving them doesn't
change behavior. The only risk is Alembic auto-generation seeing
phantom schema changes; verify with
`uv run alembic check` after the move.

**Tests:** 5+ cases — import verification, table name assertions,
relationship integrity.

### Slice 2 — Extract team mode ORM models to `models/team.py`

**What moves out (~90 lines):**

- `TeamRunORM` (366–389)
- `TeamBlackboardEventORM` (389–410)
- `TeamMemorySnapshotORM` (410–423)

**Why now:** Small, self-contained cluster. References `conversations`
table only.

**Risk:** Low.

**Tests:** 5 cases.

### Slice 3 — Extract QA ORM models to `models/qa.py`

**What moves out (~210 lines):**

- `QASessionORM` (441–466)
- `QACodeNodeORM` (466–489)
- `QACodeEdgeORM` (489–511)
- `QARequestRunORM` (511–536)
- `QARuntimeEventORM` (536–567)
- `QAArtifactORM` (567–585)

**Why now:** QA models form a self-contained subgraph with foreign
keys within the group plus a reference to `conversations`.

**Risk:** Low.

**Tests:** 5 cases.

### Slice 4 — Extract memory ORM models to `models/memory.py`

**What moves out (~320 lines):**

- `MemoryFileORM` (585–617)
- `MemoryJobORM` (617–635)
- `MemorySessionORM` (635–649)
- `MemoryConsolidationLockORM` (649–660)
- `OperationalMemoryEventORM` (660–701)
- `OperationalMemoryChunkORM` (701–745)
- `MemoryEmbeddingORM` (745–774) — conditionally defined with pgvector
- `StructuredMemoryItemORM` (774–825)
- `MemoryDecisionORM` (825–857)
- `MemoryRecallLogORM` (857–891)
- `MemoryOutboxORM` (891–919)

**Why last:** Largest group. `MemoryEmbeddingORM` has a conditional
import (`pgvector`) that requires careful handling.

**Risk:** Medium — the `pgvector` conditional import and the `Vector`
column type need to be preserved exactly.

**Tests:** 10+ cases — including pgvector conditional import behavior.

After all slices, `models/__init__.py` re-exports everything:
```python
from personagent.infrastructure.persistence.models.core import *
from personagent.infrastructure.persistence.models.browser import *
from personagent.infrastructure.persistence.models.team import *
from personagent.infrastructure.persistence.models.qa import *
from personagent.infrastructure.persistence.models.memory import *
```

The remaining `core.py` contains: `TenantORM`, `ConversationORM`,
`MessageORM`, `TaskRecordORM` (~100 lines).

## Anti-patterns specific to this file

- **Do not break Alembic.** After each slice, verify that
  `uv run alembic check` shows no unexpected migrations. SQLAlchemy
  discovers models via `Base.metadata` — all models must be imported
  by the time Alembic runs.
- **Preserve the `Vector` conditional import.** The `try/except
  ImportError` pattern for pgvector must be replicated in the memory
  models file.
- **Do not change table names or column names.** This is a database
  schema — any rename would require a migration.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run python -c "from personagent.infrastructure.persistence.models import *; print('imports OK')"
uv run alembic check 2>&1 || echo "alembic check completed"
uv run pytest tests/test_alembic_setup.py -v
uv run pytest tests/unit/ -q --no-header \
             --deselect tests/unit/test_prompt_builder.py::TestPromptBuilder::test_agent_state_overlays_are_compact
```
