# Playbook: Decompose `routes/sessions.py`

**Target file:** `@backend/src/personagent/interfaces/api/routes/sessions.py`
(1,471 lines — 12 models, 27 endpoints, 22 helpers)

**Target package:** `@backend/src/personagent/interfaces/api/routes/sessions/`

**Tests:**
- `@backend/tests/test_conversations_api.py`
- `@backend/tests/test_session_panel.py`

Read `_protocol.md` first.

## Why this file is hard

`sessions.py` handles four distinct API concerns:

1. **Browser Viewport (standalone)** — 8 endpoints that interact directly with
   the LightPanda browser worker without conversation context.
2. **Browser Workspace (conversation-scoped)** — 15 HTTP endpoints + 1 WebSocket
   that load a conversation, interact with the browser, record timeline events,
   and persist workspace state.
3. **Session Panel + Titles** — panel snapshot, project details, title
   verification/deduplication.
4. **Pydantic Models** — 12 request/response schemas interleaved with routes.

The standalone and conversation-scoped browser routes are **interleaved**
(lines 153-175 standalone, 177-321 conversation, 324-484 standalone,
486-985 conversation), making extraction non-trivial.

## Public contract that must be preserved

- `router` (APIRouter instance, prefix="/sessions")
- All endpoint paths, HTTP methods, query params, and status codes
- `DB_SESSION_DEPENDENCY` (re-exported for external consumers)

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract Pydantic models + helpers | ⏳ Pending | — | |
| 2 — Extract browser viewport routes | ⏳ Pending | — | standalone, no conversation |
| 3 — Extract browser workspace routes | ⏳ Pending | — | conversation-scoped, biggest chunk |
| 4 — Extract panel + title routes | ⏳ Pending | — | |
| 5 — Extract shared helpers | ⏳ Pending | — | _coerce_*, _now_iso, etc. |

## Proposed slices (in order)

### Slice 1 — Extract Pydantic models to `sessions/models.py`

**What moves out:** All 12 Pydantic request/response classes:
`SessionTitleVerifyRequest`, `SessionBrowserViewport`,
`SessionBrowserNavigateRequest`, `SessionBrowserHistoryRequest`,
`SessionBrowserPointerRequest`, `SessionBrowserKeyboardRequest`,
`SessionBrowserScrollRequest`, `SessionBrowserActionRequest`,
`SessionBrowserAnnotationRequest`, `SessionBrowserCooperationRequest`,
`SessionBrowserEventInput`, `SessionBrowserEventBatchRequest`.

**Risk:** Low. Pure data classes, no behavior.

**Tests:** 5+ cases — model instantiation and field validation.

### Slice 2 — Extract browser viewport routes to `sessions/browser_viewport.py`

**What moves out:** 8 endpoints that interact with `_browser_worker()` without
conversation context: `get_session_browser_view`, `navigate_session_browser`,
`move_session_browser_history`, `reload_session_browser`,
`click_session_browser`, `key_session_browser`, `scroll_session_browser`,
`act_session_browser`.

**Shared collaborator:** `_browser_worker()` (LightPanda).

**Risk:** Low-Medium. Thin wrappers, no persistence.

**Tests:** 10+ cases — one per endpoint, error paths.

### Slice 3 — Extract browser workspace routes to `sessions/browser_workspace.py`

**What moves out:** 15 HTTP endpoints + 1 WebSocket for conversation-scoped
browser interaction: cooperation, events, WebSocket, view, navigate, history,
reload, click, key, scroll, action, annotations CRUD, timeline clear, mentions.

**Shared collaborators:** `BrowserWorkspaceService`, `BrowserCooperationService`,
`_load_conversation`, `_save_conversation`.

**Risk:** Medium-High. Largest surface, interleaved with viewport routes.

**Tests:** 15+ cases.

### Slice 4 — Extract panel + title routes to `sessions/panel.py`

**What moves out:** `verify_session_titles`, `dedupe_session_titles`,
`get_session_panel`, `get_session_project_detail`.

**Shared collaborators:** `SessionPanelService`, `SessionTitleService`.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 5 — Extract shared helpers to `sessions/_helpers.py`

**What moves out:** `_coerce_dict`, `_coerce_list`, `_safe_event_source`,
`_now_iso`, `_browser_worker`, `_load_conversation`, `_save_conversation`,
and other private functions shared across modules.

**Risk:** Low. Pure refactor of private functions.

**Tests:** Already covered by route tests.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_conversations_api.py tests/test_session_panel.py -v
uv run pytest tests/unit/ -q
```
