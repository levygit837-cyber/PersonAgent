# PersonAgent Desktop Electron

Primary desktop client for PersonAgent. It keeps the existing FastAPI backend and runs the desktop UI with React, TypeScript, Tailwind, Radix/shadcn-style primitives, Zustand, TanStack Query, and React Flow.

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

- Chat uses the existing `POST /chat/completions/stream` SSE endpoint through `fetch` and `ReadableStream`.
- IPC is intentionally small: window controls, persisted settings, and native folder picker.
