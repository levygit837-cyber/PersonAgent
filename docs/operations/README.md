# Operations Documentation

This section collects operational checks for local development, release review,
and runtime diagnosis.

## Health Checks

- `GET /health` confirms the backend is reachable and checks the selected
  default LLM backend.
- The Electron desktop tries `http://localhost:8000` and
  `http://localhost:8001` during backend discovery.
- FastAPI docs are available at `/docs` and `/redoc` in development mode.

## Common Commands

```bash
docker compose up -d postgres

cd @backend
personagent serve --port 8000 --reload

cd @desktop-electron
npm run dev
```

## Release Review Checklist

- Backend tests, lint, and type checks pass.
- Desktop tests, type checks, and build pass.
- Route or transport changes are reflected in [../api/README.md](../api/README.md).
- Persistence changes include migrations and an ADR when long-lived ownership
  or behavior changes.
- Provider or runtime claims are validated with the exact provider/model path.
- Git/workspace changes are checked against dirty worktree and large artifact
  risks before staging or committing.

## Diagnostics To Expand

Create focused pages when a recurring operational issue appears:

- `release-checklist.md`
- `diagnostics.md`
- `provider-validation.md`
- `browser-runtime.md`
