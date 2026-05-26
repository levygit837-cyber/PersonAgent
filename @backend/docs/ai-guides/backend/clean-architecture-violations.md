# Known Clean Architecture Violations (Documented Exceptions)

## Rule

Application layer must NOT import from Infrastructure layer.

Dependency direction: `adapters → application → domain`

## Current Violations

| # | File | Imports From | Fix Strategy | Priority |
|---|------|-------------|--------------|----------|
| 1 | `application/use_cases/chat/media_policy.py` | `infrastructure.artifacts` | Create `domain/repositories/artifact_repository.py` port, inject implementation | High |
| 2 | `application/services/operational_memory/capture.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |
| 3 | `application/services/operational_memory/recall.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |
| 4 | `application/services/operational_memory/__init__.py` | `infrastructure.llm.embedding_adapter` + `infrastructure.persistence.operational_memory_repository` | Extract to domain ports; already uses lazy imports | Medium |
| 5 | `application/services/browser_cooperation/service/__init__.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 6 | `application/services/browser_cooperation/service/_mapping.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 7 | `application/services/browser_cooperation/service/_queries.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 8 | `application/services/browser_workspace/service.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 9 | `application/services/browser_workspace/serializers.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 10 | `application/qa/service/__init__.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 11 | `application/qa/service/_mappers.py` | `infrastructure.persistence.models` | Move ORM model usage to infrastructure layer or create DTOs | Low |
| 12 | `application/tools/orchestrator/_result_capping.py` | `infrastructure.artifacts` | Inject artifact repository port | High |
| 13 | `application/tools/runtime_config.py` | `infrastructure.artifacts` | Inject artifact repository port | High |

## Fixed Violations

| # | Fixed In | Description |
|---|----------|-------------|
| C1 | PR #207 | `application/use_cases/chat/tool_results.py` imported `canonical_args_hash` from `interfaces/api/action_approvals`. Moved to `domain/security/value_objects.py`. |

## Notes

- Violations 5–11 (ORM model imports) are pragmatic exceptions. Full isolation would require 4+ mapping layers with minimal business benefit. These may be accepted as documented exceptions indefinitely.
- Violations 2–4 use lazy imports (`from ... import` inside functions), which mitigates import-time coupling but does not eliminate the architectural violation.
- All violations are isolated to specific modules. No violation propagates to domain layer.
