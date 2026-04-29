"""Configuração do banco de dados PostgreSQL com SQLAlchemy async."""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from personagent.infrastructure.config.settings import get_settings

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

OPERATIONAL_MEMORY_SCHEMA_STATEMENTS = (
    "ALTER TABLE memory_events DROP CONSTRAINT IF EXISTS memory_events_conversation_id_fkey",
    "ALTER TABLE memory_decisions DROP CONSTRAINT IF EXISTS memory_decisions_conversation_id_fkey",
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
)


async def get_db_session() -> AsyncSession:
    """Retorna uma nova sessão de banco de dados."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Inicializa o banco de dados criando todas as tabelas."""

    # Ensure ORM models are registered in Base.metadata before create_all runs.
    from personagent.infrastructure.persistence import models as _models  # noqa: F401

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
        await conn.run_sync(Base.metadata.create_all)
        for statement in TEAM_MODE_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
        for statement in BROWSER_COOPERATION_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
        for statement in OPERATIONAL_MEMORY_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
