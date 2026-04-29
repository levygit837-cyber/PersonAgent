# Backend Documentation

The backend is a FastAPI application organized around clean architecture:

```text
interfaces -> application -> domain
infrastructure -> application/domain ports
```

## Main Areas

| Area | Path | Responsibility |
| --- | --- | --- |
| API | `@backend/src/personagent/interfaces/api` | FastAPI app, routers, SSE/WebSocket adapters, and error mapping. |
| CLI | `@backend/src/personagent/interfaces/cli` | Typer/Rich commands for chat, serving, model status, and conversations. |
| Application | `@backend/src/personagent/application` | Use cases, services, jobs, state management, tools orchestration, and QA. |
| Domain | `@backend/src/personagent/domain` | Models, tool contracts, context models, exceptions, and repository ports. |
| Infrastructure | `@backend/src/personagent/infrastructure` | Config, persistence, LLM adapters, process manager, browser/tools, and external integrations. |

## Key Contracts

- API routes are mapped in [../api/README.md](../api/README.md).
- Structured errors are centralized in
  `@backend/src/personagent/interfaces/api/errors.py`.
- Backend lifecycle is owned by `lifespan()` in
  `@backend/src/personagent/interfaces/api/main.py`.
- Dependency construction is centralized in
  `@backend/src/personagent/interfaces/config/di_container.py`.
- Database migrations live in
  `@backend/src/personagent/infrastructure/persistence/migrations/`.

## Future Pages

Create focused backend pages as the subsystem evolves:

- `clean-architecture.md`
- `dependency-injection.md`
- `llm-providers.md`
- `tools-runtime.md`
- `persistence.md`
- `state-events.md`
- `error-handling.md`
