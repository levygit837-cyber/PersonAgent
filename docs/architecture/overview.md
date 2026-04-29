# PersonAgent Application Overview

PersonAgent is a local-first desktop agent system. The active desktop target is
`@desktop-electron`; the backend is a Python FastAPI application with clean
architecture boundaries; local inference runs through llama.cpp/TurboQuant and
hosted providers are available through backend adapters.

## Runtime Shape

```text
Electron renderer
  ├─ React chat, session panel, browser workspace, Git/workspace UI
  ├─ @desktop-electron/src/api/client.ts
  └─ SSE/WebSocket readers
        │
        ▼
FastAPI backend
  ├─ interfaces/api/routes/*
  ├─ application services and use cases
  ├─ domain models, exceptions, repositories
  └─ infrastructure adapters
        ├─ PostgreSQL persistence
        ├─ llama.cpp process manager
        ├─ hosted LLM providers
        ├─ browser worker/CDP/LightPanda
        └─ local tools, Git, filesystem, MCP
```

## Repository Areas

| Path | Responsibility |
| --- | --- |
| `@backend/src/personagent/domain` | Pure business concepts: conversations, messages, context models, exceptions, repository ports, and tool contracts. |
| `@backend/src/personagent/application` | Use cases, orchestration, memory services, session panel data, tool runtime, jobs, retry behavior, and QA services. |
| `@backend/src/personagent/infrastructure` | External adapters for config, persistence, LLM providers, browser/tool implementations, and process management. |
| `@backend/src/personagent/interfaces/api` | FastAPI app, routers, SSE/WebSocket transport, and error mapping. |
| `@backend/src/personagent/interfaces/cli` | Typer/Rich command-line interface. |
| `@desktop-electron/electron` | Electron main/preload processes and isolated IPC. |
| `@desktop-electron/src` | React renderer, Zustand stores, API client, and desktop UI. |
| `@llama` | Local llama.cpp/TurboQuant runtime, scripts, and model links. |
| `docs` | Canonical cross-application documentation. |

## Backend Boundaries

The backend follows a directional dependency rule:

```text
interfaces -> application -> domain
infrastructure -> application/domain ports
```

Routes should stay thin: parse HTTP transport, call application services or use
cases, and return typed response payloads. Domain exceptions are mapped at the
API edge by `interfaces/api/errors.py`.

## Desktop Boundaries

The Electron renderer should use `@desktop-electron/src/api/client.ts` rather
than constructing ad hoc fetch calls. Streaming should use
`@desktop-electron/src/api/sse.ts`, and error display should consume
`PersonAgentApiError` from `@desktop-electron/src/api/errors.ts`.

Stateful UI flows are split across stores and components:

- Chat/session execution: `src/stores/chat-store.ts` and `components/chat/*`.
- Workspace and Git actions: `src/api/client.ts`, `stores/git-store.ts`, and
  layout/workspace components.
- Browser Workspace: session panel components plus `/sessions/.../browser`
  routes.
- Skills: `components/skills/*` and `/skills` routes.

## Major Data Flows

### Chat

1. The desktop builds a `ChatRequestPayload`.
2. The backend resolves provider, model, prompt mode, tool context, memory, and
   workspace root.
3. `ChatCompletionUseCase` runs model inference and tool loops.
4. The backend persists conversation messages and streams ordered events.
5. The desktop renders reasoning, content, tool calls, approvals, images, and
   final state in stream order.

### Browser Workspace

1. Browser tools create or reuse a logical browser/page.
2. `/sessions/.../browser/...` routes expose browser view and user actions.
3. Conversation metadata stores only lightweight browser workspace state.
4. Electron renders DOM/screenshot data, annotations, timeline, and cooperation
   state.

### Memory

1. Structured project memories live in repository-backed storage.
2. Operational memory indexes runtime evidence and supports filtered recall.
3. Chat context can include recalled memory when relevant to the user request.
4. Background memory jobs are scheduled from the backend lifespan when enabled.

### Workspace And Git

Workspace routes resolve paths inside allowed roots, expose files and mention
suggestions, and wrap Git/GitHub CLI workflows for branch, worktree, commit,
push, PR, and recent activity operations. Mutating operations publish state
events for desktop cache invalidation.

## Persistence

The backend uses async SQLAlchemy with PostgreSQL. Database initialization runs
during FastAPI lifespan. Migrations live under
`@backend/src/personagent/infrastructure/persistence/migrations/`.

Important persisted areas include:

- Conversations and messages.
- Session/browser workspace metadata.
- Operational memory and memory job state.
- QA sessions, graph data, request runs, and runtime events.

## Provider And Model Runtime

Local inference is managed by the llama.cpp process manager. Hosted providers
are backend-owned adapters, so the desktop sends provider/model selection but
does not own provider credentials or provider-specific payload logic.

Current provider surface includes local llama, NVIDIA NIM, official DeepSeek
API, Vertex/Gemini, Kimi, and Codex subscription-backed inference.

## Documentation Ownership

- Cross-cutting architecture and contracts belong in `docs/`.
- Backend-only setup details can remain in `@backend/README.md`, but should link
  to central docs.
- Desktop-only setup details can remain in `@desktop-electron/README.md`, but
  should link to central docs.
- Runtime decisions belong in ADRs under `docs/adr/`.
