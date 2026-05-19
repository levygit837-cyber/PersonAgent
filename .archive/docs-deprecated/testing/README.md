# Testing Documentation

PersonAgent has backend, desktop, and live integration validation layers.

## Backend

```bash
cd @backend
pytest
ruff check .
mypy src/personagent
```

Important backend test groups:

- Route tests under `@backend/tests/test_*_api.py`.
- Unit tests under `@backend/tests/unit/`.
- Live provider/browser tests under `@backend/tests/integration/`.
- Memory integration tests under `@backend/tests/integration/memory/`.

## Desktop

```bash
cd @desktop-electron
npm test
npm run typecheck
npm run build
```

Important desktop test groups:

- API client and SSE tests under `@desktop-electron/src/api/`.
- Chat component/store tests under `@desktop-electron/src/components/chat/`
  and `@desktop-electron/src/stores/`.
- Layout, terminal, skills, and PR workspace tests under their component
  directories.

## Live Validation

Use live tests for provider behavior, browser runtime, or performance claims.
Do not treat catalog presence or config values as proof that a provider or
runtime mode works.

Live validation is especially important for:

- Hosted provider tool-call behavior.
- Reasoning content separation.
- Browser/CDP behavior.
- Local llama.cpp/TurboQuant runtime state.
- Memory recall precision and latency.
