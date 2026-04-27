"""Configuração do banco de dados PostgreSQL com SQLAlchemy async."""

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


async def get_db_session() -> AsyncSession:
    """Retorna uma nova sessão de banco de dados."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Inicializa o banco de dados criando todas as tabelas."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
