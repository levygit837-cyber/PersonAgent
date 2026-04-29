# PersonAgent Desktop Electron

Primary desktop client for PersonAgent. It keeps the existing FastAPI backend and runs the desktop UI with React, TypeScript, Tailwind, Radix/shadcn-style primitives, Zustand, TanStack Query, and React Flow.

Canonical cross-application documentation lives in:

- [../docs/README.md](../docs/README.md)
- [../docs/app/README.md](../docs/app/README.md)
- [../docs/api/README.md](../docs/api/README.md)

## Run

```bash
cd @desktop-electron
npm install
npm run dev
```

The app auto-discovers the backend on `http://localhost:8000` and `http://localhost:8001`.

## Checks

```bash
npm run typecheck
npm test
npm run build
```

## Scope

- Backend calls should go through `src/api/client.ts`.
- Streaming should go through `src/api/sse.ts`.
- API errors should use the structured envelope handled by `src/api/errors.ts`.
- IPC is intentionally small: window controls, persisted settings, and native folder picker.
