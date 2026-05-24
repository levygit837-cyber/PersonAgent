# God Files — Master Decomposition Plan

> Single source of truth for **every** god file in PersonAgent.
> Read `_protocol.md` first. This document extends it with the
> full inventory, final target structure, and cross-cutting rules.

## Inventory

### God file criteria

A file qualifies as a god file if it meets **all three**:

1. Over **800 lines** (1,500+ is severe).
2. Mixes **more than one responsibility**.
3. **Hot path** — called from multiple places, multiple collaborators.

### Backend god files

| # | File | Lines | Status | Playbook |
|---|------|------:|--------|----------|
| 1 | `infrastructure/browser/lightpanda.py` | 4,710 | 🔄 Slices 1–4 merged (PRs #37–#40), slices 5–8 pending | `lightpanda.md` |
| 2 | `infrastructure/tools/browser_tools.py` | 2,786 | ⏳ Not started | `browser_tools.md` |
| 3 | `infrastructure/persistence/operational_memory_repository.py` | 1,938 | ⏳ Not started | `operational_memory_repository.md` |
| 4 | `interfaces/api/routes/chat.py` | 1,905 | ⏳ Not started | `routes_chat.md` |
| 5 | `interfaces/api/routes/workspace.py` | 1,576 | ⏳ Not started | `routes_workspace.md` |
| 6 | `interfaces/api/routes/sessions.py` | 1,471 | ⏳ Not started | `routes_sessions.md` |
| 7 | `application/services/browser_cooperation.py` | 1,292 | ⏳ Not started | `browser_cooperation.md` |
| 8 | `application/services/operational_memory.py` | 1,075 | ⏳ Not started | `operational_memory_service.md` |
| 9 | `infrastructure/llm/vertex_ai_adapter.py` | 1,064 | ⏳ Not started | `llm_adapters.md` |
| 10 | `application/services/session_panel.py` | 976 | ⏳ Not started | `session_panel_service.md` |
| 11 | `infrastructure/llm/codex_subscription_adapter.py` | 944 | ⏳ Not started | `llm_adapters.md` |
| 12 | `infrastructure/llm/kimi_coding_adapter.py` | 892 | ⏳ Not started | `llm_adapters.md` |
| 13 | `application/services/session_titles.py` | 848 | ⏳ Not started | `session_titles.md` |
| 14 | `infrastructure/tools/filesystem_tools.py` | 810 | ⏳ Not started | `filesystem_tools.md` |

### Already decomposed (backend)

| File | Lines | Status |
|------|------:|--------|
| `application/use_cases/chat_completion.py` | 483 | ✅ Done (was 2,742, −82%) |
| `application/team_chat/orchestrator.py` | 127 | ✅ Done (was 3,097, −96%) |

### Frontend god files

| # | File | Lines | Status | Playbook |
|---|------|------:|--------|----------|
| 15 | `components/chat/session-panel.tsx` | 3,960 | ⏳ Not started | `session_panel.md` |
| 16 | `stores/chat-store.ts` | 3,307 | ⏳ Not started | `chat_store.md` |
| 17 | `components/chat/input-dock.tsx` | 1,976 | ⏳ Not started | `input_dock.md` |
| 18 | `components/chat/agent-message.tsx` | 1,419 | ⏳ Not started | `agent_message.md` |
| 19 | `components/open-pr/open-pr-workspace.tsx` | 1,350 | ⏳ Not started | `open_pr_workspace.md` |
| 20 | `components/chat/session-panel/browser-mirror.ts` | 1,261 | ⏳ Not started | `browser_mirror.md` |
| 21 | `api/client.ts` | 1,231 | ⏳ Not started | `api_client.md` |
| 22 | `components/chat/file-viewer-panel.tsx` | 1,079 | ⏳ Not started | `file_viewer_panel.md` |

---

## Decomposition Priority

### Tier 1 — Critical (>2,000L or blocking other work)

1. **`lightpanda.py`** — 4,710L, in progress (slices 5–8 remain)
2. **`browser_tools.py`** — 2,786L, tightly coupled with lightpanda
3. **`session-panel.tsx`** — 3,960L, largest frontend file
4. **`chat-store.ts`** — 3,307L, frontend state monolith

### Tier 2 — High (1,500–2,000L)

5. **`operational_memory_repository.py`** — 1,938L
6. **`routes/chat.py`** — 1,905L
7. **`input-dock.tsx`** — 1,976L
8. **`routes/workspace.py`** — 1,576L
9. **`routes/sessions.py`** — 1,471L

### Tier 3 — Medium (800–1,500L)

10. **`browser_cooperation.py`** — 1,292L
11. **`operational_memory.py`** — 1,075L
12. **`vertex_ai_adapter.py`** — 1,064L
13. **`session_panel.py`** (service) — 976L
14. **`codex_subscription_adapter.py`** — 944L
15. **`kimi_coding_adapter.py`** — 892L
16. **`agent-message.tsx`** — 1,419L
17. **`open-pr-workspace.tsx`** — 1,350L
18. **`browser-mirror.ts`** — 1,261L
19. **`api/client.ts`** — 1,231L
20. **`file-viewer-panel.tsx`** — 1,079L
21. **`session_titles.py`** — 848L
22. **`filesystem_tools.py`** — 810L

---

## Target Structure (ASCII Tree)

After all decompositions are complete, the project structure will be:

```
@backend/src/personagent/
├── domain/
│   ├── conversation/
│   │   ├── models.py
│   │   └── repositories.py
│   ├── memory/
│   │   ├── models/
│   │   ├── repositories.py
│   │   └── services/
│   ├── context/
│   ├── prompts/
│   │   ├── context_attachments.py
│   │   └── services/
│   │       └── prompt_builder.py
│   ├── tools/
│   ├── tenancy/
│   ├── llm_backend/
│   └── exceptions.py
│
├── application/
│   ├── use_cases/
│   │   ├── chat/                          # ✅ DONE (483L, was 2,742)
│   │   │   ├── orchestrator.py
│   │   │   ├── state.py
│   │   │   ├── helpers.py
│   │   │   ├── prompt/
│   │   │   ├── tools/
│   │   │   ├── streaming/
│   │   │   ├── bookkeeping/
│   │   │   └── memory/
│   │   ├── team_chat/                     # ✅ DONE (127L, was 3,097)
│   │   │   ├── orchestrator.py
│   │   │   ├── types.py
│   │   │   ├── blackboard.py
│   │   │   ├── agent_turn_runner.py
│   │   │   ├── consensus_phase.py
│   │   │   ├── coordinator_phase.py
│   │   │   ├── final_synthesis.py
│   │   │   ├── helpers.py
│   │   │   └── phase_loop.py
│   │   ├── context/
│   │   └── memory/
│   ├── services/
│   │   ├── browser_cooperation/           # ← from browser_cooperation.py (1,292L)
│   │   │   ├── service.py                 #   core cooperation logic
│   │   │   ├── events.py                  #   BrowserEventEnvelope + event routing
│   │   │   └── proposals.py              #   proposal lifecycle
│   │   ├── operational_memory/            # ← from operational_memory.py (1,075L)
│   │   │   ├── service.py                 #   extraction/capture orchestration
│   │   │   ├── extraction.py              #   context extraction logic
│   │   │   └── recall.py                 #   recall + merge logic
│   │   ├── session_panel/                 # ← from session_panel.py (976L)
│   │   │   ├── service.py                 #   main panel data
│   │   │   ├── browser_tabs.py            #   browser tab aggregation
│   │   │   └── usage.py                  #   usage/stats helpers
│   │   ├── session_titles/                # ← from session_titles.py (848L)
│   │   │   ├── service.py                 #   title generation orchestration
│   │   │   ├── llm_titles.py             #   LLM-based title generation
│   │   │   └── cache.py                  #   title caching
│   │   ├── browser_workspace.py
│   │   └── security.py
│   ├── tools/
│   ├── jobs/
│   ├── state/
│   ├── qa/
│   ├── dto/
│   └── contracts.py
│
├── infrastructure/
│   ├── browser/                           # ← from lightpanda.py (4,710L)
│   │   ├── lightpanda.py                  #   coordinator (~1,500L target after all slices)
│   │   ├── cdp_client.py                  #   ✅ Slice 1 — CDP transport
│   │   ├── cache.py                       #   ✅ Slice 2 — snapshot + stylesheet caches
│   │   ├── actions.py                     #   ✅ Slice 3 — click/type/scroll/screenshot/script/wait
│   │   ├── page_lifecycle.py              #   ✅ Slice 4 — open/close/switch/reload/history/list_tabs
│   │   ├── snapshot.py                    #   Slice 5 — DOM → structured view pipeline
│   │   ├── search.py                      #   Slice 6 — search URL building + result extraction
│   │   ├── view_actions.py                #   Slice 7 — view_* API (agent interaction layer)
│   │   ├── models.py
│   │   ├── url_utils.py
│   │   └── content_cleanup.py
│   ├── tools/
│   │   ├── browser_tools/                 # ← from browser_tools.py (2,786L)
│   │   │   ├── __init__.py                #   re-exports create_browser_tools
│   │   │   ├── factory.py                 #   create_browser_tools registry
│   │   │   ├── navigation.py              #   search/open/extract/get_html tools
│   │   │   ├── interaction.py             #   click/type/scroll/screenshot/script tools
│   │   │   ├── tab_management.py          #   list_tabs/close_tab/switch_tab/reload/history tools
│   │   │   ├── content.py                 #   extract_content/read_chunk/element_map tools
│   │   │   └── helpers.py                 #   shared response prep, normalization, permission
│   │   ├── filesystem_tools/              # ← from filesystem_tools.py (810L)
│   │   │   ├── __init__.py
│   │   │   ├── factory.py                 #   create_filesystem_tools registry
│   │   │   ├── read_tools.py              #   read/list/search/grep tools
│   │   │   ├── write_tools.py             #   write/edit/create tools
│   │   │   └── helpers.py                 #   path validation, security checks
│   │   ├── shell_tool.py
│   │   └── mcp_tools.py
│   ├── persistence/
│   │   ├── operational_memory/            # ← from operational_memory_repository.py (1,938L)
│   │   │   ├── repository.py              #   main repository class
│   │   │   ├── chunking.py                #   chunk splitting/merging logic
│   │   │   ├── vector_search.py           #   embedding + pgvector queries
│   │   │   ├── structured_items.py        #   structured memory CRUD
│   │   │   └── models.py                  #   SQLAlchemy models (StoredMemoryChunk, etc.)
│   │   ├── models.py
│   │   └── ...
│   ├── llm/
│   │   ├── vertex_ai/                     # ← from vertex_ai_adapter.py (1,064L)
│   │   │   ├── adapter.py                 #   VertexAiAdapter main class
│   │   │   ├── streaming.py               #   stream response handling
│   │   │   ├── content_builder.py         #   request content formatting
│   │   │   └── models.py                  #   VertexModelSpec, config types
│   │   ├── codex/                          # ← from codex_subscription_adapter.py (944L)
│   │   │   ├── adapter.py                 #   CodexSubscriptionAdapter
│   │   │   ├── auth.py                    #   CodexAuthStore + CodexAuthSnapshot
│   │   │   ├── streaming.py               #   SSE event parsing
│   │   │   └── models.py                  #   _SseEvent, auth types
│   │   ├── kimi/                           # ← from kimi_coding_adapter.py (892L)
│   │   │   ├── adapter.py                 #   KimiCodingAdapter
│   │   │   ├── streaming.py               #   Anthropic-style stream parsing
│   │   │   └── content_builder.py         #   request formatting
│   │   ├── nvidia_nim_adapter.py
│   │   └── ...
│   ├── settings/
│   └── ...
│
├── interfaces/api/routes/
│   ├── chat/                              # ← from routes/chat.py (1,905L)
│   │   ├── __init__.py                    #   re-exports router
│   │   ├── completion.py                  #   chat_completion + chat_completion_stream
│   │   ├── plan_approval.py               #   approve/continue/cancel plan
│   │   ├── tool_approval.py               #   approve/reject tool
│   │   ├── team_chat.py                   #   team_chat_websocket + persistence endpoints
│   │   ├── models_listing.py              #   list_models, list_commands, prompt_preview
│   │   └── helpers.py                     #   _create_chat_use_case, resolve_* helpers
│   ├── workspace/                         # ← from routes/workspace.py (1,576L)
│   │   ├── __init__.py
│   │   ├── grant.py                       #   workspace grant endpoints
│   │   ├── filesystem.py                  #   file read/write/search endpoints
│   │   ├── git.py                         #   git operations endpoints
│   │   └── helpers.py                     #   shared workspace resolution
│   ├── sessions/                          # ← from routes/sessions.py (1,471L)
│   │   ├── __init__.py
│   │   ├── crud.py                        #   list/create/get/delete sessions
│   │   ├── memory.py                      #   memory-related session endpoints
│   │   ├── panel.py                       #   session panel data endpoints
│   │   └── export.py                      #   export/import endpoints
│   └── ...
│
@desktop-electron/src/
├── components/
│   ├── chat/
│   │   ├── session-panel/                 # ← from session-panel.tsx (3,960L)
│   │   │   ├── index.tsx                  #   SessionPanel shell (props, composition)
│   │   │   ├── helpers.ts                 #   pure helper functions (already planned)
│   │   │   ├── browser-tab-strip.tsx      #   browser tabs UI
│   │   │   ├── browser-tracing.tsx        #   live event timeline
│   │   │   ├── memory-panel.tsx           #   memory/files/sources tabs
│   │   │   ├── browser-cooperation.tsx    #   proposal acceptance overlay
│   │   │   ├── hooks/
│   │   │   │   ├── use-browser-state.ts   #   browser state management hook
│   │   │   │   ├── use-panel-data.ts      #   session panel data hook
│   │   │   │   └── use-browser-sync.ts    #   backend tab sync hook
│   │   │   ├── browser-mirror.ts          #   ← already extracted (1,261L, may need further split)
│   │   │   └── cache.ts                   #   ← already extracted
│   │   ├── input-dock/                    # ← from input-dock.tsx (1,976L)
│   │   │   ├── index.tsx                  #   InputDock shell
│   │   │   ├── composer.tsx               #   rich text input area
│   │   │   ├── annotations.tsx            #   @-mention + annotation UI
│   │   │   ├── toolbar.tsx                #   action buttons bar
│   │   │   ├── hooks/
│   │   │   │   ├── use-composer.ts        #   editor state hook
│   │   │   │   └── use-commands.ts        #   slash command hook
│   │   │   └── helpers.ts                 #   pure utilities
│   │   ├── agent-message/                 # ← from agent-message.tsx (1,419L)
│   │   │   ├── index.tsx                  #   AgentMessage container
│   │   │   ├── content-blocks.tsx         #   message block rendering
│   │   │   ├── actions.tsx                #   action buttons (copy, retry)
│   │   │   └── thinking-block.tsx         #   reasoning display
│   │   ├── tool-block.tsx                 #   919L — may decompose later
│   │   ├── file-viewer-panel/             # ← from file-viewer-panel.tsx (1,079L)
│   │   │   ├── index.tsx                  #   panel container
│   │   │   ├── file-tree.tsx              #   tree navigation
│   │   │   ├── file-content.tsx           #   content display
│   │   │   └── hooks/
│   │   │       └── use-file-data.ts       #   data fetching hook
│   │   └── ...
│   ├── open-pr/
│   │   ├── open-pr-workspace/             # ← from open-pr-workspace.tsx (1,350L)
│   │   │   ├── index.tsx                  #   workspace container
│   │   │   ├── diff-viewer.tsx            #   PR diff display
│   │   │   ├── review-form.tsx            #   review submission
│   │   │   └── helpers.ts                 #   utilities
│   │   └── ...
│   └── ...
├── stores/
│   ├── chat-store/                        # ← from chat-store.ts (3,307L)
│   │   ├── index.ts                       #   re-exports createChatStore, providers
│   │   ├── internal.ts                    #   pure helpers + constants (already planned)
│   │   ├── conversation-slice.ts          #   conversation lifecycle actions
│   │   ├── message-slice.ts              #   message CRUD + streaming
│   │   ├── plan-slice.ts                 #   plan mode approval flow
│   │   ├── tool-slice.ts                 #   tool approval flow
│   │   ├── composer-slice.ts             #   composer state + slash commands
│   │   ├── usage-slice.ts               #   live usage + context window
│   │   └── browser-slice.ts             #   browser tool blocks sync
│   ├── terminal-store.ts
│   └── ...
├── api/
│   ├── client/                            # ← from client.ts (1,231L)
│   │   ├── index.ts                       #   re-exports
│   │   ├── http.ts                        #   base HTTP client + auth
│   │   ├── chat-api.ts                    #   chat-related endpoints
│   │   ├── workspace-api.ts               #   workspace endpoints
│   │   └── session-api.ts                 #   session endpoints
│   └── ...
└── ...
```

---

## Cross-Cutting Rules for All Decompositions

### 1. Safety Gate Chain

Every slice PR must pass this exact sequence before merge:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  ruff check  │───▶│    mypy      │───▶│    pytest     │───▶│      CI      │
│  src/ tests/ │    │  (hardened)  │    │  (≥ baseline) │    │  (all green) │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

**Backend gates:**
```bash
cd @backend
uv run ruff check src/ tests/                    # "All checks passed!"
uv run mypy <hardened module paths>               # "Success" (no new errors)
uv run pytest tests/ -q                           # ≥ baseline + new tests
```

**Frontend gates:**
```bash
cd @desktop-electron
npm run typecheck                                 # exit 0
npm test                                          # ≥ baseline + new tests
```

### 2. Test Requirements

| Slice complexity | Minimum test count | Coverage areas |
|------------------|--------------------|----------------|
| Trivial (constants, types) | 5 | Shape, invariants |
| Standard (1–3 methods) | 15 | Happy path, failures, edges |
| Complex (4+ methods, state) | 25+ | Happy, failure, concurrency, edges |

**Rules:**
- **Stubs, not mocks** — define minimal recording classes
- **Never modify existing tests** — only add new test files
- **Pin public contract** — test through public methods only
- **Cover every side effect** — metadata mutations, logs, scheduled work
- **Cover every failure mode** — collaborator raises, missing data, timeouts

### 3. Backward Compatibility Pattern

When extracting from a class that is consumed by external code:

```python
# In the god file — add delegation methods
async def extracted_method(self, **kwargs: Any) -> ReturnType:
    return await self._extracted_module.extracted_method(**kwargs)
```

This preserves the public API while the actual implementation lives
in the new module. Delegation methods are acceptable when external
consumers (tests, other modules) call the method on the original class.

### 4. Import Rules

- **No circular imports** — verify with `python -c "import personagent.<module>"`
- **No cross-layer imports** — `application/` cannot import from `interfaces/`
- **No new dependencies** — extracted module takes same collaborators as original
- **TYPE_CHECKING guard** — use for type-only imports to break cycles:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from personagent.some.module import SomeType
```

### 5. Naming Conventions

| Original | Extracted class | Module path |
|----------|-----------------|-------------|
| Methods on `FooService` | `FooBarHandler` | `foo/bar_handler.py` |
| Factory functions | stays as functions | `foo/factory.py` |
| Constants + types | no class needed | `foo/types.py` or `foo/constants.py` |

**Method names never change.** The class name carries the noun;
the method carries the verb.

### 6. Constants and Shared State

- Constants used **only** by extracted methods → move to new module
- Constants used by **both** old and new code → duplicate (remove from old when old code no longer needs them)
- Shared mutable state (caches, registries) → keep on parent, access via `self._w` reference

### 7. PR Sizing

| PR type | Max lines changed | Typical |
|---------|------------------:|--------:|
| Types/constants only | 500 | 200 |
| Standard extraction | 1,500 | 800 |
| Complex extraction | 2,500 | 1,200 |

If a slice exceeds 2,500 lines changed, split it into two PRs.

---

## Execution Order (Recommended)

### Phase 1.5 — Complete lightpanda.py (in progress)
- Slices 5–8 remaining → target: **~1,500L**

### Phase 2.0 — Browser ecosystem
- `browser_tools.py` → 6 slices (navigation, interaction, tabs, content, helpers, factory)

### Phase 2.1 — Data layer
- `operational_memory_repository.py` → 4 slices
- `operational_memory.py` (service) → 3 slices

### Phase 2.2 — API routes
- `routes/chat.py` → 5 slices
- `routes/workspace.py` → 4 slices
- `routes/sessions.py` → 4 slices

### Phase 2.3 — LLM adapters
- `vertex_ai_adapter.py` → 3 slices
- `codex_subscription_adapter.py` → 3 slices
- `kimi_coding_adapter.py` → 3 slices

### Phase 2.4 — Application services
- `browser_cooperation.py` → 3 slices
- `session_panel.py` → 3 slices
- `session_titles.py` → 2 slices

### Phase 3.0 — Frontend
- `session-panel.tsx` → 6 slices
- `chat-store.ts` → 7 slices
- `input-dock.tsx` → 4 slices
- `agent-message.tsx` → 3 slices
- `open-pr-workspace.tsx` → 3 slices
- `browser-mirror.ts` → 3 slices
- `api/client.ts` → 3 slices
- `file-viewer-panel.tsx` → 3 slices

---

## Integration with ADR 0022

This decomposition plan is **complementary** to ADR 0022 (Folder
Structure Principles). The ADR defines the target folder shape;
this plan defines the work to get there.

Key alignment points:
- **Principle 4** (use cases scale with sub-packages) — already
  proven by chat_completion and team_chat decompositions.
- **Principle 6** (infrastructure mirrors external concerns) —
  browser/, llm/, persistence/ sub-packages align with decomposition.
- Target structure above follows ADR 0022's shape exactly.

The ADR migration PR (Principle 7: `interfaces/` → `adapters/`)
should be scheduled **after** all active decomposition slices are
merged to avoid path conflicts.
