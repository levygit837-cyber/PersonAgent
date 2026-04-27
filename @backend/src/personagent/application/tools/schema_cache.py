"""Cache de schemas de ferramentas enviados ao modelo."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from personagent.domain.tools import Tool


@dataclass(slots=True)
class ToolSchemaCache:
    """Cache pequeno e determinístico para schemas OpenAI-compatible."""

    _cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get_or_build(
        self,
        *,
        tools: list[Tool],
        allowed_tools: set[str] | None,
        include_deferred: bool,
        cache_scope: str,
    ) -> list[dict[str, Any]]:
        """Retorna schemas cacheados ou constrói uma nova entrada."""
        key = self._key(
            tools=tools,
            allowed_tools=allowed_tools,
            include_deferred=include_deferred,
            cache_scope=cache_scope,
        )
        if key in self._cache:
            self.hits += 1
            return copy.deepcopy(self._cache[key])

        self.misses += 1
        schemas = [tool.definition.to_openai_tool() for tool in tools]
        self._cache[key] = copy.deepcopy(schemas)
        return schemas

    def clear(self) -> None:
        """Limpa o cache."""
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def _key(
        self,
        *,
        tools: list[Tool],
        allowed_tools: set[str] | None,
        include_deferred: bool,
        cache_scope: str,
    ) -> str:
        payload = {
            "scope": cache_scope,
            "allowed_tools": sorted(allowed_tools) if allowed_tools else None,
            "include_deferred": include_deferred,
            "tools": [
                {
                    "name": tool.definition.name,
                    "aliases": sorted(tool.definition.aliases),
                    "strict": tool.definition.strict,
                    "defer": tool.definition.should_defer,
                    "always_load": tool.definition.always_load,
                    "enabled": tool.is_enabled(),
                }
                for tool in tools
            ],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["ToolSchemaCache"]
