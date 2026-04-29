# PersonAgent

Local-first personal agent system with a Python/FastAPI backend, the official
Electron desktop client, and llama.cpp + TurboQuant for local LLM inference.

## Documentation

The canonical documentation hub is [docs/README.md](docs/README.md).

- [Application overview](docs/architecture/overview.md)
- [API reference](docs/api/README.md)
- [ADR index and template](docs/adr/README.md)
- [Development guide](docs/development/README.md)
- [Browser Workspace contract](docs/browser-workspace.md)

## Architecture

```
PersonAgent/
├── @backend/                    ← Python + FastAPI
│   ├── src/personagent/
│   │   ├── domain/              ← Pure business concepts
│   │   ├── application/         ← Use cases and orchestration
│   │   ├── infrastructure/      ← External adapters
│   │   └── interfaces/          ← FastAPI + CLI
│   └── pyproject.toml
│
├── @llama/                      ← Fork llama.cpp + TurboQuant
│   ├── llama-cpp-turboquant/    ← Inference runtime
│   ├── scripts/
│   │   ├── build.sh
│   │   ├── start-server.sh
│   │   └── stop-server.sh
│   └── models/                  ← GGUF symlinks
│
├── @desktop-electron/           ← Electron + React desktop client (official desktop app)
│   ├── electron/                ← main/preload with isolated IPC
│   └── src/                     ← React renderer, shadcn-style UI, Chat
│
├── docs/                        ← Central documentation hub
├── docker-compose.yml           ← PostgreSQL
├── config.yaml                  ← YAML configuration
└── .env                         ← Environment variables
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- PostgreSQL through Docker
- CUDA Toolkit for NVIDIA GPU acceleration
- **cmake**, **build-essential**

### 2. Start PostgreSQL

```bash
docker compose up -d postgres
```

### 3. Build llama.cpp with TurboQuant

```bash
cd @llama
./scripts/build.sh
```

### 4. Install Python Dependencies

```bash
cd @backend
pip install -e ".[dev]"
```

### 5. Start The System

```bash
# CLI
personagent chat -m "Hello, who are you?"

# API server
personagent serve --port 8000
```

### 6. Start The Desktop

```bash
cd @desktop-electron
npm install
npm run dev
```

## TurboQuant

TurboQuant is an extreme KV cache quantization mode used by the local llama.cpp
runtime. Current defaults are configured for long-context local inference:

```yaml
llm:
  cache_type_k: "turbo4"
  cache_type_v: "turbo4"
  ctx_size: 262144
```

## API

The full active API map is maintained in [docs/api/README.md](docs/api/README.md).
Major route groups:

- `/chat` for completions, prompt preview, approvals, providers, and Team Mode.
- `/conversations` for conversation list/detail/fork/delete/search.
- `/sessions` for session panel and Browser Workspace actions.
- `/memory` for structured and operational memory.
- `/workspace` for files, mentions, Git, worktrees, and PR operations.
- `/skills` for installed and marketplace skills.
- `/qa` for execution-to-code graph tracing.
- `/events/state` for desktop cache invalidation events.

## CLI Commands

```bash
# Interactive chat
personagent chat -m "Your message here"

# Streaming without visible reasoning
personagent chat -m "Explain quantum computing" --no-think

# Model status
personagent model --status

# List conversations
personagent conversations-list

# Start API server
personagent serve --port 8000 --reload
```
