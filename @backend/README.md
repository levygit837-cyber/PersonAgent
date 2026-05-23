# PersonAgent Backend

Backend API for PersonAgent — Personal AI Agent with multi-provider LLM support.

## Stack

- Python 3.12+
- FastAPI
- PostgreSQL + pgvector
- Electron (desktop)
- React + TypeScript (frontend)

## Database migrations

Schema changes go through Alembic. The configuration lives at the backend
root (`alembic.ini`) and the revisions live under
`src/personagent/infrastructure/persistence/alembic/versions/`.

### Common commands

```bash
# From the backend directory
uv run alembic history              # show revision graph
uv run alembic current              # show the current DB revision
uv run alembic upgrade head         # apply pending migrations
uv run alembic upgrade head --sql   # render SQL without running it
uv run alembic stamp head           # mark DB as up-to-date without DDL
uv run alembic revision --autogenerate -m "describe the change"
```

### Bootstrap flow

`init_db()` still does the heavy lifting on first boot for existing
deployments: it creates tables from the ORM models and applies the legacy
`ALTER TABLE` statements that pre-date Alembic. Immediately afterwards, it
stamps the `0001_baseline` revision so the database picks up future
migrations through the standard Alembic flow.

For brand-new deployments the recommended order is:

1. Start a fresh PostgreSQL database.
2. Run the backend once (or call `init_db`) to create the schema.
3. Verify with `alembic current` — you should see `0001_baseline (head)`.
4. From then on, every schema change is a new Alembic revision.

Operators upgrading an existing deployment do **not** need to do anything
extra: the bootstrap will detect the missing `alembic_version` table and
stamp the baseline automatically.
