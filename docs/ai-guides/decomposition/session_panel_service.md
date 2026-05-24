# Playbook: Decompose `session_panel.py` (Service)

**Target file:** `@backend/src/personagent/application/services/session_panel.py`
(976 lines — 2 classes, 24 methods)

**Target package:** `@backend/src/personagent/application/services/session_panel/`

**Tests:**
- `@backend/tests/test_session_panel.py`

Read `_protocol.md` first.

## Why this file is hard

`SessionPanelService` (22–694, 24 methods) aggregates data from
multiple sources for the session panel UI:

1. **Browser tab aggregation** — collecting and formatting tab data
   from browser workers and opened pages cache.
2. **Usage/stats** — computing token usage, context window estimates,
   and session metadata.
3. **Panel data assembly** — combining browser tabs, memory traces,
   recent usage, and file lists into the panel response.

## Public contract that must be preserved

Consumed by:
- `interfaces/api/routes/sessions.py`

Public surface:
- `SessionPanelService.__init__(...)`
- All public methods

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract browser tab aggregation | ⏳ Pending | — | |
| 2 — Extract usage/stats helpers | ⏳ Pending | — | |
| 3 — Flatten remaining | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract browser tab aggregation to `session_panel/browser_tabs.py`

**What moves out (~300 lines):**

- Methods that collect and format browser tab data
- Tab deduplication and sorting logic
- Panel tab data structures

**Risk:** Medium.

**Tests:** 15+ cases.

### Slice 2 — Extract usage helpers to `session_panel/usage.py`

**What moves out (~200 lines):**

- Token usage computation
- Context window estimation
- Session metadata helpers

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Flatten remaining into `session_panel/service.py`

**What remains:** Core panel data assembly logic.

**Risk:** Low.

**Tests:** 5+ integration cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_session_panel.py -v
uv run pytest tests/unit/ -q
```
