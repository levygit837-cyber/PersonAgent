"""Campos de configuração do Sistema de Memória Inteligente."""

from pydantic import Field


class SettingsMemoryMixin:
    """Mixin com campos de memória operacional e semântica."""

    # --- Sistema de Memória Inteligente ---
    auto_memory_enabled: bool = Field(default=False, alias="AUTO_MEMORY_ENABLED")
    memory_recall_enabled: bool = Field(default=True, alias="MEMORY_RECALL_ENABLED")
    extract_memories_enabled: bool = Field(default=True, alias="EXTRACT_MEMORIES_ENABLED")
    auto_dream_enabled: bool = Field(default=False, alias="AUTO_DREAM_ENABLED")
    team_memory_enabled: bool = Field(default=False, alias="TEAM_MEMORY_ENABLED")
    auto_memory_directory: str | None = Field(default=None, alias="AUTO_MEMORY_DIRECTORY")
    extract_memories_throttle_turns: int = Field(default=1, alias="EXTRACT_MEMORIES_THROTTLE_TURNS")
    auto_dream_min_hours: int = Field(default=24, alias="AUTO_DREAM_MIN_HOURS")
    auto_dream_min_sessions: int = Field(default=5, alias="AUTO_DREAM_MIN_SESSIONS")
    memory_max_files: int = Field(default=200, alias="MEMORY_MAX_FILES")
    memory_max_lines_per_file: int = Field(default=200, alias="MEMORY_MAX_LINES_PER_FILE")
    memory_max_bytes_per_file: int = Field(default=25_000, alias="MEMORY_MAX_BYTES_PER_FILE")
    memory_max_recall_per_query: int = Field(default=5, alias="MEMORY_MAX_RECALL_PER_QUERY")
    memory_recall_max_tokens: int = Field(default=256, alias="MEMORY_RECALL_MAX_TOKENS")
    memory_extract_max_turns: int = Field(default=5, alias="MEMORY_EXTRACT_MAX_TURNS")
    memory_extract_max_tokens: int = Field(default=2048, alias="MEMORY_EXTRACT_MAX_TOKENS")
    operational_memory_enabled: bool = Field(default=True, alias="OPERATIONAL_MEMORY_ENABLED")
    operational_memory_capture_tools_enabled: bool = Field(
        default=True,
        alias="OPERATIONAL_MEMORY_CAPTURE_TOOLS_ENABLED",
    )
    operational_memory_recall_enabled: bool = Field(
        default=True,
        alias="OPERATIONAL_MEMORY_RECALL_ENABLED",
    )
    operational_memory_embedding_enabled: bool = Field(
        default=True,
        alias="OPERATIONAL_MEMORY_EMBEDDING_ENABLED",
    )
    operational_memory_max_capture_chars: int = Field(
        default=24_000,
        alias="OPERATIONAL_MEMORY_MAX_CAPTURE_CHARS",
    )
    operational_memory_chunk_max_chars: int = Field(
        default=4_000,
        alias="OPERATIONAL_MEMORY_CHUNK_MAX_CHARS",
    )
    operational_memory_recall_top_k: int = Field(
        default=6,
        alias="OPERATIONAL_MEMORY_RECALL_TOP_K",
    )
    operational_memory_hot_cache_size: int = Field(
        default=100,
        alias="OPERATIONAL_MEMORY_HOT_CACHE_SIZE",
    )
    operational_memory_semantic_candidate_limit: int = Field(
        default=80,
        alias="OPERATIONAL_MEMORY_SEMANTIC_CANDIDATE_LIMIT",
    )
    operational_memory_recent_candidate_limit: int = Field(
        default=40,
        alias="OPERATIONAL_MEMORY_RECENT_CANDIDATE_LIMIT",
    )
    operational_memory_context_budget_tokens: int = Field(
        default=0,
        alias="OPERATIONAL_MEMORY_CONTEXT_BUDGET_TOKENS",
    )
    operational_memory_queue_enabled: bool = Field(
        default=False,
        alias="MEMORY_QUEUE_ENABLED",
    )
    operational_memory_queue_url: str = Field(
        default="amqp://personagent:personagent_secret@127.0.0.1:5672/personagent",
        alias="MEMORY_QUEUE_URL",
    )
    operational_memory_queue_exchange: str = Field(
        default="personagent.memory",
        alias="MEMORY_QUEUE_EXCHANGE",
    )
    operational_memory_queue_name: str = Field(
        default="personagent.memory.operational.v1",
        alias="MEMORY_QUEUE_NAME",
    )
    operational_memory_queue_prefetch: int = Field(
        default=8,
        alias="MEMORY_QUEUE_PREFETCH",
    )
    operational_memory_queue_fallback_sync: bool = Field(
        default=True,
        alias="MEMORY_QUEUE_FALLBACK_SYNC",
    )
    embedding_server_url: str = Field(
        default="http://localhost:8081/v1",
        alias="EMBEDDING_SERVER_URL",
    )
    embedding_server_api_key: str = Field(default="local", alias="EMBEDDING_SERVER_API_KEY")
    embedding_model: str = Field(
        default="Qwen3-Embedding-8B-Q4_K_M.gguf",
        alias="EMBEDDING_MODEL",
    )
    embedding_model_path: str = Field(
        default="/home/levybonito/.lmstudio/models/Qwen/Qwen3-Embedding-8B-GGUF",
        alias="EMBEDDING_MODEL_PATH",
    )
    embedding_dimensions: int = Field(default=4096, alias="EMBEDDING_DIMENSIONS")
    embedding_timeout_seconds: float = Field(default=60.0, alias="EMBEDDING_TIMEOUT_SECONDS")
    embedding_auto_start: bool = Field(default=False, alias="EMBEDDING_AUTO_START")
    embedding_host: str = Field(default="127.0.0.1", alias="EMBEDDING_HOST")
    embedding_port: int = Field(default=8081, alias="EMBEDDING_PORT")
    embedding_ctx_size: int = Field(default=32768, alias="EMBEDDING_CTX_SIZE")
    embedding_n_gpu_layers: int = Field(default=999, alias="EMBEDDING_N_GPU_LAYERS")
    embedding_threads: int = Field(default=6, alias="EMBEDDING_THREADS")
    embedding_parallel: int = Field(default=1, alias="EMBEDDING_PARALLEL")
