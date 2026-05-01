from personagent.infrastructure.config.settings import Settings


def test_project_env_overrides_inherited_nvidia_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
nvidia:
  api_key: "yaml-key"
  base_url: "https://yaml.example/v1"
  default_model: "yaml/model"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "NVIDIA_API_KEY=project-key",
                "NVIDIA_DEFAULT_MODEL=project/model",
                "NVIDIA_TIMEOUT_SECONDS=45",
                "NVIDIA_STREAM_READ_TIMEOUT_SECONDS=0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("NVIDIA_API_KEY", "stale-global-key")
    monkeypatch.setenv("NVIDIA_DEFAULT_MODEL", "stale/global-model")

    settings = Settings.from_yaml(config_path)

    assert settings.nvidia_api_key == "project-key"
    assert settings.nvidia_default_model == "project/model"
    assert settings.nvidia_timeout_seconds == 45
    assert settings.nvidia_stream_read_timeout_seconds == 0


def test_project_env_overrides_vertex_api_key_and_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
vertex:
  auth_mode: "adc"
  project_id: "yaml-project"
  location: "us-central1"
  default_model: "yaml-model"
  timeout_seconds: 45
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "GOOGLE_API_KEY=project-google-key",
                "VERTEX_AUTH_MODE=auto",
                "VERTEX_PROJECT_ID=project-env-id",
                "VERTEX_LOCATION=global",
                "VERTEX_DEFAULT_MODEL=gemini-3.1-flash-lite-preview",
                "VERTEX_TIMEOUT_SECONDS=90",
                "VERTEX_STREAM_READ_TIMEOUT_SECONDS=0",
                "VERTEX_MODELS_CACHE_TTL_SECONDS=123",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GOOGLE_API_KEY", "stale-global-google-key")
    monkeypatch.setenv("VERTEX_DEFAULT_MODEL", "stale/global-model")

    settings = Settings.from_yaml(config_path)

    assert settings.google_api_key == "project-google-key"
    assert settings.vertex_auth_mode == "auto"
    assert settings.vertex_project_id == "project-env-id"
    assert settings.vertex_location == "global"
    assert settings.vertex_default_model == "gemini-3.1-flash-lite-preview"
    assert settings.vertex_timeout_seconds == 90
    assert settings.vertex_stream_read_timeout_seconds == 0
    assert settings.vertex_models_cache_ttl_seconds == 123


def test_project_env_overrides_kimi_api_key_and_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
kimi:
  api_key: "yaml-key"
  base_url: "https://yaml.example/coding/v1"
  default_model: "yaml-kimi"
  max_tokens: 8192
  context_window: 131072
  timeout_seconds: 45
  stream_read_timeout_seconds: 10
  anthropic_version: "2023-01-01"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "KIMI_API_KEY=project-kimi-key",
                "KIMI_BASE_URL=https://api.kimi.com/coding/v1",
                "KIMI_DEFAULT_MODEL=kimi-for-coding",
                "KIMI_MAX_TOKENS=32768",
                "KIMI_CONTEXT_WINDOW=262144",
                "KIMI_TIMEOUT_SECONDS=240",
                "KIMI_STREAM_READ_TIMEOUT_SECONDS=0",
                "KIMI_ANTHROPIC_VERSION=2023-06-01",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("KIMI_API_KEY", "stale-global-kimi-key")
    monkeypatch.setenv("KIMI_DEFAULT_MODEL", "stale/global-kimi")

    settings = Settings.from_yaml(config_path)

    assert settings.kimi_api_key == "project-kimi-key"
    assert settings.kimi_base_url == "https://api.kimi.com/coding/v1"
    assert settings.kimi_default_model == "kimi-for-coding"
    assert settings.kimi_max_tokens == 32768
    assert settings.kimi_context_window == 262144
    assert settings.kimi_timeout_seconds == 240
    assert settings.kimi_stream_read_timeout_seconds == 0
    assert settings.kimi_anthropic_version == "2023-06-01"


def test_project_env_overrides_zenmux_api_key_and_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
zenmux:
  api_key: "yaml-key"
  base_url: "https://yaml.example/api/v1"
  default_model: "yaml-zenmux"
  max_tokens: 8192
  context_window: 131072
  timeout_seconds: 45
  stream_read_timeout_seconds: 10
  models_cache_ttl_seconds: 1
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "ZENMUX_API_KEY=project-zenmux-key",
                "ZENMUX_BASE_URL=https://zenmux.ai/api/v1",
                "ZENMUX_DEFAULT_MODEL=deepseek/deepseek-v4-flash-free",
                "ZENMUX_MAX_TOKENS=65536",
                "ZENMUX_CONTEXT_WINDOW=1000000",
                "ZENMUX_TIMEOUT_SECONDS=240",
                "ZENMUX_STREAM_READ_TIMEOUT_SECONDS=0",
                "ZENMUX_MODELS_CACHE_TTL_SECONDS=300",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ZENMUX_API_KEY", "stale-global-zenmux-key")
    monkeypatch.setenv("ZENMUX_DEFAULT_MODEL", "stale/global-zenmux")

    settings = Settings.from_yaml(config_path)

    assert settings.zenmux_api_key == "project-zenmux-key"
    assert settings.zenmux_base_url == "https://zenmux.ai/api/v1"
    assert settings.zenmux_default_model == "deepseek/deepseek-v4-flash-free"
    assert settings.zenmux_max_tokens == 65536
    assert settings.zenmux_context_window == 1_000_000
    assert settings.zenmux_timeout_seconds == 240
    assert settings.zenmux_stream_read_timeout_seconds == 0
    assert settings.zenmux_models_cache_ttl_seconds == 300


def test_project_env_overrides_codex_subscription_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
codex:
  home: "/tmp/yaml-codex"
  cli_path: "yaml-codex"
  base_url: "https://yaml.example/backend-api/codex"
  default_model: "yaml-model"
  max_tokens: 8192
  context_window: 131072
  timeout_seconds: 45
  stream_read_timeout_seconds: 10
  models_cache_ttl_seconds: 1
  client_version: "0.1.0"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "CODEX_HOME=/tmp/project-codex",
                "CODEX_CLI_PATH=project-codex",
                "CODEX_BASE_URL=https://chatgpt.com/backend-api/codex",
                "CODEX_DEFAULT_MODEL=gpt-5.5",
                "CODEX_MAX_TOKENS=65536",
                "CODEX_CONTEXT_WINDOW=272000",
                "CODEX_TIMEOUT_SECONDS=240",
                "CODEX_STREAM_READ_TIMEOUT_SECONDS=0",
                "CODEX_MODELS_CACHE_TTL_SECONDS=300",
                "CODEX_CLIENT_VERSION=0.124.0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("CODEX_HOME", "/tmp/stale-codex")
    monkeypatch.setenv("CODEX_DEFAULT_MODEL", "stale-model")

    settings = Settings.from_yaml(config_path)

    assert settings.codex_home == "/tmp/project-codex"
    assert settings.codex_cli_path == "project-codex"
    assert settings.codex_base_url == "https://chatgpt.com/backend-api/codex"
    assert settings.codex_default_model == "gpt-5.5"
    assert settings.codex_max_tokens == 65536
    assert settings.codex_context_window == 272000
    assert settings.codex_timeout_seconds == 240
    assert settings.codex_stream_read_timeout_seconds == 0
    assert settings.codex_models_cache_ttl_seconds == 300
    assert settings.codex_client_version == "0.124.0"


def test_lightpanda_settings_defaults(monkeypatch):
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("LLAMA_HOST", raising=False)
    monkeypatch.delenv("EMBEDDING_HOST", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_host == "127.0.0.1"
    assert settings.llama_host == "127.0.0.1"
    assert settings.embedding_host == "127.0.0.1"
    assert settings.personagent_action_approval_secret == ""
    assert settings.personagent_action_approval_secret_path == "~/.cache/personagent/action_approval_secret"
    assert settings.lightpanda_enabled is True
    assert settings.lightpanda_cdp_url == "http://127.0.0.1:9222"
    assert settings.browser_cdp_url is None
    assert settings.lightpanda_timeout_ms == 30_000
    assert settings.lightpanda_search_base_url == "https://search.yahoo.com/search"
    assert settings.personagent_artifact_root == "~/.cache/personagent/artifacts"
    assert settings.tools_result_max_chars == 60_000
    assert settings.lightpanda_session_ttl_seconds == 600
    assert settings.lightpanda_max_sessions == 12
    assert settings.personagent_browser_page_cache_ttl_seconds == 1_800
    assert settings.personagent_browser_page_cache_per_conversation == 8
    assert settings.personagent_browser_page_cache_global_entries == 128
    assert settings.personagent_browser_render_cache_entries == 16
    assert settings.personagent_browser_render_cache_ttl_seconds == 180
    assert settings.personagent_browser_css_cache_entries == 256
    assert settings.personagent_browser_css_cache_ttl_seconds == 900
    assert settings.prompt_context_analysis_timeout_seconds == 12
    assert settings.prompt_context_analysis_long_timeout_seconds == 30
    assert settings.prompt_context_analysis_failure_cooldown_seconds == 15
    assert settings.prompt_context_analysis_long_context_chars == 200_000
    assert settings.prompt_context_analysis_max_payload_chars == 24_000


def test_chat_post_turn_llm_services_default_off():
    settings = Settings(_env_file=None)

    assert settings.chat_next_step_suggestions_enabled is False
    assert settings.chat_session_memory_updates_enabled is False
