"""Configuração do banco de dados PostgreSQL com SQLAlchemy async."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from personagent.infrastructure.config.settings import get_settings

Base = declarative_base()

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


async def get_db_session() -> AsyncSession:
    """Retorna uma nova sessão de banco de dados."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Inicializa o banco de dados criando todas as tabelas."""

    # Ensure ORM models are registered in Base.metadata before create_all runs.
    from personagent.infrastructure.persistence import models as _models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in TEAM_MODE_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
