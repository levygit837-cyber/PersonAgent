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
  future records.
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
│   └── README.md             # Product subsystems and desktop/backend flows
├── architecture/
│   └── overview.md           # Application architecture and data flow
├── adr/
│   └── README.md             # ADR process, status values, and template
├── backend/
│   └── README.md             # Backend layers and contract ownership
├── development/
│   └── README.md             # Setup, tests, and doc maintenance
├── operations/
│   └── README.md             # Health checks, release review, diagnostics
├── runtime/
│   └── README.md             # Local/hosted model runtime and config
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
