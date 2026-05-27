# CHECKLIST: Fix `__init__.py` Logic Debt

> **Branch:** `fix/init-py-logic-debt`  
> **Worktree:** `.worktrees/fix-init-py-logic-debt`  
> **Scope:** `@backend/src/personagent/`  
> **Date:** 2026-05-27

---

## Phase 1: Move Classes Out of `__init__.py` (PRIORITY ORDER) ✅ DONE

- [x] **1.1** `infrastructure/browser/lightpanda/__init__.py` → `worker.py` (387 lines, highest risk)
- [x] **1.2** `infrastructure/browser/content/__init__.py` → `_extraction.py` (236 lines)
- [x] **1.3** `application/qa/service/__init__.py` → `service.py` + `mappers.py` (389 lines)
- [x] **1.4** `application/services/browser_cooperation/service/__init__.py` → `service.py` (361 lines)
- [x] **1.5** `infrastructure/llm/nvidia_nim_adapter/__init__.py` → `adapter.py` (456 lines)
- [x] **1.6** `domain/prompts/services/prompt_builder/__init__.py` → `prompt_builder.py` (432 lines)
- [x] **1.7** `infrastructure/settings/settings/__init__.py` → `settings.py` (376 lines, borderline)
- [x] **1.8** `application/team_chat/phases/loop/__init__.py` → `loop.py` (335 lines)
- [x] **1.9** `application/services/operational_memory/__init__.py` → `service.py` + `utils.py` (337 lines)
- [x] **1.10** `application/services/session_titles/__init__.py` → `service.py` (280 lines)
- [x] **1.11** `adapters/api/routes/workspace/git_pull_requests/__init__.py` → `routes.py` (192 lines)
- [x] **1.12** `domain/prompts/context_attachments/__init__.py` → `context_attachments.py` (149 lines)

### Phase 1 Validation
- [x] All 12 `__init__.py` files verified: 0 classes, 0 functions, only re-exports
- [x] All imports verified successfully
- [x] Test suite: 37 pre-existing failures, 2256 passed — zero regressions introduced
- [x] Commit: `930c42d` — "refactor: move business logic out of __init__.py files"

---

## Phase 2: Eliminate Worker Delegation Stubs (TODO)

After Phase 1, update all `self._w._method()` calls in sub-modules to use
`self._w.sub_module.method()` directly. This eliminates the need for delegation
methods on the worker and prevents future "lost logic" bugs.

**Remaining delegation stubs to eliminate:**
- [ ] `_evaluate_page` → `_browser_runtime.evaluate_page()`
- [ ] `_goto_page` → `_navigation.goto_page()`
- [ ] `_goto` → `_navigation.goto()`
- [ ] `_page_runtime` → `_browser_runtime.page_runtime()`
- [ ] `_is_lightpanda_page` → `_browser_runtime.is_lightpanda_page()`
- [ ] `_bounded_script_result` → `_browser_runtime.bounded_script_result()`
- [ ] `_cdp_command_for_page` → `_browser_runtime.cdp_command_for_page()`
- [ ] `_first_open_context_page` → `_browser_runtime.first_open_context_page()`
- [ ] `_connect_browser` → `_connection.connect_browser()`
- [ ] `_new_session_page` → `session_manager.new_session_page()`
- [ ] `_raw_runtime_evaluate_value` → `_cdp_runtime.raw_runtime_evaluate_value()`
- [ ] `_lightpanda_raw_cdp_command` → `_cdp_runtime.lightpanda_raw_cdp_command()`
- [ ] `_lightpanda_markdown` → `_markdown.lightpanda_markdown()`
- [ ] `_lightpanda_markdown_url` → `_markdown.lightpanda_markdown_url()`

---

## Phase 3: Enforce `__init__.py` Purity (TODO)

Add a lint rule or pre-commit check that flags `__init__.py` files containing
`class `, `def `, or `async def ` definitions (excluding mixin composition
classes with only `__init__`).
