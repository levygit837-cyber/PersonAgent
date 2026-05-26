"""Miscellaneous utility helpers for browser tools."""

from __future__ import annotations

from typing import Any

from personagent.domain.tools import ToolUseContext


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float) and not value.is_integer():
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _browser_result_max_chars(context: ToolUseContext) -> int:
    raw_limit = context.limits.get("result_max_chars")
    if raw_limit is None:
        return 60_000
    try:
        parsed = int(raw_limit)
    except (TypeError, ValueError):
        return 60_000
    return parsed if parsed > 0 else 60_000
