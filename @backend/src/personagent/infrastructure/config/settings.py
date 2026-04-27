"""Configuração centralizada do sistema (.env + YAML)."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação com suporte a .env e YAML."""

    model_config = SettingsConfigDict(
        env_file="/home/levybonito/Projetos/PersonAgent/.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Aplicação ---
    app_name: str = Field(default="PersonAgent", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")

    # --- PostgreSQL ---
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="personagent", alias="POSTGRES_USER")
    postgres_password: str = Field(default="personagent", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="personagent", alias="POSTGRES_DB")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")

    # --- LLM / llama.cpp ---
    llama_server_url: str = Field(default="http://localhost:8080/v1", alias="LLAMA_SERVER_URL")
    llama_server_api_key: str = Field(default="local", alias="LLAMA_SERVER_API_KEY")
    llama_model_path: str = Field(default="", alias="LLAMA_MODEL_PATH")
    llama_ctx_size: int = Field(default=131072, alias="LLAMA_CTX_SIZE")
    llama_n_gpu_layers: int = Field(default=999, alias="LLAMA_N_GPU_LAYERS")
    llama_temperature: float = Field(default=0.7, alias="LLAMA_TEMPERATURE")
    llama_max_tokens: int = Field(default=82000, alias="LLAMA_MAX_TOKENS")
    nvidia_max_tokens: int = Field(default=65536, alias="NVIDIA_MAX_TOKENS")
    vertex_max_tokens: int = Field(default=65536, alias="VERTEX_MAX_TOKENS")
    kimi_max_tokens: int = Field(default=32768, alias="KIMI_MAX_TOKENS")
    kimi_context_window: int = Field(default=262144, alias="KIMI_CONTEXT_WINDOW")
    llama_cache_type_k: str = Field(default="turbo4", alias="LLAMA_CACHE_TYPE_K")
    llama_cache_type_v: str = Field(default="turbo4", alias="LLAMA_CACHE_TYPE_V")
    llama_threads: int = Field(default=6, alias="LLAMA_THREADS")
    llama_reasoning: str = Field(default="off", alias="LLAMA_REASONING")
    llama_reasoning_budget: int = Field(default=2048, alias="LLAMA_REASONING_BUDGET")
    llama_verbose: bool = Field(default=False, alias="LLAMA_VERBOSE")
    llama_timeout_seconds: float = Field(default=120.0, alias="LLAMA_TIMEOUT_SECONDS")
    llama_stream_read_timeout_seconds: float = Field(
        default=0.0, alias="LLAMA_STREAM_READ_TIMEOUT_SECONDS"
    )
    llama_auto_start: bool = Field(default=True, alias="LLAMA_AUTO_START")
    llama_bin_path: str = Field(
        default="./@llama/llama-cpp-turboquant/build/bin/llama-server",
        alias="LLAMA_BIN_PATH",
    )

    # --- NVIDIA NIM ---
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL",
    )
    nvidia_default_model: str = Field(
        default="moonshotai/kimi-k2.5",
        alias="NVIDIA_DEFAULT_MODEL",
    )
    nvidia_timeout_seconds: float = Field(default=120.0, alias="NVIDIA_TIMEOUT_SECONDS")
    nvidia_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="NVIDIA_STREAM_READ_TIMEOUT_SECONDS",
    )
    nvidia_models_cache_ttl_seconds: int = Field(
        default=300,
        alias="NVIDIA_MODELS_CACHE_TTL_SECONDS",
    )

    # --- Google Vertex AI ---
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    vertex_auth_mode: str = Field(default="auto", alias="VERTEX_AUTH_MODE")
    vertex_project_id: str = Field(default="", alias="VERTEX_PROJECT_ID")
    vertex_location: str = Field(default="global", alias="VERTEX_LOCATION")
    vertex_default_model: str = Field(
        default="gemini-3.1-flash-lite-preview",
        alias="VERTEX_DEFAULT_MODEL",
    )
    vertex_timeout_seconds: float = Field(default=240.0, alias="VERTEX_TIMEOUT_SECONDS")
    vertex_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="VERTEX_STREAM_READ_TIMEOUT_SECONDS",
    )
    vertex_models_cache_ttl_seconds: int = Field(
        default=300,
        alias="VERTEX_MODELS_CACHE_TTL_SECONDS",
    )

    # --- Kimi Code ---
    kimi_api_key: str = Field(default="", alias="KIMI_API_KEY")
    kimi_base_url: str = Field(
        default="https://api.kimi.com/coding/v1",
        alias="KIMI_BASE_URL",
    )
    kimi_default_model: str = Field(default="kimi-for-coding", alias="KIMI_DEFAULT_MODEL")
    kimi_timeout_seconds: float = Field(default=240.0, alias="KIMI_TIMEOUT_SECONDS")
    kimi_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="KIMI_STREAM_READ_TIMEOUT_SECONDS",
    )
    kimi_anthropic_version: str = Field(
        default="2023-06-01",
        alias="KIMI_ANTHROPIC_VERSION",
    )

    # --- ChatGPT Subscription via Codex ---
    codex_home: str = Field(default="", alias="CODEX_HOME")
    codex_cli_path: str = Field(default="codex", alias="CODEX_CLI_PATH")
    codex_base_url: str = Field(
        default="https://chatgpt.com/backend-api/codex",
        alias="CODEX_BASE_URL",
    )
    codex_default_model: str = Field(default="gpt-5.5", alias="CODEX_DEFAULT_MODEL")
    codex_max_tokens: int = Field(default=65536, alias="CODEX_MAX_TOKENS")
    codex_context_window: int = Field(default=272000, alias="CODEX_CONTEXT_WINDOW")
    codex_timeout_seconds: float = Field(default=240.0, alias="CODEX_TIMEOUT_SECONDS")
    codex_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="CODEX_STREAM_READ_TIMEOUT_SECONDS",
    )
    codex_models_cache_ttl_seconds: int = Field(
        default=300,
        alias="CODEX_MODELS_CACHE_TTL_SECONDS",
    )
    codex_client_version: str = Field(default="", alias="CODEX_CLIENT_VERSION")

    # --- Ferramentas ---
    tools_enabled: bool = Field(default=True, alias="TOOLS_ENABLED")
    tools_workspace_root: str | None = Field(default=None, alias="TOOLS_WORKSPACE_ROOT")
    tools_allowed_roots: str | None = Field(default=None, alias="TOOLS_ALLOWED_ROOTS")
    tools_max_iterations: int | None = Field(
        default=None, alias="TOOLS_MAX_ITERATIONS", validate_default=True
    )

    @field_validator("tools_max_iterations", mode="before")
    @classmethod
    def parse_tools_max_iterations(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return int(v)
        return int(v)

    tools_max_concurrency: int = Field(default=4, alias="TOOLS_MAX_CONCURRENCY")
    tools_read_max_bytes: int = Field(default=128_000, alias="TOOLS_READ_MAX_BYTES")
    tools_read_default_limit: int = Field(default=1_000, alias="TOOLS_READ_DEFAULT_LIMIT")
    tools_read_max_lines: int = Field(default=1_000, alias="TOOLS_READ_MAX_LINES")
    tools_search_timeout_ms: int = Field(default=15_000, alias="TOOLS_SEARCH_TIMEOUT_MS")
    tools_shell_timeout_ms: int = Field(default=10_000, alias="TOOLS_SHELL_TIMEOUT_MS")
    tools_web_timeout_ms: int = Field(default=15_000, alias="TOOLS_WEB_TIMEOUT_MS")
    tools_web_max_bytes: int = Field(default=512_000, alias="TOOLS_WEB_MAX_BYTES")
    tools_result_max_chars: int = Field(default=20_000, alias="TOOLS_RESULT_MAX_CHARS")
    tools_result_storage_root: str | None = Field(
        default=None,
        alias="TOOLS_RESULT_STORAGE_ROOT",
    )
    tools_web_allowed_domains: str | None = Field(default=None, alias="TOOLS_WEB_ALLOWED_DOMAINS")
    tools_web_blocked_domains: str | None = Field(
        default="localhost,127.0.0.1,0.0.0.0",
        alias="TOOLS_WEB_BLOCKED_DOMAINS",
    )
    tools_skill_roots: str | None = Field(default=None, alias="TOOLS_SKILL_ROOTS")
    tools_lsp_enabled: bool = Field(default=False, alias="TOOLS_LSP_ENABLED")
    tools_mcp_enabled: bool = Field(default=True, alias="TOOLS_MCP_ENABLED")
    tools_mcp_servers_json: str | None = Field(default=None, alias="TOOLS_MCP_SERVERS_JSON")
    brief_tool_enabled: bool = Field(default=False, alias="PERSONAGENT_BRIEF_TOOL_ENABLED")
    prompt_command_roots: str | None = Field(default=None, alias="PROMPT_COMMAND_ROOTS")
    prompt_context_analysis_timeout_seconds: float = Field(
        default=4.0,
        alias="PROMPT_CONTEXT_ANALYSIS_TIMEOUT_SECONDS",
    )
    prompt_context_analysis_failure_cooldown_seconds: float = Field(
        default=60.0,
        alias="PROMPT_CONTEXT_ANALYSIS_FAILURE_COOLDOWN_SECONDS",
    )

    # --- Chat post-turn services ---
    chat_next_step_suggestions_enabled: bool = Field(
        default=False,
        alias="CHAT_NEXT_STEP_SUGGESTIONS_ENABLED",
    )
    chat_session_memory_updates_enabled: bool = Field(
        default=False,
        alias="CHAT_SESSION_MEMORY_UPDATES_ENABLED",
    )
    chat_session_title_checks_enabled: bool = Field(
        default=True,
        alias="CHAT_SESSION_TITLE_CHECKS_ENABLED",
    )
    chat_session_title_primary_provider: str = Field(
        default="nvidia",
        alias="CHAT_SESSION_TITLE_PRIMARY_PROVIDER",
    )
    chat_session_title_primary_model: str = Field(
        default="openai/gpt-oss-120b",
        alias="CHAT_SESSION_TITLE_PRIMARY_MODEL",
    )
    chat_session_title_fallback_provider: str = Field(
        default="llama",
        alias="CHAT_SESSION_TITLE_FALLBACK_PROVIDER",
    )
    chat_session_title_fallback_model: str = Field(
        default="local-model",
        alias="CHAT_SESSION_TITLE_FALLBACK_MODEL",
    )
    chat_session_title_batch_size: int = Field(
        default=6,
        alias="CHAT_SESSION_TITLE_BATCH_SIZE",
    )
    chat_session_title_scan_limit: int = Field(
        default=10_000,
        alias="CHAT_SESSION_TITLE_SCAN_LIMIT",
    )
    chat_session_title_max_history_chars: int = Field(
        default=180_000,
        alias="CHAT_SESSION_TITLE_MAX_HISTORY_CHARS",
    )
    chat_session_title_duplicate_check_interval_seconds: float = Field(
        default=300.0,
        alias="CHAT_SESSION_TITLE_DUPLICATE_CHECK_INTERVAL_SECONDS",
    )
    chat_session_title_similarity_threshold: float = Field(
        default=0.9,
        alias="CHAT_SESSION_TITLE_SIMILARITY_THRESHOLD",
    )

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
    embedding_port: int = Field(default=8081, alias="EMBEDDING_PORT")
    embedding_ctx_size: int = Field(default=8192, alias="EMBEDDING_CTX_SIZE")
    embedding_n_gpu_layers: int = Field(default=999, alias="EMBEDDING_N_GPU_LAYERS")
    embedding_threads: int = Field(default=6, alias="EMBEDDING_THREADS")
    embedding_parallel: int = Field(default=1, alias="EMBEDDING_PARALLEL")

    # --- LightPanda Browser ---
    lightpanda_enabled: bool = Field(default=True, alias="LIGHTPANDA_ENABLED")
    lightpanda_cdp_url: str = Field(
        default="http://127.0.0.1:9222",
        alias="LIGHTPANDA_CDP_URL",
    )
    browser_cdp_url: str | None = Field(default=None, alias="BROWSER_CDP_URL")
    lightpanda_timeout_ms: int = Field(default=30_000, alias="LIGHTPANDA_TIMEOUT_MS")
    lightpanda_search_base_url: str = Field(
        default="https://search.yahoo.com/search",
        alias="LIGHTPANDA_SEARCH_BASE_URL",
    )
    lightpanda_session_ttl_seconds: int = Field(
        default=900,
        alias="LIGHTPANDA_SESSION_TTL_SECONDS",
    )
    lightpanda_max_sessions: int = Field(default=32, alias="LIGHTPANDA_MAX_SESSIONS")

    @property
    def db_url(self) -> str:
        """Retorna a URL de conexão com o banco de dados."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def tool_workspace_root_path(self) -> Path:
        """Retorna o root padrão para ferramentas."""
        if self.tools_workspace_root:
            return Path(self.tools_workspace_root).expanduser()
        return get_project_root()

    @property
    def tool_allowed_root_paths(self) -> list[Path]:
        """Retorna roots permitidos para ferramentas."""
        if not self.tools_allowed_roots:
            return [self.tool_workspace_root_path]
        return [
            Path(item.strip()).expanduser()
            for item in self.tools_allowed_roots.split(",")
            if item.strip()
        ]

    @property
    def tool_web_allowed_domain_list(self) -> list[str]:
        return _split_csv(self.tools_web_allowed_domains)

    @property
    def tool_web_blocked_domain_list(self) -> list[str]:
        return _split_csv(self.tools_web_blocked_domains)

    @property
    def tool_skill_root_paths(self) -> list[Path]:
        return [Path(item).expanduser() for item in _split_csv(self.tools_skill_roots)]

    @property
    def prompt_command_root_paths(self) -> list[Path]:
        return [Path(item).expanduser() for item in _split_csv(self.prompt_command_roots)]

    @property
    def tool_mcp_server_configs(self) -> list[dict[str, Any]]:
        if not self.tools_mcp_servers_json:
            return []
        try:
            raw = json.loads(self.tools_mcp_servers_json)
        except json.JSONDecodeError:
            return []
        if isinstance(raw, dict):
            raw = raw.get("servers", [])
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        """Carrega configuração de um arquivo YAML, mesclando com variáveis de ambiente."""
        path = Path(path)
        yaml_data: dict[str, Any] = {}

        if path.exists():
            with open(path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        # Converte keys de env para lowercase para compatibilidade
        flattened: dict[str, Any] = {}
        for section, values in yaml_data.items():
            if isinstance(values, dict):
                for key, val in values.items():
                    flattened[f"{section}_{key}".lower()] = val

        process_env = cls._settings_values_from_env(os.environ)
        project_env = cls._settings_values_from_env(dotenv_values(path.parent / ".env"))

        # Mescla: defaults < YAML < ambiente herdado < .env do projeto.
        # O .env local fica por último para evitar que uma variável global/stale
        # como NVIDIA_API_KEY sobrescreva a credencial do projeto.
        merged = {**flattened, **process_env, **project_env}
        return cls(**merged, _env_file=None)

    @classmethod
    def _settings_values_from_env(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        """Converte aliases de ambiente para nomes de campos do Settings."""
        alias_to_field = {
            str(field.alias): name for name, field in cls.model_fields.items() if field.alias
        }
        result: dict[str, Any] = {}
        for key, value in values.items():
            if value is None or value == "":
                continue
            field_name = alias_to_field.get(str(key))
            if field_name:
                result[field_name] = value
        return result


def get_project_root() -> Path:
    """Retorna o diretório raiz do projeto (onde está config.yaml)."""
    return Path(__file__).parent.parent.parent.parent.parent.parent


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# Singleton global
_settings: Settings | None = None


def get_settings() -> Settings:
    """Retorna a instância singleton de Settings."""
    global _settings
    if _settings is None:
        # Tenta carregar de config.yaml primeiro, senão usa .env
        config_path = get_project_root() / "config.yaml"
        _settings = Settings.from_yaml(config_path) if config_path.exists() else Settings()
    return _settings


def reset_settings() -> None:
    """Reseta o singleton (útil para testes)."""
    global _settings
    _settings = None
