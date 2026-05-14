# PersonAgent Documentation

This directory is the central documentation hub for PersonAgent. Keep durable
project knowledge here instead of scattering architectural notes across feature
READMEs.

## Start Here

- [Application overview](architecture/overview.md) explains the runtime shape,
  major modules, data flow, and ownership boundaries.
- [Application documentation](app/README.md) maps the product subsystems and
  desktop/backend flows.
- [Backend documentation](backend/README.md) maps backend layers and contracts.
- [API reference](api/README.md) maps the active FastAPI surface used by the
  Electron desktop app and backend tests.
- [Runtime documentation](runtime/README.md) covers local llama.cpp/TurboQuant,
  provider ownership, and configuration.
- [ADR index](adr/README.md) stores architecture decisions and the template for
  future records. **All 21 ADRs (0001–0021) are now complete.**
- [Development guide](development/README.md) collects local setup, validation,
  and documentation maintenance practices.
- [Testing documentation](testing/README.md) maps backend, desktop, and live
  validation layers.
- [Operations documentation](operations/README.md) collects health checks,
  release review, and diagnostics.
- [Browser Workspace](browser-workspace.md) documents the browser runtime and
  session-panel control contract.

## Documentation Map

```text
docs/
├── README.md                 # Documentation hub
├── api/
│   └── README.md             # FastAPI endpoint and transport contracts
├── app/
│   ├── README.md             # Product subsystems and desktop/backend flows
│   ├── architecture.md         # Electron + React + Vite
│   ├── chat.md                 # Chat flow, SSE, plan mode
│   ├── chat-store.md           # Frontend chat state
│   ├── api-client.md           # API consumption
│   ├── config.md               # Configuration hierarchy
│   ├── error-handling.md       # Error hierarchy and SSE
│   ├── memory.md               # Three-layer memory
│   ├── prompt-system.md        # Dynamic prompt building
│   ├── qa.md                   # QA tracing
│   ├── session.md              # Session lifecycle
│   ├── skills.md               # Skill discovery and injection
│   ├── state-events.md         # SSE state invalidation
│   └── team.md                 # Team mode multi-agent
├── architecture/
│   └── overview.md           # Application architecture and data flow
├── adr/
│   ├── README.md             # ADR process, status values, and template
│   └── 0001-0021.md          # Architecture Decision Records (complete)
├── backend/
│   ├── README.md             # Backend layers and contract ownership
│   ├── clean-arch.md           # Clean architecture guide
│   ├── di.md                   # Dependency injection
│   ├── llm-providers.md        # LLM provider adapters
│   ├── persistence.md          # PostgreSQL + pgvector
│   └── tools-runtime.md        # Tool registry and orchestration
├── development/
│   └── README.md             # Setup, tests, and doc maintenance
├── operations/
│   ├── README.md             # Health checks, release review, diagnostics
│   ├── diagnostics.md          # Troubleshooting commands
│   ├── mitigations.md          # Risk mitigations
│   └── release-checklist.md    # Release steps
├── runtime/
│   ├── README.md             # Local/hosted model runtime and config
│   └── llama.md                # llama.cpp TurboQuant guide
├── testing/
│   └── README.md             # Validation layers and live test policy
└── browser-workspace.md      # Existing browser workspace contract
```

## Maintenance Rules

- Update `docs/api/README.md` whenever a route, request body, response body,
  SSE payload, WebSocket event, or error envelope changes.
- Add or update an ADR when a decision changes module boundaries, persistence,
  provider behavior, transport contracts, or desktop/backend ownership.
- Keep component-specific READMEs short and link back to this hub for canonical
  cross-application documentation.
- Prefer references to real source files and tests over duplicated prose when a
  detail is volatile.
