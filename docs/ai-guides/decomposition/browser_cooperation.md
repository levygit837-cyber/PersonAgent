# Playbook: Decompose `browser_cooperation.py`

**Target file:** `@backend/src/personagent/application/services/browser_cooperation.py`
(1,292 lines — 2 classes, 61 functions)

**Target package:** `@backend/src/personagent/application/services/browser_cooperation/`

**Tests:**
- `@backend/tests/test_browser_cooperation.py`

Read `_protocol.md` first.

## Why this file is hard

`BrowserCooperationService` manages the multi-agent browser sharing protocol.
It coordinates:

1. **Event routing** — routing browser events between agents via `BrowserEventEnvelope`.
2. **Proposal lifecycle** — creating, accepting, rejecting cooperation proposals.
3. **State synchronization** — syncing browser state between cooperating agents.

## Public contract that must be preserved

Consumed by:
- `interfaces/api/routes/chat.py`
- `infrastructure/tools/browser_tools.py`

Public surface:
- `BrowserEventEnvelope` dataclass
- `BrowserCooperationService.__init__(...)`
- All public methods on the service class

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract `BrowserEventEnvelope` + event types | ⏳ Pending | — | |
| 2 — Extract proposal lifecycle | ⏳ Pending | — | |
| 3 — Extract state synchronization | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract event types to `browser_cooperation/events.py`

**What moves out (~100 lines):**

- `BrowserEventEnvelope` (80–130) and related types
- Event creation/parsing helpers

**Why first:** Pure data. No behavior logic.

**Risk:** Low.

**Tests:** 10+ cases — envelope shape, serialization.

### Slice 2 — Extract proposal lifecycle to `browser_cooperation/proposals.py`

**What moves out (~400 lines):**

- Proposal create/accept/reject methods
- Proposal validation and timeout logic

**Risk:** Medium — state mutations.

**Tests:** 15+ cases — create, accept, reject, timeout, race conditions.

### Slice 3 — Extract state sync to `browser_cooperation/sync.py`

**What moves out (~300 lines):**

- Browser state synchronization between agents
- Tab sharing coordination

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_browser_cooperation.py -v
uv run pytest tests/unit/ -q
```
