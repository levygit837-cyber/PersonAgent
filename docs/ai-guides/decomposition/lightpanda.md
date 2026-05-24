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
| 3 — Extract `BrowserActions` | ⏳ Pending | — | |
| 4 — Extract `BrowserPageLifecycle` | ⏳ Pending | — | |
| 5 — Extract `BrowserSnapshot` | ⏳ Pending | — | |
| 6 — Extract `BrowserSearch` | ⏳ Pending | — | |
| 7 — Extract `BrowserViewActions` | ⏳ Pending | — | |
| 8 — Inline what remains | ⏳ Pending | — | |

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
