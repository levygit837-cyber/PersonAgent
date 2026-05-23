# ADR 0021: Manual SQL Migrations Executed at Startup (No Alembic)

Date: 2025-06-10
Status: Accepted

## Context

Schema evolution must be reviewable, deterministic, and coupled to code releases. Alembic adds a dependency, autogeneration can produce unsafe DDL, and migration history becomes a separate operational concern.

## Decision

Use **manual, idempotent SQL statements** executed synchronously during `init_db()` at application startup.

**Migration files**
- There is no separate migration directory. Schema statements live in `infrastructure/persistence/database.py` as Python string tuples.
- `TEAM_MODE_SCHEMA_STATEMENTS`, `BROWSER_COOPERATION_SCHEMA_STATEMENTS`, `OPERATIONAL_MEMORY_SCHEMA_STATEMENTS`.
- Each statement uses `IF NOT EXISTS` or `IF EXISTS` to be idempotent and safe to rerun.

**Operational memory conditional creation**
- When `operational_memory_enabled=True`, the `pgvector` extension is created and operational memory tables/indexes are built.
- When disabled, only core tables (conversations, messages, browser workspaces) are created.

**Policy**
- Schema changes are part of the normal PR review process.
- No downgrade path: if a release is rolled back, the schema remains forward-compatible.
- Renames/adds are safe; destructive changes require a dedicated migration ADR.

## Consequences

- **Easier**: zero extra dependencies; schema and code are reviewed together; idempotent statements tolerate restart loops.
- **Harder**: no automatic diff generation; developers must write DDL by hand; rollback requires manual intervention.
- **Risk**: a missing index or a bad `ALTER TABLE` can degrade performance or fail in production. Mitigation: integration tests against a clean Postgres container.
- **Out of scope**: zero-downtime online schema changes; multi-step blue/green migrations.

## Alternatives Considered

- **Alembic**: rejected for the dependency overhead and autogeneration risk in a small team.
- **Django-style migrations**: not applicable (no Django ORM).

## Validation

- CI starts a fresh Postgres container and runs the backend; `init_db()` must complete without errors.
- Integration tests validate that all tables and indexes exist after startup.
