# Handoff: ADR-0022 Phase 5 — CA Violation Remediation

> Session handoff document. Created: 2026-05-25.
> **Status:** Phase 5 in progress. Group A (Artifacts) partially implemented but broke 41 tests.

---

## ✅ What Was Completed

### Phase 1 — Extract `canonical_args_hash` (merged via PR #207)
- Moved `canonical_args_hash` from `interfaces/api/action_approvals.py` → `domain/security/value_objects.py`
- Fixed cross-layer import violation

### Phase 2 — Massive Backend Structural Migration (merged via PR #208)
- `interfaces/` → `adapters/` (153 import sites)
- `infrastructure/config/` → `infrastructure/settings/`
- Flattened 10 single-file folders
- Created 2 domain bounded contexts: `domain/conversation/`, `domain/llm_backend/`
- Created 8 thematic sub-packages for >7-file directories
- Moved `artifacts.py` → `infrastructure/persistence/artifacts.py`
- Moved `security.py` → `adapters/api/middleware/auth.py`
- 2114 unit tests pass, 43 integration tests pass
- 1 pre-existing failure: `test_agent_state_overlays_are_compact`

### Phase 3 — Thermo-Nuclear Code Review
- Fixed 3 CRITICAL issues:
  1. `session_titles/cache.py` — `SessionTitleResult` under `TYPE_CHECKING` but used at runtime
  2. `streaming/__init__.py` — 344 lines of implementation moved to `executor.py`
  3. `blackboard/` — missing `__init__.py` added
- Created `docs/ai-guides/backend/clean-architecture-violations.md`

### Phase 4 — Architecture Enforcement (merged to main)
- Disabled GitHub Actions (billing issue) — moved `ci.yml` → `workflows-disabled/`
- Created `@backend/scripts/check_folder_principles.py` — baseline-aware ADR-0022 validator
- Added pre-commit hook for automatic enforcement
- 8 pre-existing violations in baseline

---

## 🔴 CURRENT STATE: Phase 5 — CA Violation Remediation (IN PROGRESS)

We are eliminating **10 runtime application→infrastructure imports**.

### Group A: Artifacts (3 violations) — PARTIALLY DONE, 41 TESTS BROKEN

**Files modified but tests failing:**

| File | Change | Status |
|------|--------|--------|
| `application/ports/artifact_storage.py` | **NEW** — `ArtifactStoragePort` Protocol with `persist_tool_result()` and `store_bytes()` | ✅ |
| `infrastructure/persistence/artifacts.py` | **NEW** — `LocalArtifactStorage` class implementing the port | ✅ |
| `application/tools/runtime_config.py` | Removed `DEFAULT_ARTIFACT_ROOT` import; default now `None` | ✅ |
| `application/tools/orchestrator/_result_capping.py` | Uses `_artifact_storage.persist_tool_result()` instead of direct infra | ✅ |
| `application/tools/orchestrator/_core.py` | `ToolOrchestrator` now accepts `artifact_storage` parameter | ✅ |
| `application/use_cases/chat/messaging/media_policy.py` | Uses `self._artifact_storage.store_bytes()` instead of `store_bytes_artifact` | ✅ |
| `application/use_cases/chat/tooling/tool_runtime.py` | `ToolRuntime` accepts and passes `artifact_storage` to `ToolOrchestrator` | ✅ |
| `application/use_cases/chat_completion.py` | Accepts `artifact_storage`, passes to `ToolRuntime` and `MediaPolicyHandler` | ✅ |
| `adapters/composition/infrastructure/_tools.py` | Added `get_artifact_storage()` → `LocalArtifactStorage()` | ✅ |
| `adapters/api/routes/chat/completion/use_case.py` | Passes `artifact_storage=container.get_artifact_storage()` | ✅ |
| `adapters/cli.py` | Passes `artifact_storage=container.get_artifact_storage()` | ✅ |
| `application/team_chat/orchestration/agent_turn_runner.py` | Accepts and passes `artifact_storage` to `ToolOrchestrator` | ✅ |
| `application/team_chat/orchestration/orchestrator.py` | Accepts and passes `artifact_storage` to `AgentTurnRunner` | ✅ |
| `adapters/api/routes/chat/team_chat.py` | Passes `artifact_storage=container.get_artifact_storage()` | ✅ |

**Why tests fail:**
- `MediaPolicyHandler` now **requires** `artifact_storage` parameter — tests instantiate without it
- `ToolOrchestrator` now **requires** `artifact_storage` parameter — tests instantiate without it
- `ToolRuntimeConfig.from_values()` no longer falls back to `DEFAULT_ARTIFACT_ROOT` — tests may rely on old default

**Fix strategy:**
1. Make `artifact_storage` **optional** (`| None = None`) in all constructors
2. When `None`, fall back to creating a `LocalArtifactStorage()` inline (temporary bridge)
3. OR: update all test files to pass a mock/fake `artifact_storage`

**Preferred approach:** Make `artifact_storage` optional with fallback to `LocalArtifactStorage()` in the constructor. This is the minimal change that restores test compatibility while keeping the architectural separation.

---

### Group B: Browser Workspace ORM (2 violations) — NOT STARTED

**Files to fix:**
- `application/services/browser_workspace/serializers.py` — imports `BrowserAnnotationORM`, `BrowserTabORM`, `BrowserTimelineEventORM`
- `application/services/browser_workspace/service.py` — imports 4 ORM models + SQLAlchemy

**Strategy:** Extract repository pattern.
1. Create `domain/browser_workspace/repositories.py` with abstract `BrowserWorkspaceRepository`
2. Create `infrastructure/persistence/browser_workspace_repository.py` with `PostgresBrowserWorkspaceRepository`
3. Move `serializers.py` mappers to infrastructure
4. Rewrite `BrowserWorkspaceService` to depend on repository port instead of `AsyncSession`

---

### Group C: QA ORM (2 violations) — NOT STARTED

**Files to fix:**
- `application/qa/service/__init__.py` — imports 5 QA ORM models
- `application/qa/service/_mappers.py` — imports 5 QA ORM models

**Strategy:** Extract repository pattern.
1. Create `infrastructure/persistence/qa_repository.py` with `QARepository` class
2. Move `_mappers.py` → `infrastructure/persistence/_qa_mappers.py`
3. Rewrite `QASessionService` to depend on `QARepository` instead of `AsyncSession`

---

### Group D: Browser Cooperation ORM (3 violations) — NOT STARTED

**Files to fix:**
- `application/services/browser_cooperation/service/__init__.py` — imports `BrowserCooperationEventORM`
- `application/services/browser_cooperation/service/_queries.py` — imports 2 ORM models
- `application/services/browser_cooperation/service/_mapping.py` — imports `BrowserCooperationEventORM`

**Strategy:** Extract repository pattern.
1. Create `application/services/browser_cooperation/ports.py` with `BrowserCooperationRepository` ABC
2. Create `infrastructure/persistence/browser_cooperation_repository.py` with `PostgresBrowserCooperationRepository`
3. Move `_queries.py` logic into repository
4. Move `_mapping.py` → `infrastructure/persistence/_browser_cooperation_mapping.py`
5. Rewrite `BrowserCooperationService` to depend on repository port

---

## 📋 NEXT STEPS (in order)

### Step 1: Fix Group A test regressions
**Goal:** Make `artifact_storage` optional everywhere so tests pass.

Files to modify:
- `application/tools/orchestrator/_core.py` — `artifact_storage: ArtifactStoragePort | None = None`
- `application/tools/orchestrator/_result_capping.py` — when `None`, skip persistence
- `application/use_cases/chat/messaging/media_policy.py` — `artifact_storage: ArtifactStoragePort | None = None`
- `application/use_cases/chat/tooling/tool_runtime.py` — `artifact_storage: ArtifactStoragePort | None = None`
- `application/team_chat/orchestration/agent_turn_runner.py` — `artifact_storage: ArtifactStoragePort | None = None`
- `application/use_cases/chat_completion.py` — `artifact_storage: ArtifactStoragePort | None = None`

**Verification:** `uv run pytest tests/unit/ -q` must show only the pre-existing `test_agent_state_overlays_are_compact` failure.

### Step 2: Implement Group B — Browser Workspace Repository
**Goal:** Remove ORM imports from `application/services/browser_workspace/`.

**Verification:** `grep "from personagent.infrastructure.persistence.models" src/personagent/application/services/browser_workspace/` should return nothing.

### Step 3: Implement Group C — QA Repository
**Goal:** Remove ORM imports from `application/qa/service/`.

**Verification:** `grep "from personagent.infrastructure.persistence.models" src/personagent/application/qa/service/` should return nothing.

### Step 4: Implement Group D — Browser Cooperation Repository
**Goal:** Remove ORM imports from `application/services/browser_cooperation/service/`.

**Verification:** `grep "from personagent.infrastructure.persistence.models" src/personagent/application/services/browser_cooperation/service/` should return nothing.

### Step 5: Final validation
- `uv run ruff check src/ tests/` — clean
- `uv run pytest tests/unit/ -q` — only pre-existing failure
- `uv run pytest tests/integration/ -q` — all pass
- `python3 scripts/check_folder_principles.py` — no new violations
- Update `docs/ai-guides/backend/clean-architecture-violations.md` — mark fixed items

### Step 6: Commit and merge
- Commit Phase 5 changes
- Update PR or create new PR for Phase 5
- Merge to main

---

## 🚀 Prompt for Next Session

Copy and paste this into the new session:

```
Continue Phase 5 of ADR-0022: CA violation remediation.

Current state: Group A (Artifacts) is partially implemented but broke 41 tests.
The problem: artifact_storage was made a required parameter in MediaPolicyHandler,
ToolOrchestrator, and ToolRuntime, but existing tests instantiate these classes
without passing artifact_storage.

Step 1: Make artifact_storage optional everywhere (| None = None) with inline
fallback to LocalArtifactStorage() when None. This restores test compatibility.

Then continue with Groups B, C, D following the strategies documented in
HANDOFF.md. After all groups are done, run full validation and commit.

Read HANDOFF.md first for full context.
```

---

## 🔗 Key References

- `docs/adr/0022-folder-structure-principles.md` — ADR
- `docs/ai-guides/backend/clean-architecture-violations.md` — violation inventory
- `@backend/scripts/check_folder_principles.py` — enforcement script
- `@backend/scripts/check_folder_principles_baseline.json` — current baseline
