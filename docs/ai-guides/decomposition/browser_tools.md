# Playbook: Decompose `browser_tools.py`

**Target file:** `@backend/src/personagent/infrastructure/tools/browser_tools.py`
(2,786 lines — second-largest backend god file)

**Target package:** `@backend/src/personagent/infrastructure/tools/browser_tools/`
(new directory; `__init__.py` re-exports `create_browser_tools`)

**Tests:**
- `@backend/tests/test_lightpanda_browser_tools.py` (integration)

Read `_protocol.md` first.

## Why this file is hard

`browser_tools.py` is a monolithic factory that creates 19 browser tool
definitions. Each tool is a `create_browser_*_tool()` function that returns
a `Tool` with validation and handler logic. The file also contains ~30
private helper functions for response normalization, content chunking,
permission checks, and argument validation.

The problems:
1. **19 tool factories** in one file — adding or modifying a tool requires
   reading 2,700+ lines of context.
2. **Shared helpers** are interleaved with tool definitions — changing a
   helper risks unintended side effects on unrelated tools.
3. **Mixed abstraction levels** — high-level tool orchestration sits next
   to low-level content chunking and URL normalization.

## Public contract that must be preserved

The file is consumed by:
- `infrastructure/tools/__init__.py` or DI wiring — calls `create_browser_tools(worker)`.

Public surface:
- `create_browser_tools(worker) -> list[Tool]` — **the only public function**.

All `create_browser_*_tool()` functions are effectively internal to
the factory. They can be moved freely as long as `create_browser_tools`
still returns the same list of `Tool` objects.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers to `helpers.py` | ✅ Merged | — | 920 lines → helpers.py; browser_tools.py → browser_tools/ package; factories.py 1,793 lines; 76 new tests; 0 regressions |
| 2 — Extract navigation tools | ⏳ Pending | — | |
| 3 — Extract interaction tools | ⏳ Pending | — | |
| 4 — Extract tab management tools | ⏳ Pending | — | |
| 5 — Extract content tools | ⏳ Pending | — | |
| 6 — Flatten factory into `factory.py` | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract private helpers to `browser_tools/helpers.py`

**What moves out (~500 lines):**

- `_simple_browser_control_tool` (1867–1903)
- `_prepare_browser_control_response` (1948–1969)
- `_prepare_extracted_content_response` (1999–2048)
- `_run_deduped_browser_extract` (2051–2070)
- `_cached_extracted_content_response` (2073–2111)
- `_summarize_element_map` (2114–2147)
- `_cache_page_content` (2150–2189)
- `_split_content_chunks` (2192–2213)
- `_curate_links` (2252–2275)
- `_normalize_browser_open_arguments` (2297–2355)
- `_validate_page_or_window_id` (2404–2425)
- `_merge_shared_browser_workspace_tabs` (2491–2521)
- `_workspace_browser_tabs` (2524–2546)
- `_normalize_browser_tab_for_tool` (2549–2588)
- `_resolve_browser_page_target` (2591–2644)
- `_error_type` (2711–2732)
- `_browser_action_permission` (2739–2763)
- Constants: `_DEFAULT_CHUNK_SIZE`, `_EXTRACT_INLINE_CONTENT_CHARS`, `_MAX_CHUNK_COUNT`, `_MAX_RETURNED_LINKS`

**Why first:** Pure functions. No tool definitions. Low risk.

**Risk:** Low.

**Tests:** 15+ cases covering response preparation, content chunking, URL normalization, permission logic.

### Slice 2 — Extract navigation tools to `browser_tools/navigation.py`

**What moves out (~450 lines):**

- `create_browser_search_tool` (159–225)
- `create_browser_open_tool` (228–349)
- `create_browser_extract_content_tool` (422–578)
- `create_browser_read_content_chunk_tool` (581–712)
- `create_browser_get_html_tool` (715–828)
- `create_browser_get_element_map_tool` (831–940)

**Collaborators:** `worker` (LightPandaBrowserWorker), helpers from slice 1.

**Risk:** Medium. These tools have complex validation and multi-step handlers.

**Tests:** 15+ cases covering search/open/extract happy paths and error handling.

### Slice 3 — Extract interaction tools to `browser_tools/interaction.py`

**What moves out (~450 lines):**

- `create_browser_click_tool` (943–1044)
- `create_browser_type_tool` (1047–1136)
- `create_browser_screenshot_tool` (1139–1211)
- `create_browser_scroll_tool` (1450–1498)
- `create_browser_script_tool` (1352–1447)
- `create_browser_read_console_tool` (1276–1349)
- `create_browser_wait_tool` (1651–1702)
- `create_browser_act_tool` (1705–1864)

**Risk:** Medium.

**Tests:** 15+ cases.

### Slice 4 — Extract tab management tools to `browser_tools/tab_management.py`

**What moves out (~250 lines):**

- `create_browser_list_tabs_tool` (352–419)
- `create_browser_close_tab_tool` (1214–1273)
- `create_browser_reload_tool` (1501–1537)
- `create_browser_history_tool` (1540–1587)
- `create_browser_switch_tab_tool` (1590–1648)

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 5 — Flatten remaining into `browser_tools/factory.py`

**What remains:**

- `create_browser_tools()` function — imports from all sub-modules and
  assembles the tool list.

**Risk:** Low — purely mechanical re-export.

**Tests:** 1 integration test verifying the returned tool list length and names.

## Anti-patterns specific to this file

- **Don't create tool classes** — the codebase uses factory functions
  that return `Tool` objects, not tool classes. Keep the pattern.
- **Don't split a single tool across files** — each `create_browser_*_tool`
  is a single unit. Move it whole or not at all.
- **Don't change tool names or schemas** — the `name` field in each
  Tool is part of the LLM contract.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_lightpanda_browser_tools.py -v
uv run pytest tests/unit/ -q
```
