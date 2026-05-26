"""Codex model catalog normalization and caching."""

from __future__ import annotations

import json
import time
from typing import Any

from personagent.infrastructure.llm.codex.auth import CodexAuthStore


class CodexModelsCatalog:
    """Normalizes and caches Codex model listings."""

    def __init__(
        self,
        auth_store: CodexAuthStore,
        *,
        base_url: str,
        context_window: int,
        models_cache_ttl_seconds: int,
    ) -> None:
        self.auth_store = auth_store
        self.base_url = base_url
        self.context_window = context_window
        self.models_cache_ttl_seconds = models_cache_ttl_seconds

    def read_local_models_cache(self, *, ignore_ttl: bool = False) -> dict[str, Any] | None:
        path = self.auth_store.models_cache_path
        if not path.exists():
            return None
        if not ignore_ttl and self.models_cache_ttl_seconds > 0:
            age = time.time() - path.stat().st_mtime
            if age > self.models_cache_ttl_seconds:
                return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return self.normalize_models_catalog(data, source="local_cache")

    def normalize_models_catalog(self, data: Any, *, source: str) -> dict[str, Any]:
        raw_models = []
        if isinstance(data, dict):
            if isinstance(data.get("models"), list):
                raw_models = data["models"]
            elif isinstance(data.get("data"), list):
                raw_models = data["data"]
        elif isinstance(data, list):
            raw_models = data

        models = [
            normalized
            for item in raw_models
            if isinstance(item, dict)
            for normalized in [self.normalize_model(item, source=source)]
            if normalized is not None
        ]
        self.ensure_core_models(models, source=source)
        return {"object": "list", "provider": "codex", "data": models}

    def normalize_model(self, item: dict[str, Any], *, source: str) -> dict[str, Any] | None:
        if item.get("supported_in_api") is False:
            return None
        model_id = str(item.get("slug") or item.get("id") or item.get("name") or "").strip()
        if not model_id:
            return None
        label = str(item.get("display_name") or item.get("label") or model_id)
        context_length = self._int_or_default(item.get("context_window"), self.context_window)
        capabilities = ["chat", "streaming", "tools", "reasoning_chat"]
        if item.get("supports_parallel_tool_calls"):
            capabilities.append("parallel_tool_calls")
        if item.get("supports_reasoning_summaries"):
            capabilities.append("reasoning_summaries")
        if item.get("support_verbosity"):
            capabilities.append("verbosity")
        if "vision" in {str(value).lower() for value in item.get("input_modalities") or []}:
            capabilities.append("image_input")

        return {
            "id": model_id,
            "name": label,
            "provider": "codex",
            "label": label,
            "owned_by": "openai",
            "context_length": context_length,
            "capabilities": capabilities,
            "supports_streaming": True,
            "supports_reasoning": True,
            "supports_tools": True,
            "supports_thinking_budget": True,
            "supported_reasoning_levels": item.get("supported_reasoning_levels") or [
                "low",
                "medium",
                "high",
                "xhigh",
            ],
            "raw": {**item, "source": source, "endpoint": f"{self.base_url}/responses"},
        }

    def ensure_core_models(self, models: list[dict[str, Any]], *, source: str) -> None:
        existing = {str(item.get("id")) for item in models}
        for model_id, label in {
            "gpt-5.4-mini": "GPT-5.4-Mini",
            "gpt-5.5": "GPT-5.5",
        }.items():
            if model_id in existing:
                continue
            models.append(
                self.normalize_model(
                    {
                        "slug": model_id,
                        "display_name": label,
                        "context_window": self.context_window,
                        "supported_in_api": True,
                        "supported_reasoning_levels": ["low", "medium", "high", "xhigh"],
                        "supports_reasoning_summaries": True,
                        "supports_parallel_tool_calls": True,
                    },
                    source=f"{source}_fallback",
                )
            )

    def filter_models(self, catalog: dict[str, Any], capability: str | None) -> dict[str, Any]:
        if not capability:
            return catalog
        models = [
            item
            for item in catalog.get("data", [])
            if capability in (item.get("capabilities") or [])
        ]
        return {**catalog, "data": models}

    @staticmethod
    def _int_or_default(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
