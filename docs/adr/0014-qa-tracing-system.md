# ADR 0014: QA Tracing with Static Code Graph and Runtime ASGI Execution

Date: 2025-06-10
Status: Accepted

## Context

Debugging a FastAPI backend requires understanding how a request travels through controllers, services, and repositories. Static code analysis alone misses runtime call paths; runtime tracing alone misses structural relationships.

## Decision

Build a QA subsystem that combines a static code graph with a live runtime tracer, exposed via dedicated API routes and SSE streams.

**Static code graph**
- `PythonCodeIndexer` parses the backend source tree and produces `QACodeGraph` (nodes and edges).
- Nodes: modules, controllers, services, repositories, functions, endpoints.
- Edges: imports, calls, inheritance, runtime call sequences.
- Persisted in PostgreSQL (`qa_code_nodes`, `qa_code_edges`).

**Runtime tracer**
- `PythonRuntimeTracer` uses `sys.monitoring` (Python 3.12+) when available, falling back to `sys.settrace`.
- Captures `call`, `return`, `line`, and `exception` events within the backend source tree.
- Excludes QA-internal paths, site-packages, and virtual environments.
- Events are published to an in-memory `QARuntimeEventBus` and persisted to `qa_runtime_events`.

**ASGI execution**
- QA requests are executed against the live FastAPI app via `ASGITransport` (`httpx`), so the traced code runs in the same process.
- Recursive QA execution (paths starting with `/qa`) is blocked.

**SSE stream**
- `GET /qa/sessions/{id}/stream` yields real-time runtime events.

## Consequences

- **Easier**: request-to-code mapping is automatic; no manual instrumentation needed; works with existing tests.
- **Harder**: `sys.monitoring` has a performance overhead; `sys.settrace` is slower and changes async behavior slightly.
- **Risk**: tracing can capture sensitive request payloads; redaction is applied to headers and bodies before persistence.
- **Out of scope**: distributed tracing across multiple processes; frontend JavaScript tracing.

## Alternatives Considered

- **OpenTelemetry + Jaeger**: rejected to avoid external dependencies and keep everything in-process and local.
- **Manual decorator-based tracing**: rejected because it requires modifying every function.

## Validation

- `@backend/tests/integration/test_qa.py` creates a session, indexes code, runs a traced request, and verifies the resulting graph and events.
