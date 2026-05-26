"""Configuração do banco de dados PostgreSQL com SQLAlchemy async."""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from personagent.infrastructure.settings.settings import get_settings

Base = declarative_base()
logger = structlog.get_logger(__name__)

_settings = get_settings()

engine = create_async_engine(
    _settings.db_url,
    echo=_settings.sqlalchemy_echo,
    hide_parameters=True,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

TEAM_MODE_SCHEMA_STATEMENTS = (
    "ALTER TABLE team_runs ADD COLUMN IF NOT EXISTS run_id VARCHAR(100)",
    "ALTER TABLE team_runs ADD COLUMN IF NOT EXISTS workspace_id TEXT",
    "ALTER TABLE team_runs ADD COLUMN IF NOT EXISTS blackboard_snapshot JSONB",
    "ALTER TABLE team_blackboard_events ADD COLUMN IF NOT EXISTS workspace_id TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_team_runs_run_id ON team_runs(run_id) WHERE run_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_team_runs_workspace_id ON team_runs(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_team_blackboard_events_run_id_sequence ON team_blackboard_events(run_id, sequence)",
    "CREATE INDEX IF NOT EXISTS idx_team_blackboard_events_workspace_id ON team_blackboard_events(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_team_memory_snapshots_workspace_id ON team_memory_snapshots(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_team_memory_snapshots_updated_at ON team_memory_snapshots(updated_at DESC)",
)

BROWSER_COOPERATION_SCHEMA_STATEMENTS = (
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS channel VARCHAR(40) NOT NULL DEFAULT 'event'",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS trace_role VARCHAR(30) NOT NULL DEFAULT 'user'",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS visibility VARCHAR(30) NOT NULL DEFAULT 'raw'",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS raw_kind VARCHAR(120)",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS coordinates JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS trace_effect VARCHAR(80)",
    "ALTER TABLE browser_cooperation_events ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(120)",
    "CREATE INDEX IF NOT EXISTS idx_browser_cooperation_workspace_correlation ON browser_cooperation_events(browser_workspace_id, correlation_id)",
)

OPTIONAL_OPERATIONAL_MEMORY_SCHEMA_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
)

OPERATIONAL_MEMORY_TABLES = frozenset({
    "memory_events",
    "memory_chunks",
    "memory_embeddings",
    "memory_structured_items",
    "memory_decisions",
    "memory_recall_logs",
    "memory_outbox",
    "memory_files",
    "memory_jobs",
    "memory_sessions",
    "memory_consolidation_locks",
})

OPERATIONAL_MEMORY_SCHEMA_STATEMENTS = (
    "ALTER TABLE memory_events DROP CONSTRAINT IF EXISTS memory_events_conversation_id_fkey",
    "ALTER TABLE memory_decisions DROP CONSTRAINT IF EXISTS memory_decisions_conversation_id_fkey",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS trust_level VARCHAR(20) NOT NULL DEFAULT 'medium'",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS importance DOUBLE PRECISION NOT NULL DEFAULT 0.5",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS search_vector TSVECTOR",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS state_reason TEXT",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS superseded_by_id UUID",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ",
    "ALTER TABLE memory_structured_items ADD COLUMN IF NOT EXISTS ranking_metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
    """
    UPDATE memory_structured_items
    SET search_text = trim(concat_ws(' ', summary, primary_path, source_type, item_type, paths::text, evidence::text)),
        search_vector = to_tsvector('simple', trim(concat_ws(' ', summary, primary_path, source_type, item_type, paths::text, evidence::text)))
    WHERE search_text = '' OR search_vector IS NULL
    """,
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS workspace_root TEXT",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS conversation_id UUID",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS recall_scope VARCHAR(40) NOT NULL DEFAULT 'workspace'",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS query_intent VARCHAR(80) NOT NULL DEFAULT 'specific'",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS candidate_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS selected_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS discarded_candidates JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS included_reasons JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS ranking_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS token_usage JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS budget_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE memory_recall_logs ADD COLUMN IF NOT EXISTS budget_used INTEGER NOT NULL DEFAULT 0",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'memory_embeddings'
              AND column_name = 'embedding'
              AND udt_name = 'jsonb'
        ) THEN
            ALTER TABLE memory_embeddings
            ALTER COLUMN embedding TYPE vector(4096)
            USING embedding::text::vector(4096);
        END IF;
    END $$;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_embeddings_embedding_subvector_1_2000_hnsw
    ON memory_embeddings
    USING hnsw (((subvector(embedding, 1, 2000))::vector(2000)) vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_project_created ON memory_structured_items(project_slug, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_project_type ON memory_structured_items(project_slug, item_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_project_latest ON memory_structured_items(project_slug, is_latest)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_conversation ON memory_structured_items(conversation_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_session ON memory_structured_items(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_workspace ON memory_structured_items(workspace_root)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_source_type ON memory_structured_items(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_primary_path ON memory_structured_items(primary_path)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_source_chunk ON memory_structured_items(source_chunk_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_hash ON memory_structured_items(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_status ON memory_structured_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_trust ON memory_structured_items(trust_level)",
    "CREATE INDEX IF NOT EXISTS idx_memory_structured_search_vector ON memory_structured_items USING gin(search_vector)",
    "CREATE INDEX IF NOT EXISTS idx_memory_recall_logs_workspace_created ON memory_recall_logs(workspace_root, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_outbox_dedupe_key ON memory_outbox(dedupe_key)",
    "CREATE INDEX IF NOT EXISTS idx_memory_outbox_status_next_attempt ON memory_outbox(status, next_attempt_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_outbox_event ON memory_outbox(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_outbox_project_created ON memory_outbox(project_slug, created_at)",
)


async def get_db_session() -> AsyncSession:
    """Retorna uma nova sessão de banco de dados."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Inicializa o banco de dados criando todas as tabelas.

    .. deprecated::
        New schema changes should be introduced via Alembic revisions
        (``alembic revision --autogenerate`` + ``alembic upgrade head``).
        The hardcoded ``ALTER TABLE`` blocks below are kept for backwards
        compatibility with existing deployments but will be folded into
        Alembic revisions in a follow-up release. After this function runs
        it now also stamps ``0001_baseline`` so the database picks up
        Alembic-tracked migrations going forward.
    """

    # Ensure ORM models are registered in Base.metadata before create_all runs.
    from personagent.infrastructure.persistence import models as _models  # noqa: F401

    if _settings.operational_memory_enabled:
        for statement in OPTIONAL_OPERATIONAL_MEMORY_SCHEMA_STATEMENTS:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
            except Exception as exc:
                logger.warning(
                    "optional_operational_memory_schema_failed",
                    statement=statement,
                    error=str(exc),
                )

    async with engine.begin() as conn:
        if _settings.operational_memory_enabled:
            await conn.run_sync(Base.metadata.create_all)
        else:
            # Cria apenas tabelas não-operacionais quando o RAG está desabilitado
            tables_to_create = [
                tbl for name, tbl in Base.metadata.tables.items()
                if name not in OPERATIONAL_MEMORY_TABLES
            ]
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables_to_create)
            )

        for statement in TEAM_MODE_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
        for statement in BROWSER_COOPERATION_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))

        if _settings.operational_memory_enabled:
            for statement in OPERATIONAL_MEMORY_SCHEMA_STATEMENTS:
                await conn.execute(text(statement))

        await _seed_default_tenant(conn)

    await _ensure_alembic_baseline()


# Hard-coded here (rather than imported from
# ``personagent.domain.models.tenancy``) to keep this bootstrap module
# free of cross-layer imports. The two definitions are guarded by a unit
# test that asserts they stay in sync.
_DEFAULT_TENANT_ID_STR = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_SLUG = "default"
_DEFAULT_TENANT_NAME = "Default"


async def _seed_default_tenant(conn) -> None:  # type: ignore[no-untyped-def]
    """Ensure the always-on default tenant row exists.

    Alembic revision ``0002`` performs the same insert; running it here
    too means fresh installs (which currently take the
    ``create_all + stamp_head`` path instead of ``upgrade_to_head``) also
    get the row. ``ON CONFLICT DO NOTHING`` keeps it idempotent.
    """

    if "tenants" not in Base.metadata.tables:
        return

    await conn.execute(
        text(
            """
            INSERT INTO tenants (id, slug, name, metadata)
            VALUES (CAST(:tenant_id AS uuid), :slug, :name, '{}'::jsonb)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            tenant_id=_DEFAULT_TENANT_ID_STR,
            slug=_DEFAULT_TENANT_SLUG,
            name=_DEFAULT_TENANT_NAME,
        )
    )


async def _ensure_alembic_baseline() -> None:
    """Stamp the baseline Alembic revision if the database is not yet tracked.

    This makes the transition from ``create_all`` + hardcoded ALTERs to
    Alembic-driven migrations safe for every existing deployment. The logic is
    idempotent: stamping a database that already has an ``alembic_version``
    row is a no-op.
    """

    from personagent.infrastructure.persistence.migration_runner import (
        current_revision,
        stamp_head,
    )

    try:
        revision = await current_revision(_settings.db_url)
    except Exception as exc:
        logger.warning("alembic_current_revision_failed", error=str(exc))
        return

    if revision is not None:
        return

    try:
        await stamp_head(_settings.db_url)
    except Exception as exc:
        logger.warning("alembic_stamp_baseline_failed", error=str(exc))
