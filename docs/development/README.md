# Development Guide

This guide collects the commands and conventions needed to work on PersonAgent.

## Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- PostgreSQL through Docker Compose
- CUDA toolchain when building/running local llama.cpp with GPU acceleration
- GitHub CLI for PR-related workspace features

## Backend

```bash
cd @backend
pip install -e ".[dev]"
personagent serve --port 8000 --reload
```

Useful validation:

```bash
cd @backend
pytest
ruff check .
mypy src/personagent
```

## Desktop

```bash
cd @desktop-electron
npm install
npm run dev
```

Useful validation:

```bash
cd @desktop-electron
npm test
npm run typecheck
```

## Local Services

```bash
docker compose up -d postgres
```

The backend can auto-start llama.cpp when configured. Local model defaults are
defined in `config.yaml`, `.env`, and backend settings.

## Documentation Workflow

1. Update source code and tests.
2. Update central docs under `docs/` in the same change when contracts or
   architecture change.
3. Keep route-level API documentation in `docs/api/README.md`.
4. Add an ADR under `docs/adr/` when the decision changes long-lived behavior.
5. Keep root and package READMEs short, with links back to `docs/`.

## Review Checklist

- Backend route changes include API docs and tests.
- Electron API client changes match backend routes and error envelopes.
- Streaming changes preserve SSE parsing and `[DONE]` behavior where used.
- WebSocket changes document inbound and outbound event shapes.
- Persistence changes include migrations and an ADR when they affect ownership
  or long-lived data contracts.
- Runtime-visible text, provider labels, and model group names remain coherent
  in the desktop UI.
