# Persistence no PersonAgent

## Visão geral

O backend usa **PostgreSQL 16 + pgvector** como store principal, acessado via **SQLAlchemy 2.0 async** (`asyncpg` driver). SQLite não é suportado para produção.

## Estrutura de tabelas

### Core (sempre criadas)
- `conversations`: sessões de chat
- `messages`: mensagens individuais (role, content, tokens)
- `browser_workspaces`: estado do browser por conversa
- `browser_tabs`, `browser_annotations`, `browser_timeline_events`

### Operational Memory (condicional)
Criadas apenas quando `operational_memory_enabled=True`:
- `memory_events`, `memory_chunks`, `memory_embeddings`
- `memory_structured_items`, `memory_recalls`

### Team Mode
- `team_runs`, `team_blackboard_events`, `team_memory_snapshots`

### QA
- `qa_sessions`, `qa_code_nodes`, `qa_code_edges`, `qa_runtime_events`, `qa_request_runs`

## pgvector

- Extensão carregada em `init_db()`.
- Colunas `Vector(dim)` para embeddings.
- Índice HNSW para busca por similaridade coseno.

## Engine e sessão

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)
```

## Repository Pattern

Cada entidade do domínio tem um repository concreto em `infrastructure/persistence/`:

```python
class ConversationRepository(Protocol):
    async def create(self, conversation: Conversation) -> None: ...
    async def get_by_id(self, id: UUID) -> Conversation | None: ...

class SQLAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
```

## Migrations

- Não usamos Alembic.
- DDL idempotente em `database.py` (`IF NOT EXISTS`).
- Mudanças de schema são revisadas no PR como código normal.

## Backup e restore

```bash
# dump
docker exec postgres pg_dump -U personagent personagent > backup.sql
# restore
docker exec -i postgres psql -U personagent personagent < backup.sql
```

## Referências

- ADR 0004: PostgreSQL + pgvector
- ADR 0021: Manual SQL Migrations
