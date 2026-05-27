# Known Clean Architecture Violations (Documented Exceptions)

## Rule

Application layer must NOT import from Infrastructure layer.

Dependency direction: `adapters → application → domain`

## Current Violations

| # | File | Imports From | Fix Strategy | Priority |
|---|------|-------------|--------------|----------|
| 2 | `application/services/operational_memory/capture.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |
| 3 | `application/services/operational_memory/recall.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |
| 4 | `application/services/operational_memory/__init__.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |

## Fixed Violations

| # | Fixed In | Description |
|---|----------|-------------|
| C1 | PR #207 | `application/use_cases/chat/tool_results.py` imported `canonical_args_hash` from `interfaces/api/action_approvals`. Moved to `domain/security/value_objects.py`. |
| 1 | Phase 5 | `application/use_cases/chat/messaging/media_policy.py` imported `infrastructure.artifacts`. Fixed by creating `application/ports/artifact_storage.py` port and injecting `LocalArtifactStorage` from adapters. |
| 5–7 | Phase 5 | Browser Cooperation ORM imports (`service/__init__.py`, `_mapping.py`, `_queries.py`). Fixed by extracting `BrowserCooperationRepository` port and `PostgresBrowserCooperationRepository` implementation. |
| 8–9 | Phase 5 | Browser Workspace ORM imports (`service.py`, `serializers.py`). Fixed by extracting `BrowserWorkspaceRepository` port and `PostgresBrowserWorkspaceRepository` implementation. |
| 10–11 | Phase 5 | QA ORM imports (`service/__init__.py`, `_mappers.py`). Fixed by extracting `QARepository` in infrastructure and rewriting `QASessionService` to depend on it. |
| 12–13 | Phase 5 | Tool result capping and runtime config imported `infrastructure.artifacts`. Fixed by injecting `ArtifactStoragePort` and removing `DEFAULT_ARTIFACT_ROOT` import from `runtime_config.py`. |

## Notes

- Violations 2–4 use lazy imports (`from ... import` inside functions), which mitigates import-time coupling but does not eliminate the architectural violation.
- All remaining violations are isolated to specific modules. No violation propagates to domain layer.
