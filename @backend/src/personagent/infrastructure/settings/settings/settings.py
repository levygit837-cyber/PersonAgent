"""Configuração centralizada do sistema (.env + YAML)."""

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._browser import SettingsBrowserMixin
from ._core import get_project_root, get_settings, reset_settings
from ._memory import SettingsMemoryMixin
from ._properties import SettingsPropertiesMixin
from ._yaml import SettingsYamlMixin


class Settings(
    BaseSettings,
    SettingsBrowserMixin,
    SettingsMemoryMixin,
    SettingsPropertiesMixin,
    SettingsYamlMixin,
):
    """Configuração da aplicação com suporte a .env e YAML."""

    model_config = SettingsConfigDict(
        env_file="/home/levybonito/PersonAgent/.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Aplicação ---
    app_name: str = Field(default="PersonAgent", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    personagent_artifact_root: str = Field(
        default="~/.cache/personagent/artifacts",
        alias="PERSONAGENT_ARTIFACT_ROOT",
    )
    personagent_local_auth_enabled: bool = Field(
        default=True,
        alias="PERSONAGENT_LOCAL_AUTH_ENABLED",
    )
    personagent_local_auth_token: str = Field(
        default="",
        alias="PERSONAGENT_LOCAL_AUTH_TOKEN",
    )
    personagent_local_auth_token_path: str = Field(
        default="~/.cache/personagent/local_auth_token",
        alias="PERSONAGENT_LOCAL_AUTH_TOKEN_PATH",
    )
    personagent_workspace_grants_path: str = Field(
        default="~/.cache/personagent/workspace_grants.json",
        alias="PERSONAGENT_WORKSPACE_GRANTS_PATH",
    )
    personagent_cors_allowed_origins: str | None = Field(
        default=None,
        alias="PERSONAGENT_CORS_ALLOWED_ORIGINS",
    )
    personagent_action_approval_ttl_seconds: int = Field(
        default=300,
        alias="PERSONAGENT_ACTION_APPROVAL_TTL_SECONDS",
    )
    personagent_action_approval_secret: str = Field(
        default="",
        alias="PERSONAGENT_ACTION_APPROVAL_SECRET",
    )
    personagent_action_approval_secret_path: str = Field(
        default="~/.cache/personagent/action_approval_secret",
        alias="PERSONAGENT_ACTION_APPROVAL_SECRET_PATH",
    )
    personagent_artifact_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        alias="PERSONAGENT_ARTIFACT_TTL_SECONDS",
    )

    # --- PostgreSQL ---
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="personagent", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="personagent", alias="POSTGRES_DB")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")

    # --- LLM / llama.cpp ---
    llama_server_url: str = Field(default="http://localhost:8080/v1", alias="LLAMA_SERVER_URL")
    llama_server_api_key: str = Field(default="local", alias="LLAMA_SERVER_API_KEY")
    llama_host: str = Field(default="127.0.0.1", alias="LLAMA_HOST")
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
        default="moonshotai/kimi-k2.6",
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

    # --- DeepSeek official API ---
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="DEEPSEEK_BASE_URL",
    )
    deepseek_default_model: str = Field(
        default="deepseek-v4-flash",
        alias="DEEPSEEK_DEFAULT_MODEL",
    )
    deepseek_max_tokens: int = Field(default=65536, alias="DEEPSEEK_MAX_TOKENS")
    deepseek_context_window: int = Field(default=1_000_000, alias="DEEPSEEK_CONTEXT_WINDOW")
    deepseek_timeout_seconds: float = Field(default=240.0, alias="DEEPSEEK_TIMEOUT_SECONDS")
    deepseek_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="DEEPSEEK_STREAM_READ_TIMEOUT_SECONDS",
    )
    deepseek_models_cache_ttl_seconds: int = Field(
        default=300,
        alias="DEEPSEEK_MODELS_CACHE_TTL_SECONDS",
    )

    # --- ZenMux API ---
    zenmux_api_key: str = Field(default="", alias="ZENMUX_API_KEY")
    zenmux_base_url: str = Field(
        default="https://zenmux.ai/api/v1",
        alias="ZENMUX_BASE_URL",
    )
    zenmux_default_model: str = Field(
        default="deepseek/deepseek-v4-flash-free",
        alias="ZENMUX_DEFAULT_MODEL",
    )
    zenmux_max_tokens: int = Field(default=65536, alias="ZENMUX_MAX_TOKENS")
    zenmux_context_window: int = Field(default=1_000_000, alias="ZENMUX_CONTEXT_WINDOW")
    zenmux_timeout_seconds: float = Field(default=240.0, alias="ZENMUX_TIMEOUT_SECONDS")
    zenmux_stream_read_timeout_seconds: float = Field(
        default=0.0,
        alias="ZENMUX_STREAM_READ_TIMEOUT_SECONDS",
    )
    zenmux_models_cache_ttl_seconds: int = Field(
        default=300,
        alias="ZENMUX_MODELS_CACHE_TTL_SECONDS",
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
    vertex_context_window: int = Field(default=1_048_576, alias="VERTEX_CONTEXT_WINDOW")
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
    tools_read_max_bytes: int = Field(default=10_000_000, alias="TOOLS_READ_MAX_BYTES")
    tools_read_default_limit: int = Field(default=10_000, alias="TOOLS_READ_DEFAULT_LIMIT")
    tools_read_max_lines: int = Field(default=100_000, alias="TOOLS_READ_MAX_LINES")
    tools_search_timeout_ms: int = Field(default=15_000, alias="TOOLS_SEARCH_TIMEOUT_MS")
    tools_shell_timeout_ms: int = Field(default=10_000, alias="TOOLS_SHELL_TIMEOUT_MS")
    tools_web_timeout_ms: int = Field(default=15_000, alias="TOOLS_WEB_TIMEOUT_MS")
    tools_web_max_bytes: int = Field(default=10_000_000, alias="TOOLS_WEB_MAX_BYTES")
    tools_result_max_chars: int | None = Field(
        default=60_000, alias="TOOLS_RESULT_MAX_CHARS", validate_default=True
    )

    @field_validator("tools_result_max_chars", mode="before")
    @classmethod
    def parse_tools_result_max_chars(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            return int(v)
        return int(v)
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
        default=12.0,
        alias="PROMPT_CONTEXT_ANALYSIS_TIMEOUT_SECONDS",
    )
    prompt_context_analysis_long_timeout_seconds: float = Field(
        default=30.0,
        alias="PROMPT_CONTEXT_ANALYSIS_LONG_TIMEOUT_SECONDS",
    )
    prompt_context_analysis_failure_cooldown_seconds: float = Field(
        default=15.0,
        alias="PROMPT_CONTEXT_ANALYSIS_FAILURE_COOLDOWN_SECONDS",
    )
    prompt_context_analysis_long_context_chars: int = Field(
        default=200_000,
        alias="PROMPT_CONTEXT_ANALYSIS_LONG_CONTEXT_CHARS",
    )
    prompt_context_analysis_max_payload_chars: int = Field(
        default=24_000,
        alias="PROMPT_CONTEXT_ANALYSIS_MAX_PAYLOAD_CHARS",
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
