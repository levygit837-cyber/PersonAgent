"""Registro de ferramentas disponíveis para o runtime."""

from __future__ import annotations

from typing import Any

from personagent.application.tools.schema_cache import ToolSchemaCache
from personagent.domain.tools import Tool


class ToolRegistry:
    """Registry simples com lookup por nome principal e aliases."""

    def __init__(
        self,
        tools: list[Tool] | None = None,
        *,
        schema_cache: ToolSchemaCache | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}
        self._schema_cache = schema_cache or ToolSchemaCache()
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        """Registra ou substitui uma ferramenta."""
        name = tool.definition.name
        self._tools[name] = tool
        for alias in tool.definition.aliases:
            self._aliases[alias] = name

    def get(self, name: str) -> Tool | None:
        """Busca uma ferramenta por nome ou alias."""
        canonical = self._aliases.get(name, name)
        return self._tools.get(canonical)

    def list_all(self) -> list[Tool]:
        """Lista todas as ferramentas registradas."""
        return list(self._tools.values())

    def list_enabled(
        self,
        allowed_tools: set[str] | None = None,
        *,
        include_deferred: bool = False,
    ) -> list[Tool]:
        """Lista ferramentas habilitadas, filtrando por allowlist opcional."""
        tools = [tool for tool in self._tools.values() if tool.is_enabled()]
        selected: list[Tool] = []
        for tool in tools:
            explicitly_allowed = self._matches_allowlist(tool, allowed_tools)
            if allowed_tools is not None and not explicitly_allowed:
                continue
            if (
                tool.definition.should_defer
                and not tool.definition.always_load
                and not include_deferred
                and not explicitly_allowed
            ):
                continue
            selected.append(tool)
        return selected

    def openai_schemas(
        self,
        allowed_tools: set[str] | None = None,
        *,
        include_deferred: bool = False,
        cache_scope: str = "default",
    ) -> list[dict[str, Any]]:
        """Retorna schemas OpenAI-compatible para envio ao modelo."""
        tools = self.list_enabled(
            allowed_tools=allowed_tools,
            include_deferred=include_deferred,
        )
        return self._schema_cache.get_or_build(
            tools=tools,
            allowed_tools=allowed_tools,
            include_deferred=include_deferred,
            cache_scope=cache_scope,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        include_disabled: bool = True,
    ) -> list[Tool]:
        """Busca ferramentas por nome, alias, grupo, descrição e hint."""
        normalized = query.strip().lower()
        if normalized.startswith("select:"):
            selected = normalized.removeprefix("select:").strip()
            tool = self.get(selected)
            return [tool] if tool is not None and (include_disabled or tool.is_enabled()) else []

        terms = [term for term in normalized.split() if term]
        scored: list[tuple[int, Tool]] = []
        for tool in self._tools.values():
            if not include_disabled and not tool.is_enabled():
                continue
            searchable = " ".join(
                [
                    tool.definition.name,
                    *tool.definition.aliases,
                    tool.definition.description,
                    tool.definition.group,
                    tool.definition.search_hint or "",
                ]
            ).lower()
            score = 1 if not terms else sum(1 for term in terms if term in searchable)
            if score:
                scored.append((score, tool))
        scored.sort(key=lambda item: (-item[0], item[1].definition.name))
        return [tool for _score, tool in scored[: max(1, limit)]]

    def clear_schema_cache(self) -> None:
        """Limpa o cache de schemas."""
        self._schema_cache.clear()

    @property
    def schema_cache(self) -> ToolSchemaCache:
        return self._schema_cache

    def _matches_allowlist(self, tool: Tool, allowed_tools: set[str] | None) -> bool:
        if allowed_tools is None:
            return False
        return tool.definition.name in allowed_tools or bool(
            set(tool.definition.aliases).intersection(allowed_tools)
        )


__all__ = ["ToolRegistry"]
