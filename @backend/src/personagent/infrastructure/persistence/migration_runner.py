"""Programmatic Alembic helpers.

This module is the *only* supported way to run Alembic from inside the
application or test suite. It centralizes the resolution of ``alembic.ini``
so callers do not have to worry about working-directory assumptions, and it
exposes a small async-friendly surface for the common operations:

* :func:`stamp_head` -- mark the current database as fully migrated without
  applying any DDL. Used during the migration from the legacy
  ``init_db``-only flow to Alembic.
* :func:`upgrade_to_head` -- apply all pending migrations.
* :func:`current_revision` -- return the revision currently recorded in
  ``alembic_version``, or ``None`` if the table does not exist.

CLI-style usage (``alembic upgrade head`` from a shell) remains the canonical
operator workflow; these helpers exist for the runtime bootstrap path and
integration tests that need a deterministic schema state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

logger = structlog.get_logger(__name__)


def _alembic_ini_path() -> Path:
    """Return the absolute path to ``alembic.ini`` regardless of CWD.

    The file lives at the backend root; this module is several levels deeper.
    Walking up from ``__file__`` keeps the lookup stable when the package is
    installed (e.g. ``pip install -e .``) and when it runs from a checkout.
    """

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate alembic.ini from "
        f"{here}. Did the backend layout change?"
    )


def build_config(database_url: str | None = None) -> Config:
    """Build an :class:`alembic.config.Config` pointing at our env."""

    ini_path = _alembic_ini_path()
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(ini_path.parent / "src" / "personagent" / "infrastructure" / "persistence" / "alembic"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def _stamp_head_sync(database_url: str | None) -> None:
    config = build_config(database_url=database_url)
    command.stamp(config, "head")


async def stamp_head(database_url: str | None = None) -> None:
    """Mark the database as fully migrated without applying any DDL.

    Idempotent: stamping a database that is already at head is a no-op.
    """

    logger.info("alembic_stamp_head", url=_safe_url(database_url))
    await asyncio.to_thread(_stamp_head_sync, database_url)


def _upgrade_sync(database_url: str | None, revision: str) -> None:
    config = build_config(database_url=database_url)
    command.upgrade(config, revision)


async def upgrade_to_head(database_url: str | None = None) -> None:
    """Apply all pending migrations up to ``head``."""

    logger.info("alembic_upgrade_head", url=_safe_url(database_url))
    await asyncio.to_thread(_upgrade_sync, database_url, "head")


async def current_revision(database_url: str) -> str | None:
    """Return the revision recorded in ``alembic_version``.

    Returns ``None`` when the table does not yet exist, which is the signal
    bootstrap code uses to decide whether a stamp-from-scratch is needed.
    """

    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as connection:

            def _fetch(sync_connection) -> str | None:  # type: ignore[no-untyped-def]
                ctx = MigrationContext.configure(sync_connection)
                return ctx.get_current_revision()

            return await connection.run_sync(_fetch)
    finally:
        await engine.dispose()


def _safe_url(url: str | None) -> str | None:
    """Strip credentials from a DSN for logging."""

    if url is None:
        return None
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host_and_path = rest.partition("@")
    return f"{scheme}://***@{host_and_path}"


def to_sync_url(url: str) -> str:
    """Return a sync-driver equivalent of the runtime DSN.

    Alembic's offline mode does not need (and cannot use) ``asyncpg``. When
    the runtime URL declares the async driver we swap it for ``psycopg`` so
    ``alembic upgrade --sql`` keeps working in environments where only the
    sync driver is installed.
    """

    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    return url
