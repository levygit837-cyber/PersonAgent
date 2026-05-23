"""0002: introduce the ``tenants`` table and a ``tenant_id`` column on ``conversations``.

Revision ID: 0002_multi_tenant_primitives
Revises: 0001_baseline
Create Date: 2025-11-24 00:00:00.000000

This migration is the first step of the Fase 1 multi-tenant work. It is
intentionally conservative:

* Adds a ``tenants`` table with stable schema (id, slug, name, timestamps,
  metadata).
* Inserts a single *default tenant* row whose UUID is hard-coded
  (``00000000-0000-0000-0000-000000000001``) so single-tenant installs
  continue to work without any application-level changes.
* Adds a ``tenant_id`` column to ``conversations`` (FK to ``tenants.id``,
  ``ON DELETE RESTRICT`` because we never want to silently lose chat
  history).
* Backfills every existing conversation with the default tenant id, then
  flips the column to ``NOT NULL``.
* Creates an index on ``conversations(tenant_id)`` for the typical
  "list my conversations" query path.

What this migration explicitly does *not* do:

* It does **not** add ``tenant_id`` to leaf tables that are scoped via
  ``conversation_id`` (messages, browser_tabs, ...). Those inherit
  tenancy by joining through their parent and adding a redundant column
  would just create a denormalization risk.
* It does **not** introduce ``users`` yet. User accounts are still
  out of scope until the auth layer is rebuilt.
* It does **not** add ``tenant_id`` to peer root tables (``team_runs``,
  ``browser_workspaces``, ``memory_*``, ``qa_*``). Those land in
  follow-up revisions to keep this PR's blast radius small and
  reviewable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_multi_tenant_primitives"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_SLUG = "default"
_DEFAULT_TENANT_NAME = "Default"


def _is_offline_mode() -> bool:
    """``True`` when Alembic was invoked with ``--sql`` (offline mode).

    Offline mode emits raw DDL to stdout for an operator to review/apply
    manually -- there is no live database to introspect. In that case we
    *must* emit every statement unconditionally, because there's no way
    to know what the target database already contains.
    """

    return bool(op.get_context().as_sql)


def _has_table(bind: sa.engine.Connection, name: str) -> bool:
    if _is_offline_mode():
        return False
    return sa.inspect(bind).has_table(name)


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    if _is_offline_mode():
        return False
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(bind: sa.engine.Connection, table: str, name: str) -> bool:
    if _is_offline_mode():
        return False
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def _has_fk(bind: sa.engine.Connection, table: str, name: str) -> bool:
    if _is_offline_mode():
        return False
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(fk["name"] == name for fk in inspector.get_foreign_keys(table))


def upgrade() -> None:
    """Forward migration: create ``tenants`` + add ``conversations.tenant_id``.

    Every step is guarded by an existence check because ``init_db`` may
    have already created the table via ``Base.metadata.create_all`` (the
    fresh-install path) before Alembic runs. Without the guards, this
    migration would crash with ``DuplicateTable`` / ``DuplicateColumn`` on
    new deployments.
    """

    bind = op.get_bind()

    if not _has_table(bind, "tenants"):
        op.create_table(
            "tenants",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        )

    # Seed the always-on tenant. ``ON CONFLICT DO NOTHING`` keeps the
    # migration idempotent across reruns.
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, slug, name, metadata)
            VALUES (CAST(:tenant_id AS uuid), :slug, :name, '{}'::jsonb)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            tenant_id=_DEFAULT_TENANT_ID,
            slug=_DEFAULT_TENANT_SLUG,
            name=_DEFAULT_TENANT_NAME,
        )
    )

    if not _has_column(bind, "conversations", "tenant_id"):
        # Add the ``tenant_id`` column as nullable first so we can
        # backfill existing rows before flipping it to NOT NULL. This
        # sequence (add nullable -> backfill -> alter NOT NULL) avoids
        # the table rewrite that NOT NULL + default would trigger on
        # large tables in older Postgres versions.
        op.add_column(
            "conversations",
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE conversations
            SET tenant_id = CAST(:tenant_id AS uuid)
            WHERE tenant_id IS NULL
            """
        ).bindparams(tenant_id=_DEFAULT_TENANT_ID)
    )

    op.alter_column(
        "conversations",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    if not _has_fk(bind, "conversations", "fk_conversations_tenant_id_tenants"):
        op.create_foreign_key(
            "fk_conversations_tenant_id_tenants",
            "conversations",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if not _has_index(bind, "conversations", "ix_conversations_tenant_id"):
        op.create_index(
            "ix_conversations_tenant_id",
            "conversations",
            ["tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    """Reverse migration: drop ``conversations.tenant_id`` + ``tenants``."""

    bind = op.get_bind()

    if _has_index(bind, "conversations", "ix_conversations_tenant_id"):
        op.drop_index("ix_conversations_tenant_id", table_name="conversations")
    if _has_fk(bind, "conversations", "fk_conversations_tenant_id_tenants"):
        op.drop_constraint(
            "fk_conversations_tenant_id_tenants",
            "conversations",
            type_="foreignkey",
        )
    if _has_column(bind, "conversations", "tenant_id"):
        op.drop_column("conversations", "tenant_id")
    if _has_table(bind, "tenants"):
        op.drop_table("tenants")
