# ADR 0006: Manual Singleton DI Container (No Framework)

Date: 2025-06-10
Status: Accepted

## Context

Clean architecture requires wiring infrastructure adapters into application use cases without letting the use cases know the concrete classes. A DI container is needed, but adding a heavy framework (e.g., `dependency-injector`, `injector`, or `fastapi.Depends` auto-wiring) would introduce unnecessary dependencies and magic.

## Decision

Implement a **manual, singleton DI container** (`DIContainer`) in `@backend/src/personagent/interfaces/config/di_container.py`.

**Design**
- Single class with lazy-initialized attributes (`_llm_backends`, `_tool_registry`, `_lightpanda_browser_worker`, etc.).
- Factory methods for per-request or per-backend objects (`create_build_context_use_case`, `create_prompt_context_analyzer`).
- Singleton accessors for long-lived services (`get_container()` returns a module-level singleton; `reset_container()` for tests).
- A separate `lifespan()` context manager for CLI usage.

**Wiring example**
```python
container = get_container()
backend = container.get_llm_backend("llama")
use_case = ChatCompletionUseCase(
    conversation_repo=await container.get_conversation_repo(session),
    llm_backend=backend,
    tool_registry=container.get_tool_registry(),
    ...
)
```

## Consequences

- **Easier**: explicit wiring is grep-able, debuggable, and has zero framework lock-in; tests can replace any singleton by calling `reset_container()`.
- **Harder**: adding a new cross-cutting concern means editing `DIContainer` directly; no auto-discovery or decorator-based registration.
- **Risk**: the file grows large (~600 lines); merge conflicts are possible. We mitigate by grouping factories into sections (LLM, Tools, Memory, Browser, etc.).
- **Out of scope**: scopes (request, transient, singleton) beyond the two we use; AOP or interceptors.

## Alternatives Considered

- **FastAPI `Depends` with auto-wiring**: rejected because it ties the container to the web framework; CLI commands and background jobs would need duplicate wiring.
- **`dependency-injector` library**: rejected to avoid a runtime dependency and configuration DSL.

## Validation

- All backend tests call `reset_container()` in fixtures to guarantee isolation.
- `create_app()` resolves the container in `lifespan()` and initializes DB + llama-server + memory scheduler.
