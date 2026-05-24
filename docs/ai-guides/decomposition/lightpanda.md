# Playbook: Decompose `lightpanda.py`

**Target file:** `@backend/src/personagent/infrastructure/browser/lightpanda.py`
(5,735 lines — the largest god file in the repo)

**Target package:** `@backend/src/personagent/infrastructure/browser/`
(new modules go here as siblings)

**Tests:**
- `@backend/tests/test_lightpanda_browser_tools.py` (integration)
- `@backend/tests/test_browser_cooperation.py`

Read `_protocol.md` first.

## Why this file is hard

`LightPandaBrowserWorker` is the integration boundary between the
agent's tool calls and a Chrome-DevTools-Protocol (CDP) server.
The class is responsible for:

1. **CDP transport** — sending JSON-RPC frames over a WebSocket
   and routing responses back to callers (1,200+ lines).
2. **Page lifecycle** — opening tabs, waiting for visual / load
   readiness, closing tabs, switching tabs.
3. **Visible-page actions** — click, type, scroll, key press,
   screenshot.
4. **Snapshot pipeline** — converting a live DOM into a
   structured HTML + element-map representation (with disk and
   in-memory caches).
5. **Search** — provider-specific URL building and result
   extraction.
6. **View mode** — the higher-level `view_*` API used by the
   browser-tab tool for agent interaction.

Each of these is a separable concern. The current file mixes
them so a CDP retry change might accidentally affect the
screenshot pipeline.

## Public contract that must be preserved

The class is consumed by:

- `infrastructure/tools/browser_*.py` — every browser tool
  imports `LightPandaBrowserWorker` directly.
- `application/services/browser_*.py` — orchestration around
  the worker.

Public surface (do not rename, do not change signature):

- `__init__`
- `warmup`, `close`
- `search`, `search_url`, `search_provider_label`
- `open`, `extract_content`, `get_html`, `list_tabs`
- `click`, `type_input`, `screenshot`, `scroll`, `reload`,
  `history`, `switch_tab`, `close_tab`, `wait`, `script`,
  `read_console`
- `view_snapshot`, `view_navigate`, `view_history`,
  `view_reload`, `view_click`, `view_key`, `view_scroll`,
  `view_act`

The `_RawCdpClient` private class (5,505+) is *not* exported but
is closely tied to the worker; extract them as a pair when
appropriate.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract `_RawCdpClient` to `cdp_client.py` | ✅ Merged | — | 56 lines removed from lightpanda.py; new `CdpClient` class + backward-compat alias |
| 2 — Extract `BrowserSnapshotCache` | ✅ Merged | — | 116 lines removed; `SnapshotCache` + `StylesheetDiskCache` in `cache.py` |
| 3 — Extract `BrowserActions` | ✅ Merged | — | 535 lines removed; 7 action methods in `actions.py` + backward-compat delegations |
| 4 — Extract `BrowserPageLifecycle` | ✅ Merged | — | 342 lines removed; 6 public methods in `page_lifecycle.py` + backward-compat delegations |
| 5 — Extract `BrowserSnapshot` | ✅ Merged | — | 577 lines removed; 14 methods in `snapshot.py` + backward-compat delegations; 37 new tests |
| 6 — Extract `BrowserSearch` | ✅ Merged | — | 253 lines removed; search + search_url + 4 scripts in `search.py` + backward-compat delegations; 27 new tests |
| 7 — Extract `BrowserViewActions` | ✅ Merged | — | 317 lines removed; 7 view_* methods in `view_actions.py` + backward-compat delegations; 23 new tests |
| 8 — Inline what remains | ✅ Merged | — | JS scripts → `scripts.py` (942 lines); content extraction → `content.py` (20 methods); 20 new tests; lightpanda.py: 3,520 → 2,015 (−43%) |
| 9 — Extract console & cooperation | ✅ Merged | — | 8 methods, 105 lines removed; `BrowserConsole` in `console.py`; 32 new tests |
| 10 — Extract opened page tracking | ✅ Merged | — | 8 methods, 116 lines removed; `OpenedPageTracker` in `opened_pages.py`; 27 new tests |
| 11 — Extract search result cache | ✅ Merged | — | 9 methods, 74 lines removed; `SearchResultCache` in `search_cache.py`; 30 new tests |
| 12 — Extract element & frame helpers | ⏳ Pending | — | 8 methods, ~91 lines → existing helpers or `element_helpers.py` |
| 13 — Extract block detection | ⏳ Pending | — | 4 methods, ~127 lines → `block_detection.py` |
| 14 — Extract page helpers | ⏳ Pending | — | 10 methods, ~180 lines → `page_helpers.py` |

**After Phase 2 (slices 9–14):** lightpanda.py target: ~700 lines (init, facade
delegations, session management, CDP infrastructure, page resolution, navigation).
These remaining ~700 lines form the **identity core** of the worker and should NOT
be extracted further — they are the state machine, connection pool, and CDP
transport that all other modules depend on via `self._w`.

## Phase 2 — Additional low-risk slices (9–14)

### Line budget after Phase 1 (slices 1–8)

| Category | Methods | Lines | Risk |
|----------|---------|-------|------|
| Init / warmup / close | 3 | 94 | ⛔ Core — stays |
| Facade delegations | 25 | 87 | ⛔ Core — stays |
| **Console & cooperation** | **8** | **147** | 🟢 Low |
| **Opened page tracking** | **8** | **148** | 🟢 Low |
| **Search result cache** | **9** | **133** | 🟢 Low |
| **Element & frame helpers** | **8** | **91** | 🟢 Low |
| **Block detection** | **4** | **127** | 🟢 Low |
| **Page helpers** | **10** | **180** | 🟡 Medium |
| Session management | 20 | 339 | 🔴 Core — stays |
| Page resolution | 8 | 245 | 🔴 Core — stays |
| CDP infrastructure | 9 | 216 | 🔴 Core — stays |
| Navigation | 2 | 56 | 🔴 Core — stays |
| Misc (snapshot delegations) | 10 | 66 | ⛔ Core — stays |

## Proposed slices (in order; expect 8+ PRs)

### Slice 1 — Extract `_RawCdpClient` to `cdp_client.py`

**What moves out:**

- `_RawCdpClient` class (5,505–end) — ~200 lines

**Why first:** The class is already self-contained and only
talks to a WebSocket. It has no dependency on the worker; the
worker holds a reference to it. Move it; rename to `CdpClient`;
keep a leading-underscore alias for backwards compat.

**Tests required:** `tests/unit/test_lightpanda_cdp_client.py`
(new). Minimum 10 cases with a fake WebSocket:

- `send_command` round-trips a frame and returns the correct
  reply.
- Concurrent commands are matched to their replies by message
  id.
- A reply with an `error` field raises a typed exception.
- `wait_for_event` yields when the matching event arrives and
  ignores non-matching events.
- Close cleans up pending callers (no orphaned futures).

**Risk:** Low — the surface is small and well-typed.

### Slice 2 — Extract `BrowserSnapshotCache` to `snapshot_cache.py`

**What moves out:**

- `_render_snapshot_cache_key` (3,234)
- `_render_snapshot_url_cache_key` (3,253)
- `_read_render_snapshot_cache` (3,257)
- `_store_render_snapshot_cache` (3,270)
- `_clone_render_snapshot` (3,296)
- The in-memory cache dict (search for `_render_snapshot_cache`
  attribute initialization)

Also extract the stylesheet disk cache:

- `_stylesheet_disk_cache_path` (3,440)
- `_read_stylesheet_disk_cache` (3,444)
- `_write_stylesheet_disk_cache` (3,463)
- `_trim_stylesheet_disk_cache` (3,477)

**Module name:** `lightpanda/cache.py` (could be two classes:
`SnapshotCache` + `StylesheetCache`).

**Risk:** Low. The cache is invariant under any sequence of
reads/writes, and the keying logic is pure.

**Tests:** 15+ cases. Use `tmp_path` for disk cache; in-memory
cache uses a stub clock for TTL behavior.

### Slice 3 — Extract `BrowserActions` (visible-page actions)

**What moves out:**

- `click` (2016)
- `type_input` (2132)
- `screenshot` (2266)
- `scroll` (2539)
- `read_console` (2415)
- `script` (2460)
- `wait` (2656)

**Module:** `lightpanda/actions.py`. Class: `BrowserActions`.

**Collaborators:**

- `cdp_client: CdpClient`
- `_wait_for_page_settle` (helper from the worker; may need to
  be moved or duplicated)

**Risk:** Medium. Actions interact with the page's DOM state;
side effects matter. Tests for each action with a stubbed CDP
client (recording dispatched commands).

### Slice 4 — Extract `BrowserPageLifecycle`

**What moves out:**

- `open` (1242)
- `close_tab` (2358)
- `switch_tab` (2630)
- `list_tabs` (1547)
- `reload` (2572)
- `history` (2597)
- `_wait_for_page_visual_ready` (3200)
- `_wait_for_page_load_complete` (3226)
- `_wait_for_page_settle` (4529)

**Module:** `lightpanda/page_lifecycle.py`.

**Risk:** Medium-high. Tab management has subtle races (open +
switch + close). Pin every observable side effect with tests
before extracting.

### Slice 5 — Extract `BrowserSnapshot` (DOM → structured view)

**What moves out:**

- `view_snapshot` (1662)
- `_browser_view_snapshot` (2736)
- `_browser_element_map`, `_browser_iframe_element_map`,
  `_browser_frame_tree_snapshot`, `_browser_tabs_snapshot`,
  `_enrich_browser_element_map`, `_panel_session_tabs`
- `_html_with_embedded_stylesheet_fallbacks` (3305)
- `_computed_html_snapshot`, `_stylesheet_hrefs`, `_html_attrs`
- `_fetch_stylesheet_css`
- `_readable_dom_content_url`
- `_html_or_empty`

**Module:** `lightpanda/snapshot.py`.

**Collaborators:**

- `cdp_client`
- `snapshot_cache`, `stylesheet_cache` (from slice 2)

**Risk:** High. This is the most complex pipeline in the file —
it includes HTTP fetches, multiple async branches, and disk
I/O. Land it with thorough integration tests as the safety net.
The `test_lightpanda_browser_tools.py` file already exercises
this end-to-end; do not regress that test.

### Slice 6 — Extract `BrowserSearch`

**What moves out:**

- `search` (1168)
- `search_url` (2694)
- `search_provider_label` (1160)
- `_search_results_script` (1062 — module-level helper, move it
  with the class)

**Module:** `lightpanda/search.py`.

**Risk:** Low. Search is mostly pure URL-building plus a CDP
call.

### Slice 7 — Extract `BrowserViewActions` (view-mode wrappers)

**What moves out:**

- `view_navigate` (1683)
- `view_history` (1713)
- `view_reload` (1753)
- `view_click` (1799)
- `view_key` (1836)
- `view_scroll` (1867)
- `view_act` (1896)

**Module:** `lightpanda/view_actions.py`.

**Note:** These wrap the slice-3 actions with view-mode
semantics (auto-snapshot after action, etc). Land slice 3
first.

**Risk:** Medium.

### Slice 8 — Inline what remains

After slices 1–7, `LightPandaBrowserWorker` should be a thin
facade that owns the lifecycle of all the subsystems and
delegates calls to them. Target: **under 1,000 lines.**

The facade keeps every public method (with the same signature)
so the callers don't change. The body of each method is now
`return await self._snapshot.view_snapshot(...)` etc.

This is the **last** slice. Do not collapse the facade — it's
the backward-compat layer.

### Slice 9 — Extract console & cooperation listeners to `console.py`

**What moves out:**

- `_attach_page_console_listeners` (L935–974)
- `_console_message_attr` (L975–981)
- `_record_console_entry` (L982–1005)
- `_install_console_capture` (L1281–1284)
- `_install_cooperation_capture` (L1285–1302)
- `_drain_page_console_entries` (L1303–1324)
- `_drain_cooperation_events` (L1325–1342)
- `_record_cooperation_event` (L1343–1356)
- Related instance attrs: `_console_cache`, `_console_sequence`,
  `_console_listener_keys`, `_cooperation_event_cache`,
  `_cooperation_listener_keys`

**Module:** `browser/console.py`. Class: `BrowserConsole`.

**Dependencies (via `self._w`):** `_evaluate_page`, `_clean_browser_url`, scripts
from `scripts.py`.

**Risk:** 🟢 Low. Console capture is almost entirely self-contained.
Only `_drain_page_console_entries` calls `_evaluate_page` on the worker.

**Callers that need updating:**
- `actions.py` calls `_drain_page_console_entries`, `_console_cache`, `_attach_page_console_listeners`
- `page_lifecycle.py` calls `_attach_page_console_listeners`
- `_resolve_live_page` calls `_attach_page_console_listeners`
- Worker `close()` clears console caches

**Tests:** 10+ cases covering attach, record, drain, cooperation events.

### Slice 10 — Extract opened page tracking to `opened_pages.py`

**What moves out:**

- `_cache_opened_page` (L1658–1701)
- `_browser_open_response` (L1702–1730)
- `_opened_page_read_status` (L1731–1733)
- `_opened_page_tab` (L1734–1763)
- `_opened_page` (L1764–1773)
- `_opened_page_by_url` (L1774–1789)
- `_target_title` (L1790–1795)
- `_next_unextracted_opened_page` (L1866–1875)
- Related instance attrs: `_opened_pages_cache`, `_last_open_cache`

**Module:** `browser/opened_pages.py`. Class: `OpenedPageTracker`.

**Dependencies (via `self._w`):** `_clean_browser_url`, `_urls_equivalent`
(both from `url_utils.py` — pure functions, easy to import directly).

**Risk:** 🟢 Low. Pure state tracking with no async operations or CDP calls.
Every method is synchronous.

**Callers that need updating:**
- `page_lifecycle.py` — `_cache_opened_page`, `_browser_open_response`,
  `_opened_page_by_url`, `_opened_page_tab`, `_last_open_cache`
- `content.py` — `_opened_page`, `_cleanup_live_pages` (uses `_opened_page`)
- `_resolve_live_page` — `_opened_page`
- `_resolve_content_target` — `_opened_page`, `_next_unextracted_opened_page`

**Tests:** 10+ cases covering cache, lookup, response formatting.

### Slice 11 — Extract search result cache to `search_cache.py`

**What moves out:**

- `_cache_search_results` (L1610–1631)
- `_latest_cached_search_results` (L1632–1637)
- `_copy_search_results` (L1638–1651)
- `_remember_current_url` (L1652–1657)
- `_result_url` (L1883–1916)
- `_result_title` (L1917–1932)
- `_match_search_result_url` (L1933–1948)
- `_match_search_result_title` (L1949–1964)
- `search_url` delegation (L386–388)
- Related attrs: `_search_cache`, `_current_url_cache`

**Module:** `browser/search_cache.py`. Class: `SearchResultCache`.

**Dependencies:** `_clean_browser_url`, `_urls_equivalent`, `BrowserSearchResult`,
`BrowserSearchSnapshot` (all pure).

**Risk:** 🟢 Low. Pure synchronous state tracking, no CDP or async.

**Callers that need updating:**
- `page_lifecycle.py` — `_result_url`, `_result_title`, `_match_search_result_url`,
  `_match_search_result_title`, `_remember_current_url`
- `_get_session` — `_latest_cached_search_results`
- `content.py` — `_remember_current_url`
- `_cleanup_search_cache` — internal cache access

**Tests:** 8+ cases covering cache, lookup, dedup.

### Slice 12 — Extract element & frame helpers to `element_helpers.py`

**What moves out:**

- `_element_selector` (L422–427)
- `_element_target` (L428–435)
- `_browser_action_target_payload` (L437–454, static method)
- `_action_context_for_element` (L455–464)
- `_page_frames` (L465–477)
- `_main_frame` (L478–486)
- `_frame_id` (L487–495)
- `_frame_viewport_offset` (L496–513)
- Related attr: `_element_map_cache`

**Module:** `browser/element_helpers.py`. Class: `ElementHelpers` or
standalone functions.

**Dependencies:** Only `_element_map_cache` (a dict), no CDP calls.

**Risk:** 🟢 Low. Pure lookups and frame navigation — no async CDP needed
except `_frame_viewport_offset` (minor bounding-box call).

**Callers that need updating:**
- `actions.py` — `_element_selector`, `_element_target`, `_browser_action_target_payload`,
  `_action_context_for_element`, `_page_frames`, `_frame_id`, `_frame_viewport_offset`,
  `_main_frame`, `_element_map_cache`
- `snapshot.py` — `_page_frames`, `_frame_id`, `_browser_element_map`, `_element_map_cache`

**Tests:** 8+ cases covering selector lookup, frame ID generation, viewport offset.

### Slice 13 — Extract block detection to `block_detection.py`

**What moves out:**

- `_raise_if_google_blocked` (L1483–1523)
- `_raise_if_bing_blocked` (L1524–1564)
- `_raise_if_yahoo_blocked` (L1565–1604)
- `_raise_if_search_blocked` (L1605–1609)

**Module:** `browser/block_detection.py`. Standalone functions or
`BlockDetector` class.

**Dependencies (via `self._w`):** `_safe_title`, `_evaluate_page`.

**Risk:** 🟢 Low. These are pure detection + raise logic. The only
interaction with the worker is reading page title/body text.

**Callers that need updating:**
- `page_lifecycle.py` — `_raise_if_search_blocked` (after navigating)
- `search.py` — may call `_raise_if_search_blocked` after search navigation

**Tests:** 6+ cases covering each provider detection + no-block passthrough.

### Slice 14 — Extract page helpers to `page_helpers.py`

**What moves out:**

- `_wait_for_page_visual_ready` (L389–414)
- `_wait_for_page_load_complete` (L415–421)
- `_upload_files` (L514–536)
- `_drag_between_elements` (L537–591)
- `_set_page_viewport` (L592–600)
- `_safe_user_agent` (L601–607)
- `_safe_html` (L608–622)
- `_safe_scroll_state` (L623–638)
- `_safe_title` (L1461–1473)
- `_safe_title_for_url` (L1474–1482)

**Module:** `browser/page_helpers.py`. Class: `PageHelpers`.

**Dependencies (via `self._w`):** `_evaluate_page`,
`_raw_runtime_evaluate_value`, `timeout_ms`, scripts from `scripts.py`.

**Risk:** 🟡 Medium. These helpers are heavily used by actions.py,
content.py, snapshot.py, and page_lifecycle.py. Careful wiring needed.
However, each function is individually simple.

**Callers that need updating:**
- `actions.py` — `_safe_title`, `_safe_user_agent`, `_safe_html`,
  `_safe_scroll_state`, `_set_page_viewport`, `_wait_for_page_load_complete`,
  `_upload_files`, `_drag_between_elements`
- `content.py` — `_safe_title`
- `page_lifecycle.py` — `_safe_title`
- `block_detection.py` (if already extracted) — `_safe_title`, `_evaluate_page`
- `snapshot.py` — `_safe_html`

**Tests:** 10+ cases covering viewport, title, HTML, scroll, upload, drag.

## Pre-condition tests

```bash
cd @backend
uv run pytest tests/test_lightpanda_browser_tools.py \
              tests/test_browser_cooperation.py \
              -v --no-header
```

Some of these tests require a running LightPanda process. If
you can't run them locally, mark them as `pytest.mark.integration`
and skip — but **add the marker only if it already exists**, and
note in the PR description that the integration tests were not
run locally.

## Anti-patterns specific to this file

- **Do not unify the snapshot cache and stylesheet cache yet.**
  They have different TTLs, different keys, and different
  serialization formats. Keep them separate.
- **Do not move CDP error-handling logic into a "policy"
  module.** It's tied to specific commands; lifting it would
  hide assumptions.
- **Do not introduce a new abstraction layer above CDP.** Other
  browser providers (e.g. Playwright) can be added later via a
  separate `BrowserBackend` protocol; for now, the worker is
  CDP-specific.
- **Do not change the public method signatures even slightly.**
  Every method is called by at least one tool, and tools are
  called by the LLM — silent contract changes ripple through to
  the model.

## Special concern: integration vs unit tests

This file is one of the few in the repo where integration tests
are non-trivial (require a running LightPanda binary). Until
you have a verified local environment that can run them:

1. **Run the unit suite** after every slice (cheap, fast):
   ```bash
   uv run pytest tests/unit -q --no-header
   ```
2. **Run the LightPanda integration suite** at minimum after
   slices 3, 4, 5, and 8 — these touch behavior that unit tests
   can't catch:
   ```bash
   uv run pytest tests/test_lightpanda_browser_tools.py \
                 tests/test_browser_cooperation.py \
                 -v --no-header
   ```
3. **Note in PR description** which tests were run vs not run.
   Reviewers will know to run the missing ones before
   approving.

## Validation gates

```bash
cd @backend
uv run ruff check --fix src/ tests/
uv run ruff check src/ tests/
uv run mypy src/personagent/infrastructure/browser \
            src/personagent/application/use_cases/chat \
            src/personagent/application/state \
            src/personagent/domain/models/conversation.py
uv run pytest tests/unit tests/test_tool_loop_limit.py tests/test_alembic_setup.py \
              tests/test_conversations_api.py tests/test_team_chat_orchestrator.py \
              tests/test_action_approvals.py \
              -q --no-header \
              --deselect tests/unit/test_prompt_builder.py::TestPromptBuilder::test_agent_state_overlays_are_compact
```

Then, *if your environment supports it*:

```bash
uv run pytest tests/test_lightpanda_browser_tools.py \
              tests/test_browser_cooperation.py \
              -v --no-header
```
