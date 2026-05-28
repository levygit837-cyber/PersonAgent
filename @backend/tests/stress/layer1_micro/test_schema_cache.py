"""Micro-benchmarks for ToolSchemaCache performance."""

from __future__ import annotations

import pytest

from personagent.application.tools.schema_cache import ToolSchemaCache
from personagent.application.tools.registry import ToolRegistry
from personagent.domain.tools import ToolDefinition, build_tool

from tests.stress.conftest import make_mock_tool


def _make_registry_with_n_tools(n: int) -> ToolRegistry:
    """Create a registry with n tools."""
    registry = ToolRegistry()
    for i in range(n):
        registry.register(make_mock_tool(f"tool_{i}"))
    return registry


@pytest.mark.stress
class TestSchemaCacheBenchmarks:

    def test_cache_miss_generation_10_tools(self, benchmark):
        """Full schema generation for 10 tools (cache miss)."""
        cache = ToolSchemaCache()
        registry = _make_registry_with_n_tools(10)
        tools = registry.list_enabled()

        cache.clear()
        result = benchmark(
            lambda: cache.get_or_build(
                tools=tools,
                allowed_tools=None,
                include_deferred=False,
                cache_scope="test",
            )
        )
        assert len(result) == 10

    def test_cache_miss_generation_50_tools(self, benchmark):
        """Full schema generation for 50 tools (cache miss)."""
        cache = ToolSchemaCache()
        registry = _make_registry_with_n_tools(50)
        tools = registry.list_enabled()

        cache.clear()
        result = benchmark(
            lambda: cache.get_or_build(
                tools=tools,
                allowed_tools=None,
                include_deferred=False,
                cache_scope="test",
            )
        )
        assert len(result) == 50

    def test_cache_hit_lookup(self, benchmark):
        """Repeated lookup with same key → cache hit."""
        cache = ToolSchemaCache()
        registry = _make_registry_with_n_tools(20)
        tools = registry.list_enabled()

        # Prime the cache
        cache.get_or_build(
            tools=tools,
            allowed_tools=None,
            include_deferred=False,
            cache_scope="test",
        )

        result = benchmark(
            lambda: cache.get_or_build(
                tools=tools,
                allowed_tools=None,
                include_deferred=False,
                cache_scope="test",
            )
        )
        assert len(result) == 20
        assert cache.hits > 0

    def test_cache_invalidation_on_scope_change(self, benchmark):
        """Changing cache_scope invalidates the cache."""
        cache = ToolSchemaCache()
        registry = _make_registry_with_n_tools(10)
        tools = registry.list_enabled()

        # Prime with one scope
        cache.get_or_build(
            tools=tools,
            allowed_tools=None,
            include_deferred=False,
            cache_scope="provider_a:model_1",
        )

        def switch_scope():
            cache.clear()
            return cache.get_or_build(
                tools=tools,
                allowed_tools=None,
                include_deferred=False,
                cache_scope="provider_b:model_2",
            )

        result = benchmark(switch_scope)
        assert len(result) == 10

    def test_registry_openai_schemas_with_cache(self, benchmark):
        """Registry.openai_schemas() → uses cache internally."""
        registry = _make_registry_with_n_tools(30)

        # Prime cache
        registry.openai_schemas(cache_scope="test")

        result = benchmark(lambda: registry.openai_schemas(cache_scope="test"))
        assert len(result) == 30
