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


def test_lightpanda_settings_defaults():
    settings = Settings()

    assert settings.lightpanda_enabled is True
    assert settings.lightpanda_cdp_url == "http://127.0.0.1:9222"
    assert settings.browser_cdp_url is None
    assert settings.lightpanda_timeout_ms == 30_000
    assert settings.lightpanda_search_base_url == "https://search.yahoo.com/search"
    assert settings.lightpanda_session_ttl_seconds == 900
    assert settings.lightpanda_max_sessions == 32


def test_chat_post_turn_llm_services_default_off():
    settings = Settings()

    assert settings.chat_next_step_suggestions_enabled is False
    assert settings.chat_session_memory_updates_enabled is False
