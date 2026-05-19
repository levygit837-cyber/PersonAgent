# Application Documentation

This section documents product-facing subsystems and desktop/backend flows.

## Current Subsystems

| Area | Source Of Truth | Notes |
| --- | --- | --- |
| Desktop shell and chat | `@desktop-electron/src` | Official desktop target. React renderer, Zustand stores, API client, and Electron main/preload. |
| Chat execution | `@backend/src/personagent/application/use_cases/chat_completion.py` | Provider routing, prompt construction, tool loops, reasoning/final split, approvals, persistence, and streaming. |
| Team Mode | `@backend/src/personagent/interfaces/api/routes/chat.py` | WebSocket flow under `/chat/team/ws`. |
| Session panel | `@backend/src/personagent/application/services/session_panel.py` | Conversation status, workspace detail, and session summary data for desktop panels. |
| Browser Workspace | `docs/browser-workspace.md` | Browser runtime, annotations, cooperation, control tools, and persisted lightweight state. |
| Skills | `@backend/src/personagent/interfaces/api/routes/skills.py` | Installed skills, marketplace skills, and activation state. |
| Memory | `@backend/src/personagent/interfaces/api/routes/memory.py` | Structured memory CRUD plus operational recall/indexing. |
| Workspace and Git | `@backend/src/personagent/interfaces/api/routes/workspace.py` | Files, mentions, projects, branches, worktrees, commits, pushes, and PRs. |
| QA tracing | `@backend/src/personagent/interfaces/api/routes/qa.py` | Execution-to-code graph sessions, request tracing, context, and stream events. |

## Desktop Contract

The desktop should treat `@desktop-electron/src/api/client.ts` as the boundary
to the backend. UI components and stores should call API helpers rather than
embedding endpoint strings.

The active streaming contracts are:

- Chat completion SSE.
- Tool approval resume SSE.
- User-question response SSE.
- QA runtime SSE.
- State-change SSE.
- Team Mode WebSocket.

## Documentação Operacional

- [Architecture](architecture.md) — Electron + React + Vite, IPC e segurança.
- [Chat](chat.md) — fluxo de mensagem, SSE e plan mode.
- [Chat Store](chat-store.md) — estado do chat no frontend.
- [API Client](api-client.md) — consumo da API FastAPI.
- [Config](config.md) — hierarquia de configuração.
- [Error Handling](error-handling.md) — hierarquia de erros e streaming.
- [Memory](memory.md) — três camadas de memória.
- [Prompt System](prompt-system.md) — montagem dinâmica do system prompt.
- [QA](qa.md) — tracing estático e runtime.
- [Session](session.md) — ciclo de vida de conversas.
- [Skills](skills.md) — discovery, ativação e injeção.
- [State Events](state-events.md) — SSE de invalidação e git.
- [Team Mode](team.md) — multi-agente com blackboard.
