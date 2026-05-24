# Playbook: Decompose `filesystem_tools.py`

**Target file:** `@backend/src/personagent/infrastructure/tools/filesystem_tools.py`
(810 lines — 0 classes, 32 functions)

**Target package:** `@backend/src/personagent/infrastructure/tools/filesystem_tools/`

**Tests:**
- `@backend/tests/test_tools_runtime.py`

Read `_protocol.md` first.

## Why this file is hard

`filesystem_tools.py` is a factory module with 32 functions that creates
filesystem tool definitions. It mixes:

1. **Read tools** — file read, directory list, grep/search.
2. **Write tools** — file write, edit, create, delete.
3. **Shared helpers** — path validation, security checks, permission guards.

## Public contract that must be preserved

- `create_filesystem_tools(...)` — the only public entry point.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers + security | ⏳ Pending | — | |
| 2 — Extract read tools | ⏳ Pending | — | |
| 3 — Extract write tools | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract helpers to `filesystem_tools/helpers.py`

**What moves out (~200 lines):**

- Path validation and sanitization
- Security checks (workspace bounds)
- Permission guards
- Shared constants

**Risk:** Low.

**Tests:** 15+ cases — path validation, security boundaries.

### Slice 2 — Extract read tools to `filesystem_tools/read_tools.py`

**What moves out (~300 lines):**

- File read, directory list, grep/search tool factories.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Extract write tools to `filesystem_tools/write_tools.py`

**What moves out (~250 lines):**

- File write, edit, create, delete tool factories.

**Risk:** Medium — write operations are security-sensitive.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_tools_runtime.py -v
uv run pytest tests/unit/ -q
```
