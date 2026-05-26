# Clean Architecture Violations & Known Smells

> Living document. Last updated: 2026-05-25 (post ADR-0022 Phase 2 migration).

---

## 1. Application → Infrastructure Runtime Imports

The application layer must not depend on the infrastructure layer per ADR-0001. The following files violate this rule at **runtime** (not `TYPE_CHECKING`):

| # | File | Imported Symbol(s) | Why It Violates | Planned Fix |
|---|------|-------------------|-----------------|-------------|
| 1 | `application/tools/runtime_config.py` | `DEFAULT_ARTIFACT_ROOT` from `infrastructure.persistence.artifacts` | Application reads infra artifact path directly | Extract artifact path to domain setting or port |
| 2 | `application/tools/orchestrator/_result_capping.py` | `DEFAULT_ARTIFACT_ROOT`, `safe_segment` from `infrastructure.persistence.artifacts` | Same as #1 | Same as #1 |
| 3 | `application/services/browser_workspace/serializers.py` | `BrowserAnnotationORM`, `BrowserTabORM`, `BrowserTimelineEventORM` from `infrastructure.persistence.models` | Application serializes infra ORM entities directly | Move ORM→DTO mapping to infrastructure layer |
| 4 | `application/services/browser_workspace/service.py` | `BrowserAnnotationORM`, `BrowserTabORM`, `BrowserTimelineEventORM`, `BrowserWorkspaceORM` from `infrastructure.persistence.models` | Application queries ORM models directly | Same as #3 |
| 5 | `application/qa/service/__init__.py` | `QACodeEdgeORM`, `QACodeNodeORM`, `QARequestRunORM`, `QARuntimeEventORM`, `QASessionORM` from `infrastructure.persistence.models` | Application owns QA business logic but imports ORM models | Extract repository port in domain; infra implements it |
| 6 | `application/qa/service/_mappers.py` | Same 5 QA ORM models from `infrastructure.persistence.models` | Mapper lives in application but maps infra ORM | Move mappers to infrastructure or use domain DTOs |
| 7 | `application/use_cases/chat/messaging/media_policy.py` | `store_bytes_artifact` from `infrastructure.persistence.artifacts` | Use case calls infra artifact storage directly | Add artifact storage port in domain; inject adapter |
| 8 | `application/services/browser_cooperation/service/__init__.py` | `BrowserCooperationEventORM` from `infrastructure.persistence.models` | Application service imports ORM model | Extract repository pattern |
| 9 | `application/services/browser_cooperation/service/_queries.py` | `BrowserCooperationEventORM`, `BrowserWorkspaceORM` from `infrastructure.persistence.models` | Application queries ORM directly | Same as #8 |
| 10 | `application/services/browser_cooperation/service/_mapping.py` | `BrowserCooperationEventORM` from `infrastructure.persistence.models` | Application maps ORM directly | Same as #8 |

**Status:** Pre-existing. Not introduced by ADR-0022 Phase 2. Scheduled for Phase 5 remediation.

---

## 2. Application → Infrastructure Imports (TYPE_CHECKING Only)

These are wrapped in `if TYPE_CHECKING:` and create **no runtime dependency**. They are acceptable by convention but noted for completeness.

| File | Imported Symbol(s) |
|------|-------------------|
| `application/services/operational_memory/capture.py` | `OpenAICompatibleEmbeddingAdapter`, `OperationalMemoryRepository` |
| `application/services/operational_memory/recall.py` | Same pair |
| `application/services/operational_memory/__init__.py` | Same pair |

---

## 3. Circular Import Loops (Parent ↔ Child Packages)

These work today because all access to the parent module is **deferred inside function bodies** (late binding). Any future refactor that moves an attribute access to module level will break them.

### 3.1 `adapters/api/routes/chat/` loop

```
chat/__init__.py  ──imports──▶  chat.completion
      ▲                          │
      └─── "import chat as _chat"┘
      (in completion/resolvers.py, completion/use_case.py, completion/routes.py,
       team_chat.py, models_listing.py, plan_approval.py, tool_approval.py)
```

**Accessed from children:** `_chat.get_db`, `_chat.get_container`, `_chat._load_conversation_for_decision`, `_chat._approve_pending_tool_call`, `_chat.resolve_model`, `_chat.resolve_context_workspace_root`, `_chat.load_team_memory_snapshot`, `_chat._team_trace_event_for_storage`, `_chat.persist_team_run_started`, `_chat.persist_team_run`, `_chat.persist_team_blackboard_event`, `_chat.persist_team_memory_snapshot`

**Root cause:** Children re-import the parent to access siblings' public API instead of importing siblings directly.

**Fix:** Move `get_db` and `get_container` to `chat/deps.py` (already created). Update the 7 child modules to import directly from `chat.deps` and sibling modules instead of via `_chat`.

### 3.2 `adapters/api/routes/sessions/` loop

```
sessions/__init__.py  ──imports──▶  sessions.browser.viewport
      ▲                              │
      └─── "import sessions as _sessions"┘
      (in browser/viewport.py, browser/interaction.py, panel/panel.py,
       workspace/cooperation.py, workspace/data.py, workspace/infra.py)
```

**Accessed from children:** `_sessions.get_db`, `_sessions.get_container`, `_sessions.DB_SESSION_DEPENDENCY`, `_sessions._load_conversation`, `_sessions._save_conversation`, `_sessions._coerce_dict`, `_sessions._coerce_list`, `_sessions._now_iso`, `_sessions._safe_event_source`, `_sessions._resolve_optional_workspace`, `_sessions._browser_worker`

**Root cause:** Same pattern as 3.1. Children reach up to parent to access sibling exports and shared deps.

**Fix:** Move `get_db`, `get_container`, `DB_SESSION_DEPENDENCY` to `sessions/deps.py` (already created). Move shared helpers (`_load_conversation`, `_save_conversation`, etc.) to a `sessions/common.py` or keep them in `panel/helpers.py` and import directly. Update the 6 child modules.

**Status:** Documented. Not scheduled for immediate fix due to scope (13 files). Safe to leave while all access is late-bound. Priority: medium.

---

## 4. Other Known Smells (Non-CA)

| Smell | Location | Severity | Notes |
|-------|----------|----------|-------|
| God module | `application/use_cases/chat/helpers.py` | Medium | Imported by 9+ sibling modules. Consider extracting shared DTOs to `chat/models.py`. |
| Over-exporting | `infrastructure/tools/browser/building/__init__.py` | Low | Re-exports 48 private names from 5 sibling modules. The 5 modules total ~492 lines; the `__init__.py` is 99 lines of glue. Consider merging `_utils.py` + `_arguments.py` into `_building.py`. |
| Missing re-export | `application/services/session_titles/__init__.py` | Low | `SessionTitleResult` is defined in `__init__.py` and imported by `cache.py`. Works, but splitting into a dedicated `models.py` would be cleaner. |
