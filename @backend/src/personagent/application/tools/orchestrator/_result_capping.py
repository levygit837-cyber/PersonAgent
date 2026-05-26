"""Result size limiting and structured-result truncation."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from personagent.domain.tools import ToolResult, ToolUseContext
from personagent.infrastructure.artifacts import DEFAULT_ARTIFACT_ROOT, safe_segment

DEFAULT_TOOL_RESULT_MAX_CHARS = 60_000


class _ToolResultCappingMixin:
    """Mixin that caps tool results to configurable character limits."""

    def _cap_result(self, result: ToolResult, context: ToolUseContext) -> ToolResult:
        raw_context_limit = context.limits.get(
            "result_max_chars",
            self._config.result_max_chars or DEFAULT_TOOL_RESULT_MAX_CHARS,
        )
        try:
            context_limit = DEFAULT_TOOL_RESULT_MAX_CHARS if raw_context_limit is None else int(raw_context_limit)
        except (TypeError, ValueError):
            context_limit = DEFAULT_TOOL_RESULT_MAX_CHARS
        if context_limit <= 0:
            return result

        raw_result_limit = (
            result.metadata.get("max_result_size_chars", result.metadata.get("limit", context_limit))
            if isinstance(result.metadata, dict)
            else context_limit
        )
        try:
            result_limit = context_limit if raw_result_limit is None else int(raw_result_limit)
        except (TypeError, ValueError):
            result_limit = context_limit
        max_chars = max(1, min(result_limit, context_limit))
        if len(result.content) <= max_chars:
            return result

        storage_ref = self._persist_large_result(result, context)
        structured = self._cap_structured_result(result, max_chars, storage_ref)
        if structured is not None:
            return structured
        truncated = result.content[:max_chars] + "\n[Output truncated.]"
        metadata = {
            **result.metadata,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
            "storage_kind": "local_file" if storage_ref else None,
        }
        data = {
            **result.data,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
            "storage_kind": "local_file" if storage_ref else None,
        }
        return replace(result, content=truncated, metadata=metadata, data=data)

    def _cap_structured_result(
        self,
        result: ToolResult,
        max_chars: int,
        storage_ref: str | None,
    ) -> ToolResult | None:
        if not result.data:
            return None
        try:
            data = deepcopy(result.data)
            if not isinstance(data, dict):
                return None
            data.update(
                {
                    "truncated": True,
                    "original_chars": len(result.content),
                    "storage_ref": storage_ref,
                    "storage_kind": "local_file" if storage_ref else None,
                }
            )
            for _attempt in range(20):
                content = json.dumps(data, ensure_ascii=False)
                if len(content) <= max_chars:
                    return replace(
                        result,
                        content=content,
                        metadata={
                            **result.metadata,
                            "truncated": True,
                            "original_chars": len(result.content),
                            "storage_ref": storage_ref,
                            "storage_kind": "local_file" if storage_ref else None,
                        },
                        data=data,
                    )
                slot = self._largest_string_slot(data)
                if slot is None:
                    return None
                parent, key, value = slot
                marker = "\n[Output truncated.]"
                excess = len(content) - max_chars
                target_len = max(0, len(value) - excess - len(marker) - 200)
                if target_len >= len(value):
                    target_len = max(0, len(value) // 2)
                parent[key] = value[:target_len].rstrip() + marker
        except (TypeError, ValueError):
            return None
        return None

    def _largest_string_slot(self, value: Any) -> tuple[dict[str, Any] | list[Any], Any, str] | None:
        best: tuple[dict[str, Any] | list[Any], Any, str] | None = None

        def visit(node: Any) -> None:
            nonlocal best
            if isinstance(node, dict):
                for key, item in node.items():
                    if isinstance(item, str):
                        if best is None or len(item) > len(best[2]):
                            best = (node, key, item)
                    else:
                        visit(item)
            elif isinstance(node, list):
                for index, item in enumerate(node):
                    if isinstance(item, str):
                        if best is None or len(item) > len(best[2]):
                            best = (node, index, item)
                    else:
                        visit(item)

        visit(value)
        return best

    def _persist_large_result(self, result: ToolResult, context: ToolUseContext) -> str | None:
        raw_root = context.limits.get("tool_result_storage_root")
        root = (
            Path(str(raw_root)).expanduser()
            if raw_root
            else self._config.tool_result_storage_root or DEFAULT_ARTIFACT_ROOT
        )
        storage_dir = root / "tool-results" / safe_segment(context.conversation_id)
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
            path = storage_dir / f"{safe_segment(result.tool_call_id)}.txt"
            path.write_text(result.content, encoding="utf-8")
            return str(path)
        except OSError:
            return None
