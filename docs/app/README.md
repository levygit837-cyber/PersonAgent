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

## Future Pages

Split this index into dedicated pages when a subsystem changes materially:

- `desktop-electron.md`
- `chat-experience.md`
- `session-panel.md`
- `team-mode.md`
- `skills.md`
- `memory.md`
- `workspace-git.md`
- `qa-system.md`
