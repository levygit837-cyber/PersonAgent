"""Result size limiting with structured preview and spill-to-disk persistence."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.domain.tools import ToolResult, ToolUseContext
from personagent.domain.tools.tool_result_budget import (
    DEFAULT_MAX_RESULT_SIZE_CHARS,
    PERSISTED_OUTPUT_CLOSING_TAG,
    PERSISTED_OUTPUT_TAG,
    PREVIEW_SIZE_CHARS,
)


def _is_content_empty(content: str) -> bool:
    """True when content is None, empty, or whitespace-only."""
    return content.strip() == "" if content else True


def _build_preview_message(
    storage_ref: str | None,
    original_size: int,
    preview_text: str,
    has_more: bool,
) -> str:
    """Build a structured preview message for a persisted tool result."""
    message = f"{PERSISTED_OUTPUT_TAG}\n"
    message += (
        f"Output too large ({original_size:,} chars). "
        f"Full output saved to: {storage_ref or 'disk'}\n\n"
    )
    message += f"Preview (first {PREVIEW_SIZE_CHARS:,} chars):\n"
    message += preview_text
    if has_more:
        message += "\n...\n"
    else:
        message += "\n"
    message += PERSISTED_OUTPUT_CLOSING_TAG
    return message


def _generate_preview(content: str, max_chars: int) -> tuple[str, bool]:
    """Generate a preview of content, truncating at a newline when possible."""
    if len(content) <= max_chars:
        return content, False

    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n")
    # If we found a newline reasonably close to the limit, use it;
    # otherwise fall back to the exact limit.
    cut_point = last_newline if last_newline > max_chars * 0.5 else max_chars
    return content[:cut_point], True


class _ToolResultCappingMixin:
    """Mixin that caps tool results to configurable character limits."""

    _artifact_storage: ArtifactStoragePort

    def _cap_result(self, result: ToolResult, context: ToolUseContext) -> ToolResult:
        # ---- Resolve effective limit --------------------------------------
        raw_context_limit = context.limits.get(
            "result_max_chars",
            self._config.result_max_chars or DEFAULT_MAX_RESULT_SIZE_CHARS,
        )
        try:
            context_limit = (
                DEFAULT_MAX_RESULT_SIZE_CHARS
                if raw_context_limit is None
                else int(raw_context_limit)
            )
        except (TypeError, ValueError):
            context_limit = DEFAULT_MAX_RESULT_SIZE_CHARS
        if context_limit <= 0:
            return result

        raw_result_limit = (
            result.metadata.get(
                "max_result_size_chars", result.metadata.get("limit", context_limit)
            )
            if isinstance(result.metadata, dict)
            else context_limit
        )
        try:
            result_limit = (
                context_limit if raw_result_limit is None else int(raw_result_limit)
            )
        except (TypeError, ValueError):
            result_limit = context_limit

        # ---- Skip infinite-cap tools -------------------------------------
        if not math.isfinite(result_limit):
            return result

        max_chars = max(1, min(result_limit, context_limit))
        if len(result.content) <= max_chars:
            return result

        # ---- Persist and build preview -------------------------------------
        storage_ref = self._persist_large_result(result, context)

        # Try structured truncation first (for JSON data results)
        structured = self._cap_structured_result(result, max_chars, storage_ref)
        if structured is not None:
            return structured

        # Build a human-readable preview message
        preview_text, has_more = _generate_preview(result.content, PREVIEW_SIZE_CHARS)
        preview_message = _build_preview_message(
            storage_ref=storage_ref,
            original_size=len(result.content),
            preview_text=preview_text,
            has_more=has_more,
        )

        metadata = {
            **result.metadata,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
            "storage_kind": "local_file" if storage_ref else None,
            "persisted": True,
        }
        data = {
            **result.data,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
            "storage_kind": "local_file" if storage_ref else None,
            "persisted": True,
        }
        return replace(
            result, content=preview_message, metadata=metadata, data=data
        )

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

    def _largest_string_slot(
        self, value: Any
    ) -> tuple[dict[str, Any] | list[Any], Any, str] | None:
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

    def _persist_large_result(
        self, result: ToolResult, context: ToolUseContext
    ) -> str | None:
        raw_root = context.limits.get("tool_result_storage_root")
        root = (
            Path(str(raw_root)).expanduser()
            if raw_root
            else self._config.tool_result_storage_root
        )
        return self._artifact_storage.persist_tool_result(
            content=result.content,
            conversation_id=context.conversation_id,
            tool_call_id=result.tool_call_id,
            root=root,
        )
