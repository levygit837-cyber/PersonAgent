# Architecture Debt: `__init__.py` Business Logic & Lost Decomposition Logic

> **Created:** 2026-05-27
> **Status:** Active — 12 files flagged, 3 critical bugs fixed, more refactoring needed
> **Scope:** `@backend/src/personagent/`

---

## Problem Statement

`__init__.py` files should only contain re-exports (`from ... import ...`, `__all__`).
12 files in the codebase contain real business logic (class definitions, function definitions,
significant control flow). This creates ambiguity about where code lives and makes
decomposition fragile — as proven by the 3 critical bugs found from the lightpanda
decomposition where callers referenced methods that no longer existed.

---

## Part 1: Lost Logic Bugs (Fixed 2026-05-27)

Three critical bugs were found during the lightpanda decomposition (commit `b49b544`).
Slice 17 removed backward-compat delegation stubs from the worker but didn't update
all callers in the sub-modules.

### Bug 1: Garbled attribute in `_acquisition.py` (CRITICAL)

**File:** `infrastructure/browser/session_manager/_acquisition.py`, line 31

```python
# BROKEN (truncated during edit):
cached_results = self._w.d

# FIXED:
cached_results = self._w.search_result_cache.latest_cached_search_results(conversation_id)
```

**Impact:** Every session reuse (second+ request in a conversation) would crash with
`AttributeError: 'LightPandaBrowserWorker' object has no attribute 'd'`.

### Bug 2: 10 missing method calls across 6 files (CRITICAL)

Removed delegation stubs and their callers:

| File | Broken call | Fixed to |
|------|------------|----------|
| `content/__init__.py` (×4) | `self._w._resolve_content_target(...)` | `self._w.session_manager.resolve_content_target(...)` |
| `content/_target.py` | `self._w._is_session_page_alias(...)` | `self._w.session_manager.is_session_page_alias(...)` |
| `content/_target.py` | `self._w._page_is_open(...)` | `self._w.session_manager.page_is_open(...)` |
| `content/_target.py` (×2) | `self._w._preferred_session_page(...)` | `self._w.session_manager.preferred_session_page(...)` |
| `view_actions/_act.py` (×4) | `self._w._element_target(...)` | `self._w.element_helpers.element_target(...)` |
| `view_actions/_act.py` | `self._w._action_context_for_element(...)` | `self._w.element_helpers.action_context_for_element(...)` |
| `view_actions/_act.py` | `self._w._upload_files(...)` | `self._w.element_helpers.upload_files(...)` |
| `view_actions/_act.py` | `self._w._wait_for_page_load_complete(...)` | `self._w.page_helpers.wait_for_page_load_complete(...)` |
| `view_actions/_pointer.py` (×3) | `self._w._preferred_session_page(...)` | `self._w.session_manager.preferred_session_page(...)` |
| `view_actions/_pointer.py` (×2) | `self._w._set_page_viewport(...)` | `self._w.element_helpers.set_page_viewport(...)` |
| `view_actions/_pointer.py` (×2) | `self._w._wait_for_page_load_complete(...)` | `self._w.page_helpers.wait_for_page_load_complete(...)` |
| `view_actions/_navigation.py` (×2) | `self._w._preferred_session_page(...)` | `self._w.session_manager.preferred_session_page(...)` |
| `page/lifecycle.py` | `self._w._is_session_page_alias(...)` | `self._w.session_manager.is_session_page_alias(...)` |

**Impact:** `BrowserAct`, `BrowserExtractContent`, `BrowserGetHtml`, `BrowserClick`,
`BrowserScroll`, `BrowserReload`, `BrowserHistory` — all broken with `AttributeError`.

### Bug 3: `__init__.py` anti-pattern (Root Cause)

The lightpanda decomposition used `self._w = worker` (whole worker reference) instead
of explicit dependency injection. This made every sub-module depend on the worker's
full API surface, so removing any method from the worker broke callers silently.

Other decomposed packages (`chat_completion/`, `team_chat/`) used proper constructor
injection and had zero similar issues.

---

## Part 2: `__init__.py` Files with Business Logic

### Flagged Files (12 files, >50 lines with logic)

#### 1. `infrastructure/llm/nvidia_nim_adapter/__init__.py` — 456 lines

- **Class:** `NvidiaNimAdapter(LLMBackendRepository)`
- **Methods:** `chat_completion`, `chat_completion_stream`, `health_check`, `get_model_info`,
  `list_models`, `_build_payload`, `_parse_stream_chunk`, `_normalize_model`, etc.
- **Logic:** HTTP client lifecycle, retry logic (tenacity), SSE streaming parser, model caching
- **Fix:** Move class to `adapter.py`, keep `__init__.py` as `from .adapter import NvidiaNimAdapter`

#### 2. `domain/prompts/services/prompt_builder/__init__.py` — 432 lines

- **Class:** `PromptBuilder`
- **Methods:** `build` (async, ~80 lines), `_with_frontloaded_agent_sections`,
  `_prompt_tool_names`, `_resolve_sections`, `_assemble_system_prompt`, `_resolve_profile`
- **Logic:** Prompt section assembly, caching with SHA256 scopes, async resolution
- **Fix:** Move class to `prompt_builder.py`, keep `__init__.py` as re-export

#### 3. `application/qa/service/__init__.py` — 389 lines

- **Class:** `QASessionService`
- **Function:** `_session_data_from_orm()` (ORM mapper)
- **Methods:** `create_session`, `index_session`, `execute_request`, `graph_response`,
  `list_events`, `context_response`, `_get_session`, `_persist_events`, `_runtime_edges`
- **Logic:** Full CRUD service, worktree creation, ASGI test client, runtime tracing
- **Fix:** Move class to `service.py`, move `_session_data_from_orm` to `mappers.py`,
  keep `__init__.py` as re-export

#### 4. `infrastructure/settings/settings/__init__.py` — 376 lines

- **Class:** `Settings(BaseSettings, ...mixins)`
- **Logic:** ~100+ Pydantic `Field` declarations, `field_validator` methods
- **Fix:** Borderline acceptable (Pydantic convention). Could move to `settings.py` + re-export.

#### 5. `infrastructure/browser/lightpanda/__init__.py` — 387 lines

- **Class:** `LightPandaBrowserWorker`
- **Logic:** `__init__` wiring ~20 sub-modules, `warmup()`, `close()`, ~30 delegation methods
- **Fix:** Move class to `worker.py`, keep `__init__.py` as re-export. The delegation
  methods are pure boilerplate that should be eliminated by having callers use
  sub-modules directly (as done in the Bug 2 fixes above).

#### 6. `application/services/browser_cooperation/service/__init__.py` — 361 lines

- **Class:** `BrowserCooperationService`
- **Methods:** `set_cooperation`, `ingest_events`, `record_canonical_event`,
  `get_snapshot`, `resolve_proposal`
- **Logic:** Event normalization, deduplication, cooperation state management
- **Fix:** Move class to `service.py`, keep `__init__.py` as re-export

#### 7. `application/team_chat/phases/loop/__init__.py` — 335 lines

- **Class:** `TeamChatPhaseLoop`
- **Methods:** `run` (async generator, ~150 lines), `_get_or_create_conversation`,
  `_refresh_session_title`
- **Logic:** Complex async orchestration: execution → debate → consensus → synthesis
- **Fix:** Move class to `loop.py`, keep `__init__.py` as re-export

#### 8. `application/services/operational_memory/__init__.py` — 337 lines

- **Class:** `OperationalMemoryService`
- **Function:** `project_slug_from_workspace()` (utility)
- **Methods:** `capture_user_message`, `capture_assistant_message`, `capture_tool_result`,
  `recall_for_prompt`, `recall_package_for_prompt`, `status`, `process_outbox_message`
- **Fix:** Move class to `service.py`, move utility to `utils.py`, keep `__init__.py` as re-export

#### 9. `application/services/session_titles/__init__.py` — 280 lines

- **Class:** `SessionTitleService(_SessionTitleServiceHelpersMixin)`
- **Methods:** `refresh_title`, `verify_all`, `refresh_conversations`, `maybe_repair_duplicate_titles`
- **Logic:** LLM-based title generation, uniqueness checking, batch processing
- **Fix:** Move class to `service.py`, keep `__init__.py` as re-export

#### 10. `infrastructure/browser/content/__init__.py` — 236 lines

- **Class:** `BrowserContent(...mixins)`
- **Methods:** `extract_content` (~80 lines), `get_html` (~70 lines)
- **Logic:** Page resolution, markdown extraction orchestration, truncation
- **Fix:** Move `extract_content` and `get_html` to a new `_extraction.py` mixin,
  keep `__init__.py` as mixin composition + re-export only

#### 11. `adapters/api/routes/workspace/git_pull_requests/__init__.py` — 192 lines

- **Function:** `register_git_pr_routes(router)`
- **Logic:** 4 inline FastAPI endpoint handlers
- **Fix:** Move handlers to `routes.py`, keep `__init__.py` as re-export

#### 12. `domain/prompts/context_attachments/__init__.py` — 149 lines

- **Class:** `ResolvedContextAttachments` (frozen dataclass)
- **Function:** `resolve_context_attachments()` — validation + dispatch (9 attachment types)
- **Fix:** Move dataclass and function to `context_attachments.py`, keep `__init__.py` as re-export

### Acceptable Files (3 files, <50 lines with logic)

These use the mixin composition pattern — the `__init__.py` IS the class definition point:

| File | Lines | Pattern |
|------|-------|---------|
| `browser/actions/__init__.py` | 36 | `BrowserActions(_InteractionMixin, _CaptureMixin, ...)` |
| `browser/session_manager/__init__.py` | 28 | `BrowserSessionManager(...mixins)` |
| `browser/view_actions/__init__.py` | 36 | `BrowserViewActions(_NavigationMixin, _PointerMixin, _ActMixin)` |

These are fine — the class only has `__init__` storing `self._w = worker`.

---

## Part 3: Refactoring Strategy

### Phase 1: Move classes out of `__init__.py` (12 files)

For each flagged file:
1. Create a new module (e.g., `adapter.py`, `service.py`, `worker.py`)
2. Move the primary class/function to the new module
3. Update `__init__.py` to only re-export: `from .module import ClassName`
4. Run tests to verify no breakage

**Priority order** (by risk — files with active callers first):
1. `lightpanda/__init__.py` (387 lines) — highest risk, most callers
2. `content/__init__.py` (236 lines) — actively being fixed
3. `qa/service/__init__.py` (389 lines) — recently refactored in Phase 5
4. `browser_cooperation/service/__init__.py` (361 lines) — recently refactored
5. Remaining 8 files — lower risk

### Phase 2: Eliminate worker delegation stubs

After Phase 1, update all `self._w._method()` calls in sub-modules to use
`self._w.sub_module.method()` directly. This eliminates the need for delegation
methods on the worker and prevents future "lost logic" bugs.

**Remaining delegation stubs to eliminate:**
- `_evaluate_page` → `_browser_runtime.evaluate_page()`
- `_goto_page` → `_navigation.goto_page()`
- `_goto` → `_navigation.goto()`
- `_page_runtime` → `_browser_runtime.page_runtime()`
- `_is_lightpanda_page` → `_browser_runtime.is_lightpanda_page()`
- `_bounded_script_result` → `_browser_runtime.bounded_script_result()`
- `_cdp_command_for_page` → `_browser_runtime.cdp_command_for_page()`
- `_first_open_context_page` → `_browser_runtime.first_open_context_page()`
- `_connect_browser` → `_connection.connect_browser()`
- `_new_session_page` → `session_manager.new_session_page()`
- `_raw_runtime_evaluate_value` → `_cdp_runtime.raw_runtime_evaluate_value()`
- `_lightpanda_raw_cdp_command` → `_cdp_runtime.lightpanda_raw_cdp_command()`
- `_lightpanda_markdown` → `_markdown.lightpanda_markdown()`
- `_lightpanda_markdown_url` → `_markdown.lightpanda_markdown_url()`

### Phase 3: Enforce `__init__.py` purity

Add a lint rule or pre-commit check that flags `__init__.py` files containing
`class `, `def `, or `async def ` definitions (excluding mixin composition
classes with only `__init__`).

---

## References

- ADR-0022: Folder structure principles
- Commit `b49b544`: "refactor(browser): complete Phase 3 lightpanda decomposition - remove backward-compat stubs"
- Commit `ceb279a`: "refactor(browser): decompose lightpanda.py into lightpanda/ package"
- `docs/ai-guides/backend/clean-architecture-violations.md`: Existing violation inventory
