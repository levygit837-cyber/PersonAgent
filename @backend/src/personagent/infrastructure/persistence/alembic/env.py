"""Alembic environment for PersonAgent.

This module wires Alembic's CLI to the same configuration the runtime uses:

* The database URL is read from ``personagent.infrastructure.config.settings``
  (which itself respects ``DATABASE_URL`` / ``POSTGRES_*`` env vars) so the
  same ``.env`` file drives both the running app and any migration runs.
* ``target_metadata`` points at the ORM ``Base.metadata`` so future
  ``alembic revision --autogenerate`` calls have something to diff against.
* Online migrations use the async engine because the runtime URL is the
  ``postgresql+asyncpg`` driver. Offline mode falls back to a sync-friendly
  URL so ``alembic upgrade --sql`` keeps working.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

# Import the ORM models so Base.metadata is fully populated before Alembic
# inspects it. The import is intentionally side-effectful.
from personagent.infrastructure.persistence import models as _models  # noqa: F401
from personagent.infrastructure.persistence.database import Base
from personagent.infrastructure.persistence.migration_runner import to_sync_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Pick the URL to migrate against.

    Order of precedence:

    1. ``-x url=...`` passed to the CLI (handy for one-off migrations against
       a snapshot or read replica).
    2. ``sqlalchemy.url`` declared in ``alembic.ini`` -- intentionally left
       empty in this repo, but supported for operators who prefer the standard
       Alembic flow.
    3. The runtime settings, which honor ``DATABASE_URL`` and the
       ``POSTGRES_*`` family of env vars.
    """

    cli_options = context.get_x_argument(as_dictionary=True)
    if url := cli_options.get("url"):
        return url

    if url := config.get_main_option("sqlalchemy.url"):
        return url

    from personagent.infrastructure.config.settings import get_settings

    return str(get_settings().db_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it against a live database."""

    url = to_sync_url(_resolve_database_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations(url: str) -> None:
    """Build a temporary async engine and run migrations through it."""

    connectable = AsyncEngine(
        engine_from_config(
            {"sqlalchemy.url": url},
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            future=True,
        )
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a real database using the runtime engine config."""

    url = _resolve_database_url()
    asyncio.run(_run_async_migrations(url))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
