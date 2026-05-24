# Playbook: Decompose `routes/sessions.py`

**Target file:** `@backend/src/personagent/interfaces/api/routes/sessions.py`
(1,471 lines — 12 classes, 50 functions)

**Target package:** `@backend/src/personagent/interfaces/api/routes/sessions/`

**Tests:**
- `@backend/tests/test_conversations_api.py`
- `@backend/tests/test_session_panel.py`

Read `_protocol.md` first.

## Why this file is hard

`sessions.py` handles four distinct API concerns:

1. **Session CRUD** — list/create/get/update/delete conversations.
2. **Memory endpoints** — memory recall, preference files, operational memory.
3. **Panel data** — session panel metadata, browser tabs, usage stats.
4. **Export/import** — conversation export and import.

The file also contains 12 Pydantic model definitions that clutter the
route logic.

## Public contract that must be preserved

- `router` (APIRouter instance)
- All endpoint paths and HTTP methods

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract Pydantic models + helpers | ⏳ Pending | — | |
| 2 — Extract CRUD endpoints | ⏳ Pending | — | |
| 3 — Extract memory endpoints | ⏳ Pending | — | |
| 4 — Extract panel + export endpoints | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract Pydantic models + helpers to `sessions/models.py`

**What moves out:** All 12 Pydantic request/response classes, shared helpers.

**Risk:** Low.

**Tests:** 5+ cases — model shape validation.

### Slice 2 — Extract CRUD endpoints to `sessions/crud.py`

**What moves out:** list/create/get/update/delete session endpoints.

**Risk:** Medium.

**Tests:** 10+ cases.

### Slice 3 — Extract memory endpoints to `sessions/memory.py`

**What moves out:** Memory recall, preference file endpoints.

**Risk:** Medium.

**Tests:** 10+ cases.

### Slice 4 — Extract panel + export to `sessions/panel.py`

**What moves out:** Panel data, export/import endpoints.

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_conversations_api.py tests/test_session_panel.py -v
uv run pytest tests/unit/ -q
```
