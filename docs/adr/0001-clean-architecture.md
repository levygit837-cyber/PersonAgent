# ADR 0001: Clean Architecture (Domain -> Application -> Infrastructure -> Interfaces)

Date: 2025-06-10
Status: Accepted

## Context

PersonAgent started as a monolithic script and quickly accumulated technical debt: domain logic mixed with HTTP handlers, database queries scattered across use cases, and provider-specific code leaking into the orchestration layer. We needed a boundary discipline that would let us swap persistence, add new LLM providers, and test business rules without spinning up a database or a browser.

## Decision

Adopt Clean Architecture with four explicit layers and a strict dependency rule: code can only depend inward.

```text
interfaces -> application -> domain
infrastructure -> application/domain ports
```

- **Domain** (`@backend/src/personagent/domain`): entities, value objects, tool contracts, prompt sections, repository ports, and the exception hierarchy. No external dependencies.
- **Application** (`@backend/src/personagent/application`): use cases (chat completion, memory recall, context build), services (session panel, operational memory, browser cooperation), tool orchestration, and QA. Depends only on domain ports.
- **Infrastructure** (`@backend/src/personagent/infrastructure`): concrete adapters for PostgreSQL persistence, LLM providers, browser workers, tool implementations, and config/settings. Implements domain ports.
- **Interfaces** (`@backend/src/personagent/interfaces`): FastAPI routers, SSE/WebSocket endpoints, CLI commands, and the DI container. Translates transport concerns into application use-case calls.

Repository ports in the domain layer (`ConversationRepository`, `LLMBackendRepository`, `MemoryRepository`) are implemented by infrastructure classes (`PostgresConversationRepository`, `LlamaCppAdapter`, `FileSystemMemoryRepository`).

## Consequences

- **Easier**: unit-test business logic with in-memory fakes; swap PostgreSQL for another store by re-implementing a port; add a new LLM provider without touching use cases.
- **Harder**: more boilerplate (adapters, DTOs, mappers); new developers must learn the boundary discipline.
- **Risk**: circular dependencies can appear if infrastructure imports leak upward. We enforce this with manual code review and a grep-based CI check.
- **Out of scope**: microservices, event sourcing, or CQRS.

## Alternatives Considered

- **FastAPI standard layout**: controllers call ORM models directly. Rejected because it couples domain rules to SQLAlchemy schema changes.
- **Hexagonal architecture (full)**: too many ports and adapters for a team of one. We kept the spirit but simplified to four concrete layers.

## Validation

- `@backend/tests/unit/test_chat_completion.py` exercises `ChatCompletionUseCase` with fake repositories.
- `@backend/tests/test_api_security.py` validates that interface routers never import SQLAlchemy or LLM adapters directly.
