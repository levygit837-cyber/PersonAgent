# Playbook: Decompose `routes/chat.py`

**Target file:** `@backend/src/personagent/interfaces/api/routes/chat.py`
(1,905 lines — 8 classes, 53 functions)

**Target package:** `@backend/src/personagent/interfaces/api/routes/chat/`

**Tests:**
- `@backend/tests/test_conversations_api.py`
- `@backend/tests/test_chat_models_api.py`

Read `_protocol.md` first.

## Why this file is hard

`chat.py` is a single route module that handles the entire chat API surface:

1. **Chat completion** — sync and streaming endpoints (889–1111).
2. **Plan approval** — approve/continue/cancel plan flow (1115–1233).
3. **Tool approval** — approve/reject tool calls (1237–1390).
4. **Team chat** — WebSocket endpoint + persistence (1484–1905).
5. **Model listing** — list_models, list_commands, prompt_preview (712–885).
6. **Shared helpers** — use case factory, resolve_* functions (282–563).

## Public contract that must be preserved

The FastAPI `router` is imported by the application wiring. All
endpoint paths and HTTP methods must remain identical.

Public surface:
- `router` (APIRouter instance)
- All endpoint functions decorated with `@router.get/post/websocket`

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers to `chat/helpers.py` | ⏳ Pending | — | |
| 2 — Extract model listing endpoints | ⏳ Pending | — | |
| 3 — Extract plan approval endpoints | ⏳ Pending | — | |
| 4 — Extract tool approval endpoints | ⏳ Pending | — | |
| 5 — Extract team chat endpoints | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract helpers to `chat/helpers.py`

**What moves out (~280 lines):**

- `resolve_reasoning_budget` (254–268)
- `resolve_model` (282–296)
- `resolve_default_output_tokens` (314–328)
- `resolve_tool_context` (342–360)
- `_update_plan_approval_artifact` (421–441)
- `_resume_request_from_tool_approval` (477–524)
- `_create_chat_use_case` (527–563)
- `_approve_pending_tool_call` (566–650)
- `_answer_pending_user_question` (653–698)
- Pydantic request/response models (classes at module level)

**Why first:** Pure functions and factory helpers. No endpoints.

**Risk:** Low.

**Tests:** 15+ cases.

### Slice 2 — Extract model listing to `chat/models_listing.py`

**What moves out (~180 lines):**

- `list_models` (712–731)
- `codex_auth_logout` (746–761)
- `list_chat_commands` (765–822)
- `prompt_preview` (826–885)

**Risk:** Low — read-only endpoints.

**Tests:** 10+ cases.

### Slice 3 — Extract plan approval to `chat/plan_approval.py`

**What moves out (~120 lines):**

- `approve_plan` (1115–1160)
- `continue_plan` (1164–1200)
- `cancel_plan` (1204–1233)

**Risk:** Medium — state mutations.

**Tests:** 10+ cases.

### Slice 4 — Extract tool approval to `chat/tool_approval.py`

**What moves out (~200 lines):**

- `approve_tool` (1237–1260)
- `approve_tool_stream` (1264–1351)
- `reject_tool` (1355–1390)
- `answer_user_question_stream` (1394–1480)

**Risk:** Medium.

**Tests:** 10+ cases.

### Slice 5 — Extract team chat to `chat/team_chat.py`

**What moves out (~420 lines):**

- `team_chat_websocket` (1484–1688) — the WebSocket handler
- `persist_team_run_started` (1732–1760)
- `persist_team_blackboard_event` (1763–1789)
- `load_team_memory_snapshot` (1792–1810)
- `persist_team_memory_snapshot` (1813–1838)
- `persist_team_run` (1841–1884)
- `_team_trace_event_for_storage` (1887–1905)

**Risk:** Medium-high — WebSocket handling with streaming.

**Tests:** 15+ cases.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_conversations_api.py tests/test_chat_models_api.py -v
uv run pytest tests/unit/ -q
```
