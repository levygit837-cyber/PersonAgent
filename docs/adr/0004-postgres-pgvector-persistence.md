# ADR 0004: PostgreSQL 16 + pgvector + SQLAlchemy 2.0 Async

Date: 2025-06-10
Status: Accepted

## Context

PersonAgent needs durable persistence for conversations, messages, browser workspaces, operational memory (RAG), and team-mode blackboard events. SQLite is insufficient for concurrent async workloads and vector search. We need a single store that handles structured relational data and semantic retrieval.

## Decision

Use PostgreSQL 16 with the `pgvector` extension as the primary database, accessed through SQLAlchemy 2.0 async (`asyncpg` driver).

**Key choices**
- **Async engine**: `create_async_engine(..., pool_pre_ping=True, pool_size=10, max_overflow=20)`.
- **Session factory**: `async_sessionmaker(..., expire_on_commit=False, autoflush=False)`.
- **ORM base**: `declarative_base()` in `@backend/src/personagent/infrastructure/persistence/database.py`.
- **pgvector**: `Vector(dimensions)` columns for embeddings; HNSW index on subvectors for cosine similarity search.
- **Schema evolution**: manual SQL statements executed at startup (`init_db()`) rather than Alembic, because the schema is tightly coupled to code releases and the team prefers explicit, reviewable DDL.

**Operational memory tables** (`memory_events`, `memory_chunks`, `memory_embeddings`, `memory_structured_items`, etc.) are created conditionally when `operational_memory_enabled=True`. Non-operational tables (conversations, messages, browser workspaces) are always created.

## Consequences

- **Easier**: native vector search without a separate vector database; async I/O throughout the backend; rich PostgreSQL JSONB indexing for metadata.
- **Harder**: manual migrations require discipline; `pgvector` must be installed on the Postgres instance; HNSW index build can be expensive on large datasets.
- **Risk**: schema statements in `init_db()` are idempotent but must be kept in sync with model definitions. A missing `IF NOT EXISTS` or forgotten index can degrade query performance silently.
- **Out of scope**: multi-master replication, read replicas, or automatic sharding.

## Alternatives Considered

- **SQLite + aiosqlite**: rejected due to lack of concurrent write support and no native vector indexing.
- **Dedicated vector DB (Pinecone, Weaviate)**: rejected to keep the operational surface minimal; pgvector handles current scale.

## Validation

- `docker compose up -d postgres` starts the required service.
- `@backend/tests/integration/` validates conversation CRUD and operational memory recall against a live Postgres container.
