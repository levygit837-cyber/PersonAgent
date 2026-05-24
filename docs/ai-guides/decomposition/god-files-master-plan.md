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

| # | File | Original | Current | Status | Playbook |
|---|------|------:|------:|--------|----------|
| 1 | `infrastructure/browser/lightpanda.py` | 5,735 | 1,469 | 🔄 Phase 3 — 14 slices done (−74%), further decomp needed | `lightpanda.md` |
| 2 | `infrastructure/tools/browser_tools/factories.py` | 2,786 | 61 | ✅ Done — 4 slices (PRs #48, #57–#59), −98% | `browser_tools.md` |
| 3 | `infrastructure/persistence/operational_memory_repository.py` | 1,938 | 251 | ✅ Done — 6 slices (merged to main), −87% | `operational_memory_repository.md` |
| 4 | `interfaces/api/routes/chat/__init__.py` | 1,905 | 612 | 🔄 In progress — 6 slices merged, more pending | `routes_chat.md` |
| 5 | `infrastructure/llm/vertex_ai_adapter.py` | 1,064 | 31 | ✅ Done — 3 slices (PRs #47, #50, #53), −97% | `llm_adapters.md` |
| 6 | `interfaces/api/routes/workspace/` | 1,576 | 30 | ✅ Done — 4 slices (PR #84), −98% | `routes_workspace.md` |
| 7 | `interfaces/api/routes/sessions/__init__.py` | 1,471 | 166 | ✅ Done — 5 slices (−89%) | `routes_sessions.md` |
| 8 | `application/services/browser_cooperation/__init__.py` | 1,292 | 35 | ✅ Done — 4 slices (−97%) | `browser_cooperation.md` |
| 9 | `application/team_chat/blackboard.py` | 1,091 | 1,091 | ⏳ Not started | `blackboard.md` |
| 10 | `application/services/operational_memory.py` | 1,075 | 1,075 | ⏳ Not started | `operational_memory_service.md` |
| 11 | `application/services/session_panel.py` | 976 | 976 | ⏳ Not started | `session_panel_service.md` |
| 12 | `infrastructure/llm/codex_subscription_adapter.py` | 944 | 944 | ⏳ Not started | `llm_adapters.md` |
| 13 | `infrastructure/persistence/models.py` | 919 | 919 | ⏳ Not started | `persistence_models.md` |
| 14 | `infrastructure/llm/kimi_coding_adapter.py` | 892 | 892 | ⏳ Not started | `llm_adapters.md` |
| 15 | `application/services/session_titles.py` | 848 | 848 | ⏳ Not started | `session_titles.md` |
| 16 | `infrastructure/tools/filesystem_tools.py` | 810 | 810 | ⏳ Not started | `filesystem_tools.md` |

### Already decomposed (backend)

| File | Original | Current | Status |
|------|------:|------:|--------|
| `application/use_cases/chat_completion.py` | 2,742 | 483 | ✅ Done (−82%) |
| `application/team_chat/orchestrator.py` | 3,097 | 127 | ✅ Done (−96%) |
| `infrastructure/browser/lightpanda.py` | 5,735 | 1,469 | 🔄 Phase 3 — 14 slices done (−74%), further decomp needed |
| `infrastructure/tools/browser_tools/` | 2,786 | 61 | ✅ Done — 4 slices (−98%) |
| `infrastructure/persistence/operational_memory/` | 1,938 | 251 | ✅ Done — 6 slices (−87%) |
| `infrastructure/llm/vertex_ai/` | 1,064 | 31 | ✅ Done — 3 slices (−97%) |
| `interfaces/api/routes/workspace/` | 1,576 | 30 | ✅ Done — 4 slices (−98%) |
| `interfaces/api/routes/sessions/` | 1,471 | 166 | ✅ Done — 5 slices (−89%) |
| `application/services/browser_cooperation/` | 1,292 | 35 | ✅ Done — 4 slices (−97%) |
| `infrastructure/tools/browser_tools/helpers.py` | 1,111 | 543 | ✅ Done — 3 slices (PRs #91, #93, #95), −51% |

### Frontend god files

| # | File | Original | Current | Status | Playbook |
|---|------|------:|------:|--------|----------|
| 17 | `components/chat/session-panel.tsx` | 3,960 | 172 | ✅ Done — 6 slices (PRs #60–#63, #70, #71), −96% | `session_panel.md` |
| 18 | `stores/chat-store.ts` | 3,307 | 121 | ✅ Done — 6 slices (PRs #72–#74, #76–#78), −96% | `chat_store.md` |
| 19 | `stores/chat-store/streaming-helpers.ts` | 2,033 | 30 | ✅ Done — 4 modules (PR #80), −99% | — |
| 20 | `components/chat/input-dock.tsx` | 1,976 | 1,976 | ⏳ Not started | `input_dock.md` |
| 21 | `components/chat/agent-message.tsx` | 1,419 | 1,419 | ⏳ Not started | `agent_message.md` |
| 22 | `components/open-pr/open-pr-workspace.tsx` | 1,350 | 1,350 | ⏳ Not started | `open_pr_workspace.md` |
| 23 | `components/chat/session-panel/browser-mirror.ts` | 1,261 | 1,261 | ⏳ Not started | `browser_mirror.md` |
| 24 | `api/client.ts` | 1,231 | 1,231 | ⏳ Not started | `api_client.md` |
| 25 | `components/chat/file-viewer-panel.tsx` | 1,079 | 1,079 | ⏳ Not started | `file_viewer_panel.md` |
| 26 | `components/chat/tool-block.tsx` | 919 | 919 | ⏳ Not started | `tool_block.md` |
| 27 | `types/chat.ts` | 887 | 887 | ⏳ Not started | `chat_types.md` |

### Watchlist (below threshold but trending)

Files below 800L that may become god files as the codebase grows.
Monitor quarterly; promote to the inventory if they cross the
threshold and meet the three criteria.

| File | Lines | Notes |
|------|------:|-------|
| `infrastructure/tools/shell_tool.py` | 751 | Close to threshold; mixes tool factory + PTY lifecycle |
| `electron/main.ts` | 672 | Electron main process; mixes window management, IPC, PTY, auth, security |
| `components/layout/sidebar.tsx` | 770 | Close to threshold; growing as nav features are added |
| `domain/prompts/services/prompt_builder.py` | 649 | Complex prompt assembly; may grow with new providers |
| `infrastructure/config/settings.py` | 642 | Pydantic Settings; may grow with new config sections |
| `domain/exceptions.py` | 615 | Cross-cutting; may stay as-is if purely declarative |

---

## Decomposition Priority

### Tier 1 — Critical (>2,000L or blocking other work) — ALL DONE

1. ~~**`lightpanda.py`** — 5,735→1,469L~~ ✅
2. ~~**`browser_tools.py`** — 2,786→61L~~ ✅
3. ~~**`session-panel.tsx`** — 3,960→172L~~ ✅
4. ~~**`chat-store.ts`** — 3,307→121L~~ ✅

### Tier 2 — High (1,500–2,000L)

5. ~~**`operational_memory_repository.py`** — 1,938→251L~~ ✅
6. **`routes/chat.py`** — 1,905→612L 🔄 (6 slices merged, more pending)
7. **`input-dock.tsx`** — 1,976L ⏳
8. ~~**`routes/workspace.py`** — 1,576→30L~~ ✅
9. ~~**`routes/sessions.py`** — 1,471→166L~~ ✅

### Tier 3 — Medium (800–1,500L)

10. ~~**`browser_cooperation.py`** — 1,292→35L~~ ✅
11. **`blackboard.py`** — 1,091L ⏳
12. **`operational_memory.py`** (service) — 1,075L ⏳
13. ~~**`vertex_ai_adapter.py`** — 1,064→31L~~ ✅
14. **`session_panel.py`** (service) — 976L ⏳
15. **`codex_subscription_adapter.py`** — 944L ⏳
16. **`persistence/models.py`** — 919L ⏳
17. **`kimi_coding_adapter.py`** — 892L ⏳
18. **`agent-message.tsx`** — 1,419L ⏳
19. **`open-pr-workspace.tsx`** — 1,350L ⏳
20. **`browser-mirror.ts`** — 1,261L ⏳
21. **`api/client.ts`** — 1,231L ⏳
22. **`file-viewer-panel.tsx`** — 1,079L ⏳
23. **`tool-block.tsx`** — 919L ⏳
24. **`types/chat.ts`** — 887L ⏳
25. **`session_titles.py`** — 848L ⏳
26. **`filesystem_tools.py`** — 810L ⏳
27. **`streaming-helpers.ts`** — ~~2,033→30L~~ ✅

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
│   │   ├── team_chat/                     # ✅ orchestrator DONE (127L, was 3,097)
│   │   │   ├── orchestrator.py
│   │   │   ├── types.py
│   │   │   ├── blackboard/               # ← from blackboard.py (1,091L) NEW
│   │   │   │   ├── __init__.py            #   re-exports _Blackboard + constants
│   │   │   │   ├── blackboard.py          #   _Blackboard class (~500L target)
│   │   │   │   ├── json_parsing.py        #   Slice 1 — JSON/text extraction helpers
│   │   │   │   ├── claim_graph.py         #   Slice 2 — ClaimGraphAnalyzer
│   │   │   │   └── scoring.py             #   Slice 3 — coherency, novelty, keywords
│   │   │   ├── agent_turn_runner.py
│   │   │   ├── consensus_phase.py
│   │   │   ├── coordinator_phase.py
│   │   │   ├── final_synthesis.py
│   │   │   ├── helpers.py
│   │   │   ├── phase_loop.py
│   │   │   └── contracts.py
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
│   │   ├── lightpanda.py                  #   ✅ coordinator (1,469L — identity core)
│   │   ├── cdp_client.py                  #   ✅ Slice 1 — CDP transport
│   │   ├── cache.py                       #   ✅ Slice 2 — snapshot + stylesheet caches
│   │   ├── actions.py                     #   ✅ Slice 3 — click/type/scroll/screenshot/script/wait
│   │   ├── page_lifecycle.py              #   ✅ Slice 4 — open/close/switch/reload/history/list_tabs
│   │   ├── snapshot.py                    #   ✅ Slice 5 — DOM → structured view pipeline
│   │   ├── search.py                      #   ✅ Slice 6 — search URL building + result extraction
│   │   ├── view_actions.py                #   ✅ Slice 7 — view_* API (agent interaction layer)
│   │   ├── content.py                     #   ✅ Slice 8 — content extraction + markdown
│   │   ├── console.py                     #   ✅ Slice 9 — console listeners + cooperation
│   │   ├── opened_pages.py                #   ✅ Slice 10 — opened page tracking
│   │   ├── search_cache.py                #   ✅ Slice 11 — search result caching
│   │   ├── element_helpers.py             #   ✅ Slice 12 — element + frame helpers
│   │   ├── block_detection.py             #   ✅ Slice 13 — block/captcha detection
│   │   ├── page_helpers.py                #   ✅ Slice 14 — page resolution helpers
│   │   ├── models.py
│   │   ├── url_utils.py
│   │   └── content_cleanup.py
│   ├── tools/
│   │   ├── browser_tools/                 # ✅ DONE (was 2,786L → 61L orchestrator)
│   │   │   ├── __init__.py                #   ✅ re-exports create_browser_tools
│   │   │   ├── factories.py               #   ✅ create_browser_tools orchestrator (61L)
│   │   │   ├── navigation.py              #   ✅ search/open/extract/get_html tools
│   │   │   ├── interaction.py             #   ✅ click/type/scroll/screenshot/script tools
│   │   │   ├── tab_management.py          #   ✅ list_tabs/close_tab/switch_tab/reload/history
│   │   │   └── helpers.py                 #   ✅ shared response prep, normalization (1,111L)
│   │   ├── filesystem_tools/              # ← from filesystem_tools.py (810L)
│   │   │   ├── __init__.py
│   │   │   ├── factory.py                 #   create_filesystem_tools registry
│   │   │   ├── read_tools.py              #   read/list/search/grep tools
│   │   │   ├── write_tools.py             #   write/edit/create tools
│   │   │   └── helpers.py                 #   path validation, security checks
│   │   ├── shell_tool.py
│   │   └── mcp_tools.py
│   ├── persistence/
│   │   ├── models/                        # ← from models.py (919L) — planned
│   │   │   ├── __init__.py                #   re-exports all 31 ORM classes
│   │   │   ├── core.py                    #   TenantORM, ConversationORM, MessageORM, TaskRecordORM
│   │   │   ├── browser.py                 #   Slice 1 — 7 browser ORM classes
│   │   │   ├── team.py                    #   Slice 2 — 3 team mode ORM classes
│   │   │   ├── qa.py                      #   Slice 3 — 6 QA ORM classes
│   │   │   └── memory.py                  #   Slice 4 — 11 memory ORM classes
│   │   ├── operational_memory/            # ✅ DONE (was 1,938L → 251L repository)
│   │   │   ├── __init__.py                #   ✅ barrel
│   │   │   ├── operational_memory_repository.py  #   ✅ main repository (251L)
│   │   │   ├── recall_retrieval.py         #   ✅ recall + search + scoring pipeline
│   │   │   ├── scoring.py                 #   ✅ ScoringRanker
│   │   │   ├── structured_items.py        #   ✅ StructuredItemStore
│   │   │   ├── event_outbox.py            #   ✅ EventOutboxManager
│   │   │   ├── models.py                  #   ✅ StoredMemoryChunk + StoredStructuredMemoryItem
│   │   │   └── _search_helpers.py         #   ✅ SQL-building helpers
│   │   └── ...
│   ├── llm/
│   │   ├── vertex_ai/                     # ✅ DONE (was 1,064L → 31L re-export)
│   │   │   ├── __init__.py                #   ✅ re-export barrel (31L)
│   │   │   ├── adapter.py                 #   ✅ VertexAiAdapter main class (397L)
│   │   │   ├── streaming.py               #   ✅ stream response handling (364L)
│   │   │   ├── content_builder.py         #   ✅ request content formatting (302L)
│   │   │   └── models.py                  #   ✅ VertexModelSpec, config types (100L)
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
│   ├── chat/                              # 🔄 IN PROGRESS (was 1,905L → 612L)
│   │   ├── __init__.py                    #   router + remaining endpoints (612L)
│   │   ├── helpers.py                     #   ✅ extracted — shared helpers (351L)
│   │   ├── models_listing.py              #   ✅ extracted — list_models, list_commands (218L)
│   │   ├── completion.py                  #   ✅ extracted — chat_completion + chat_completion_stream (606L)
│   │   ├── plan_approval.py               #   ✅ extracted — approve/continue/cancel plan (148L)
│   │   ├── tool_approval.py               #   ✅ extracted — approve/reject tool (287L)
│   │   └── team_chat.py                   #   ✅ extracted — team_chat_websocket + persistence (478L)
│   ├── workspace/                         # ← from routes/workspace.py (1,576L)
│   │   ├── __init__.py
│   │   ├── grant.py                       #   workspace grant endpoints
│   │   ├── filesystem.py                  #   file read/write/search endpoints
│   │   ├── git.py                         #   git operations endpoints
│   │   └── helpers.py                     #   shared workspace resolution
│   ├── sessions/                          # ✅ DONE (was 1,471L → 166L)
│   │   ├── __init__.py                    #   ✅ router (166L)
│   │   ├── browser_interaction.py         #   ✅ browser interaction endpoints (382L)
│   │   ├── workspace_data.py              #   ✅ workspace data endpoints (280L)
│   │   ├── _workspace_infra.py            #   ✅ workspace infrastructure (269L)
│   │   ├── browser_viewport.py            #   ✅ browser viewport endpoints (213L)
│   │   ├── cooperation.py                 #   ✅ cooperation endpoints (175L)
│   │   └── models.py                      #   ✅ shared models (131L)
│   └── ...
│
@desktop-electron/src/
├── types/
│   ├── chat/                              # ← from chat.ts (887L) NEW
│   │   ├── index.ts                       #   barrel re-exports
│   │   ├── conversation.ts                #   conversation, message, command, skill types
│   │   ├── team.ts                        #   Slice 1 — 15 team mode types (~250L)
│   │   ├── tool-types.ts                  #   Slice 2 — ToolBlockUi, ToolBlockStatus
│   │   ├── models.ts                      #   Slice 3 — provider, reasoning, streaming, auth types
│   │   └── memory-types.ts                #   Slice 4 — memory trace types
│   └── ...
├── components/
│   ├── chat/
│   │   ├── session-panel/                 # ✅ DONE (was 3,960L → 172L orchestrator)
│   │   │   ├── session-panel.tsx           #   ✅ orchestrator (172L)
│   │   │   ├── helpers.ts                 #   ✅ Slice 1 — types + pure functions (401L)
│   │   │   ├── use-session-panel-state.ts #   ✅ Slice 2 — data loading hook (117L)
│   │   │   ├── use-browser-tabs.ts        #   ✅ Slice 3 — browser tab hook (560L)
│   │   │   ├── browser-helpers.ts         #   ✅ Slice 3 — browser pure functions (1,000L)
│   │   │   ├── browser-tab-strip.tsx      #   ✅ Slice 4 — tab strip UI (93L)
│   │   │   ├── browser-controls.tsx       #   ✅ Slice 4 — nav + mode buttons (56L)
│   │   │   ├── browser-cooperation.tsx    #   ✅ Slice 4 — proposal overlay (157L)
│   │   │   ├── browser-tracing.tsx        #   ✅ Slice 4 — tracing panel (243L)
│   │   │   ├── shared-ui.tsx              #   ✅ Slice 4 — shared components (62L)
│   │   │   ├── browser-tab-content.tsx    #   ✅ Slice 5 — tab content (553L)
│   │   │   ├── detail-sections.tsx        #   ✅ Slice 6 — right-rail sections (348L)
│   │   │   ├── browser-mirror.ts          #   ← pre-existing (1,261L, may need further split)
│   │   │   └── cache.ts                   #   ← pre-existing
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
│   │   ├── tool-block/                    # ← from tool-block.tsx (919L) NEW
│   │   │   ├── index.tsx                  #   ToolBlock router + CompactToolGroupBlock (~80L)
│   │   │   ├── write-output.tsx           #   Slice 1 — WriteToolEvent + diff parsing
│   │   │   ├── read-shell.tsx             #   Slice 2 — Read/Shell/Generic/Browser events
│   │   │   ├── todo-block.tsx             #   Slice 3 — Todo components
│   │   │   ├── utils.ts                   #   Slice 3 — shared utilities + status helpers
│   │   │   ├── browser-output.ts          #   ← already extracted
│   │   │   ├── search-output.ts           #   ← already extracted
│   │   │   ├── todo.ts                    #   ← already extracted
│   │   │   └── visibility.ts              #   ← already extracted
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
│   ├── chat-store/                        # ✅ DONE (was 3,307L → 121L orchestrator)
│   │   ├── chat-store.ts                  #   ✅ orchestrator + providers (121L)
│   │   ├── internal.ts                    #   ✅ Slice 1 — pure helpers + constants (690L)
│   │   ├── composer-slice.ts              #   ✅ Slice 2 — composer state + actions (42L)
│   │   ├── conversation-slice.ts          #   ✅ Slice 3 — load/start/regenerate/rewind/branch (93L)
│   │   ├── streaming-slice.ts             #   ✅ Slice 4 — sendMessage + stopStreaming (191L)
│   │   ├── streaming-helpers.ts           #   ✅ re-export barrel (30L) ← decomposed further:
│   │   │   ├── chunk-handlers.ts          #   ✅ handleChunk + text/tool processing (~530L)
│   │   │   ├── team-event-handlers.ts     #   ✅ handleTeamEvent + ~40 team functions (~1,100L)
│   │   │   ├── approval-helpers.ts        #   ✅ plan/tool approval parsing (~69L)
│   │   │   └── message-helpers.ts         #   ✅ messageFromPersisted + image helpers (~108L)
│   │   ├── plan-approval-slice.ts         #   ✅ Slice 5 — approve/continue/cancel plan (97L)
│   │   └── tool-approval-slice.ts         #   ✅ Slice 6 — approve/reject tool (131L)
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

### 8. ORM / Database Model Rules (for persistence/models decomposition)

- **Never change table names or column names** — this would require a DB migration.
- **Verify Alembic** — after each slice, run `uv run alembic check` to confirm no phantom migrations are generated.
- **Preserve conditional imports** — the `pgvector` try/except pattern must be replicated in destination files.
- **All models must be discoverable** — `Base.metadata` collects models at import time; the `__init__.py` barrel must import all sub-modules so Alembic sees them.

### 9. Frontend Barrel Re-export Rules (for types/chat and store splits)

- **Every consumer import path must keep working** — the barrel `index.ts` re-exports everything from sub-modules.
- **Runtime values must not live in type-only files** — constants, arrays, and functions go in files importable at runtime.
- **Do not rename exports** — renaming a 71-export type file would cascade across dozens of consumers.

---

## Execution Order (Recommended)

### Phase 1.5 — Complete lightpanda.py ✅ DONE
- All 14 slices merged (PRs #37–#56): 5,735 → 1,469L (−74%)

### Phase 2.0 — Browser ecosystem ✅ DONE
- `browser_tools.py` → 4 slices (PRs #48, #57–#59): 2,786 → 61L (−98%)

### Phase 2.1 — Data layer (partially done)
- ~~`operational_memory_repository.py`~~ → 6 slices: 1,938 → 251L (−87%) ✅
- `operational_memory.py` (service) → 3 slices ⏳
- `persistence/models.py` → 4 slices ⏳

### Phase 2.2 — API routes (partially started)
- `routes/chat.py` → 2 slices merged (PRs #75, #79): 1,905 → 1,419L (−26%) 🔄
- `routes/workspace.py` → 4 slices ⏳
- `routes/sessions.py` → 4 slices ⏳

### Phase 2.3 — LLM adapters (partially done)
- ~~`vertex_ai_adapter.py`~~ → 3 slices (PRs #47, #50, #53): 1,064 → 31L (−97%) ✅
- `codex_subscription_adapter.py` → 3 slices ⏳
- `kimi_coding_adapter.py` → 3 slices ⏳

### Phase 2.4 — Application services
- `browser_cooperation.py` → 3 slices ⏳
- `blackboard.py` → 3 slices ⏳
- `session_panel.py` → 3 slices ⏳
- `session_titles.py` → 2 slices ⏳

### Phase 3.0 — Frontend (partially done)
- ~~`session-panel.tsx`~~ → 6 slices (PRs #60–#63, #70, #71): 3,960 → 172L (−96%) ✅
- ~~`chat-store.ts`~~ → 6 slices (PRs #72–#74, #76–#78): 3,307 → 121L (−96%) ✅
- ~~`streaming-helpers.ts`~~ → 4 modules (PR #80): 2,033 → 30L (−99%) ✅
- `input-dock.tsx` → 4 slices ⏳
- `agent-message.tsx` → 3 slices ⏳
- `open-pr-workspace.tsx` → 3 slices ⏳
- `browser-mirror.ts` → 3 slices ⏳
- `api/client.ts` → 3 slices ⏳
- `file-viewer-panel.tsx` → 3 slices ⏳
- `tool-block.tsx` → 3 slices ⏳
- `types/chat.ts` → 4 slices ⏳

---

## Summary: Total Decomposition Scope

| Category | Files | Slices done | Status |
|----------|------:|-------:|--------|
| Backend — completed | 6 | ~36 slices | ✅ lightpanda (14), browser_tools (4), op_memory_repo (6), vertex_ai (3), chat_completion, orchestrator |
| Backend — in progress | 1 | 2 slices | 🔄 routes/chat |
| Backend — remaining | 10 | ~31 slices est. | ⏳ |
| Frontend — completed | 3 | ~16 slices | ✅ session-panel (6), chat-store (6), streaming-helpers (4) |
| Frontend — remaining | 8 | ~29 slices est. | ⏳ |
| **Total** | **28** | **~54 done / ~60 remaining** | **~47% complete** |

### Lines reduced so far

| God file | Original | Current | Reduction |
|----------|------:|------:|-----------|
| `lightpanda.py` | 5,735 | 1,469 | −74% |
| `browser_tools/factories.py` | 2,786 | 61 | −98% |
| `chat_completion.py` | 2,742 | 483 | −82% |
| `team_chat/orchestrator.py` | 3,097 | 127 | −96% |
| `operational_memory_repository.py` | 1,938 | 251 | −87% |
| `vertex_ai_adapter.py` | 1,064 | 31 | −97% |
| `session-panel.tsx` | 3,960 | 172 | −96% |
| `chat-store.ts` | 3,307 | 121 | −96% |
| `streaming-helpers.ts` | 2,033 | 30 | −99% |
| `routes/chat/__init__.py` | 1,905 | 1,419 | −26% (in progress) |
| **Total** | **28,567** | **4,164** | **−85%** |

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
- **`persistence/models/` split** aligns with Principle 2 (bounded
  contexts in domain) — each ORM group maps to a domain concept.

The ADR migration PR (Principle 7: `interfaces/` → `adapters/`)
should be scheduled **after** all active decomposition slices are
merged to avoid path conflicts.
