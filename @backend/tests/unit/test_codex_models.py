import json

from personagent.infrastructure.llm.codex.auth import CodexAuthStore
from personagent.infrastructure.llm.codex.models import CodexModelsCatalog


def test_normalize_model_filters_unsupported():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    assert catalog.normalize_model({"supported_in_api": False}, source="test") is None


def test_normalize_model_skips_empty_id():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    assert catalog.normalize_model({"slug": ""}, source="test") is None


def test_normalize_model_builds_capabilities():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    model = catalog.normalize_model(
        {
            "slug": "gpt-test",
            "display_name": "GPT-Test",
            "context_window": 128000,
            "supports_parallel_tool_calls": True,
            "supports_reasoning_summaries": True,
            "support_verbosity": True,
            "input_modalities": ["text", "vision"],
        },
        source="test",
    )
    assert model is not None
    assert model["id"] == "gpt-test"
    assert model["context_length"] == 128000
    assert "parallel_tool_calls" in model["capabilities"]
    assert "reasoning_summaries" in model["capabilities"]
    assert "verbosity" in model["capabilities"]
    assert "image_input" in model["capabilities"]


def test_ensure_core_models_adds_missing_defaults():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    models: list[dict] = []
    catalog.ensure_core_models(models, source="test")
    ids = {m["id"] for m in models}
    assert "gpt-5.5" in ids
    assert "gpt-5.4-mini" in ids


def test_filter_models_by_capability():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    data = {
        "object": "list",
        "data": [
            {"id": "a", "capabilities": ["chat"]},
            {"id": "b", "capabilities": ["chat", "tools"]},
        ],
    }
    filtered = catalog.filter_models(data, "tools")
    assert len(filtered["data"]) == 1
    assert filtered["data"][0]["id"] == "b"


def test_filter_models_none_returns_all():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    data = {"object": "list", "data": [{"id": "a"}]}
    assert catalog.filter_models(data, None) == data


def test_read_local_models_cache_honors_ttl(tmp_path):
    cache_path = tmp_path / "models_cache.json"
    cache_path.write_text(json.dumps({"models": [{"slug": "gpt-test", "display_name": "Test"}]}))

    store = CodexAuthStore(tmp_path)
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    result = catalog.read_local_models_cache(ignore_ttl=True)
    assert result is not None
    assert result["data"][0]["id"] == "gpt-test"


def test_read_local_models_cache_missing_returns_none(tmp_path):
    store = CodexAuthStore(tmp_path)
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    assert catalog.read_local_models_cache() is None


def test_normalize_models_catalog_from_list():
    store = CodexAuthStore("/tmp")
    catalog = CodexModelsCatalog(
        auth_store=store,
        base_url="https://example.com",
        context_window=272000,
        models_cache_ttl_seconds=300,
    )
    result = catalog.normalize_models_catalog(
        [{"slug": "gpt-test", "display_name": "Test", "supported_in_api": True}],
        source="test",
    )
    assert result["object"] == "list"
    assert result["provider"] == "codex"
    assert len(result["data"]) == 3  # test + 2 core models


def test_int_or_default():
    assert CodexModelsCatalog._int_or_default("42", 0) == 42
    assert CodexModelsCatalog._int_or_default(None, 10) == 10
    assert CodexModelsCatalog._int_or_default("bad", 10) == 10
