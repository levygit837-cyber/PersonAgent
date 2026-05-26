# PersonAgent — CommandCode Agent Instructions

## Project
Python 3.11+ FastAPI backend + Electron 41 / React 19 / TypeScript 5 desktop. PostgreSQL + pgvector. Clean Architecture with strict layers (domain → application → infrastructure → interfaces).

## How to Navigate
- **Always use codedb first** before grep, ripgrep, or reading files blindly
- `codedb_context` with a natural-language task when starting work on an unfamiliar area — one call replaces 3–5 search/word/symbol calls
- `codedb_tree` / `codedb_ls` to orient in the file tree
- `codedb_outline` to see symbols (functions, classes, imports) in a file before reading it
- `codedb_symbol` for exact definition lookups
- `codedb_search` for substring/regex full-text search across the codebase
- `codedb_word` for O(1) exact identifier lookup
- `codedb_callers` to find every usage of a symbol before refactoring
- `codedb_deps` to see who imports a file or what a file imports
- `codedb_hot` for recently modified files
- Only use grep/ripgrep as a fallback when codedb doesn't find what you need
- Only use Read on specific line ranges after codedb_outline tells you what's there

## Commands
- Backend: `cd @backend && uv run pytest` (tests), `uv run ruff check .` (lint), `uv run mypy src/personagent` (typecheck)
- Desktop: `cd @desktop-electron && npm test` (tests), `npm run lint` (lint), `npm run typecheck`
- Full CI: `cd @backend && uv run ruff check . && uv run mypy src/personagent && uv run pytest`
- Database: `docker compose up -d postgres` then `cd @backend && uv run alembic upgrade head`

## Rules
- Follow Clean Architecture: domain has zero imports from application/infrastructure/interfaces
- Use Pydantic v2 for models, SQLAlchemy 2.0 async for persistence
- TypeScript: strict mode, use const, prefer object params for functions with 2+ args
- Python: ruff formatting, mypy strict, pytest + pytest-asyncio for tests
- Never modify .worktrees/ — those are git worktree clones, not the real source
- Test files go in @backend/tests/ or @desktop-electron/src/**/*.test.tsx
