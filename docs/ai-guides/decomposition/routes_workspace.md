# Playbook: Decompose `routes/workspace.py`

**Target file:** `@backend/src/personagent/interfaces/api/routes/workspace.py`
(1,576 lines — 9 classes, 75 functions)

**Target package:** `@backend/src/personagent/interfaces/api/routes/workspace/`

**Tests:**
- `@backend/tests/test_conversations_api.py` (shares some workspace endpoints)

Read `_protocol.md` first.

## Why this file is hard

`workspace.py` bundles three distinct API concerns:

1. **Workspace grants** — workspace handshake, validation, trust.
2. **Filesystem operations** — file read/write/search/list endpoints.
3. **Git operations** — git status, diff, branch, commit endpoints.

Each concern has different security models and error handling patterns.

## Public contract that must be preserved

- `router` (APIRouter instance)
- All endpoint paths and HTTP methods

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers to `workspace/helpers.py` | ⏳ Pending | — | |
| 2 — Extract grant endpoints | ⏳ Pending | — | |
| 3 — Extract filesystem endpoints | ⏳ Pending | — | |
| 4 — Extract git endpoints | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract shared helpers + Pydantic models

**What moves out:** Request/response Pydantic models, workspace resolution helpers, path validation.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 2 — Extract grant endpoints to `workspace/grant.py`

**What moves out:** Workspace grant/revoke/validate endpoints.

**Risk:** Medium — security-sensitive.

**Tests:** 15+ cases — valid grant, expired grant, unauthorized.

### Slice 3 — Extract filesystem endpoints to `workspace/filesystem.py`

**What moves out:** File read/write/list/search endpoints.

**Risk:** Medium.

**Tests:** 10+ cases.

### Slice 4 — Extract git endpoints to `workspace/git.py`

**What moves out:** Git status/diff/branch/commit endpoints.

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_conversations_api.py -v
uv run pytest tests/unit/ -q
```
