# @backend — PersonAgent Backend

Python/FastAPI backend for PersonAgent.

Canonical cross-application documentation lives in:

- [../docs/README.md](../docs/README.md)
- [../docs/api/README.md](../docs/api/README.md)
- [../docs/architecture/overview.md](../docs/architecture/overview.md)

## Clean Architecture

```
src/personagent/
├── domain/                      ← Framework-independent business concepts
│   ├── models/                  ← Entities and value objects
│   ├── repositories/            ← Repository ports
│   └── exceptions.py            ← Domain exceptions
│
├── application/                 ← Use cases and orchestration
│   ├── services/                ← Application services
│   ├── use_cases/               ← Business workflow orchestration
│   └── ports/                   ← Service ports
│
├── infrastructure/              ← External adapters
│   ├── config/                  ← Settings from .env + YAML
│   ├── llm/                     ← llama.cpp and hosted provider adapters
│   └── persistence/             ← PostgreSQL + SQLAlchemy
│
└── interfaces/                  ← Entry points
    ├── api/                     ← FastAPI + routes
    └── cli/                     ← Typer + Rich
```

## Dependency Injection

The backend uses a simple DI container in `interfaces/config/di_container.py`:

```python
container = get_container()
llm_backend = container.get_llm_backend()
process_manager = container.get_process_manager()
```

## Database

- PostgreSQL with async SQLAlchemy.
- Migrations live in `infrastructure/persistence/migrations/`.
- Database initialization runs during FastAPI lifespan.

## API And Streaming

The active API surface is documented in
[../docs/api/README.md](../docs/api/README.md). Streaming transports include:

- Chat completion SSE.
- Tool approval and user-question resume SSE.
- QA runtime SSE.
- State-change SSE.
- Team Mode WebSocket.

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check . --fix
ruff format .

# Type check
mypy src/personagent
```
