---
schema_version: 1
generated_at: 2026-05-26T12:00:00Z
generator: claude-sonnet-4-6
source_hash: blake2b:placeholder
source_files:
  - @backend/src/personagent/infrastructure/tools/mcp_tools.py
  - @backend/src/personagent/interfaces/config/di_container.py
  - @backend/src/personagent/domain/tools/contracts.py
  - @backend/src/personagent/application/tools/registry.py
  - @backend/src/personagent/infrastructure/config/settings.py
  - @desktop-electron/electron/main.ts
  - @desktop-electron/src/components/chat/message-feed.tsx
  - @desktop-electron/src/stores/chat-store.ts
loc_budget: 200
loc_actual: 140
---

# PersonAgent

Local-first AI agent desktop app. FastAPI/Python backend + Electron/React/TypeScript frontend. PostgreSQL+pgvector persistence. Multi-provider LLM (llama.cpp, NVIDIA NIM, Vertex AI, Kimi, DeepSeek). Clean Architecture.

## Layout

- `@backend/src/personagent/` — Python backend (domain → application → infrastructure → interfaces)
  - `domain/` — zero-dep pure models: tools, prompts, memory, exceptions
  - `application/` — use cases (chat, tools, plan/team modes), DTOs, services, app state
  - `infrastructure/` — LLM adapters, browser (Playwright/CDP), persistence (SQLAlchemy/pgvector), tools implementation
  - `interfaces/` — FastAPI routes, CLI (Typer), DI container
- `@desktop-electron/` — Electron 41 desktop
  - `electron/main.ts` — window mgmt, IPC, PTY terminal, security
  - `src/components/chat/` — React 19 chat UI with streaming SSE
  - `src/stores/` — Zustand state management (chat, git, terminal)
- `@backend/tests/` — pytest + pytest-asyncio (integration + unit)
- `@desktop-electron/src/**/*.test.tsx` — vitest

## Key concepts

- **Clean Architecture**: domain imports nothing from app/infra/interfaces. Ports (abstract) → Adapters (concrete).
- **Tool system**: `domain/tools/contracts.py` defines `Tool`, `ToolDefinition`, `ToolRegistry`. Infrastructure registers concrete tools. DI container wires everything.
- **MCP client**: `infrastructure/tools/mcp_tools.py` creates dynamic MCP tools from `McpServerConfig`. Supports stdio transport with JSON-RPC 2.0.
- **Plan Mode**: agent proposes steps before acting (`application/plan_mode.py`); user approves each.
- **Team Mode**: multi-agent orchestration via blackboard (`application/team_chat/`), consensus/coordinator phases.
- **Memory**: three-layer: structured (files), operational (runtime semantic), embeddings (pgvector).
- **Config**: `config.yaml` + env vars → `infrastructure/config/settings.py` (Pydantic v2).

## Entry points

- **Add an LLM provider** → `infrastructure/llm/` adapter pattern; see `kimi_coding_adapter.py`
- **Add a tool** → define Tool in domain, implement in infra, register via DI container (`interfaces/config/di_container.py`)
- **Add API route** → `interfaces/api/routes/` + register in `interfaces/api/main.py`
- **Frontend feature** → Zustand store (`src/stores/`) → React component (`src/components/`)
- **Database migration** → `@backend alembic upgrade head` / create revision in `infrastructure/persistence/alembic/versions/`

## Conventions

- Python: ruff format, mypy strict, pytest + pytest-asyncio, structlog for logging
- TypeScript: strict mode, const not let, object params for 2+ args, Tailwind + Radix UI
- Test naming: `test_<module>.py` or `<module>.test.tsx`
- `.worktrees/` is git worktrees — never modify
- DI: manual container (`di_container.py`), no magic frameworks
