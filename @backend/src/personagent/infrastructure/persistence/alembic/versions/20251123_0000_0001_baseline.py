"""baseline: claim the current schema as Alembic revision 0001.

Revision ID: 0001_baseline
Revises:
Create Date: 2025-11-23 00:00:00.000000

This is intentionally a no-op migration. It exists to anchor Alembic's
``alembic_version`` table at a known starting point for every existing
deployment.

The migration **flow** going forward is:

1. **Existing deployments**: run ``alembic stamp 0001_baseline`` once. The
   schema is already in the shape Alembic expects (because ``init_db`` has
   been creating tables and applying the hardcoded ALTER statements for
   every release up to this point), so there is nothing to apply -- we just
   tell Alembic to remember that the database is up to date.
2. **Fresh deployments**: ``init_db`` still does the heavy lifting for now
   (``Base.metadata.create_all`` + the legacy ALTER statements). Right
   after, the bootstrap code stamps this revision so the database is in
   sync with Alembic's history.
3. **All future schema changes** go through ``alembic revision --autogenerate``
   followed by ``alembic upgrade head``. The legacy ALTER statements in
   ``database.py`` will be folded into a later revision and removed once
   every environment has been migrated past it.

Keeping this revision empty avoids the risk of subtly mis-recreating a
schema that has 30+ tables, several ``pgvector`` indexes, JSONB defaults,
and trigger-driven side effects.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op. See module docstring for the rationale."""


def downgrade() -> None:
    """No-op. The baseline cannot be reversed -- it is the bottom of the chain."""
