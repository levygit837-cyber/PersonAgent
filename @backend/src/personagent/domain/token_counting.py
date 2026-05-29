"""Token counting helpers shared by backend surfaces.

The preferred path uses ``tiktoken`` so live UI counters are based on a
real tokenizer instead of the old chars/4 estimate. The fallback remains
small and explicit so environments that have not installed the dependency
can still run.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

_FALLBACK_TOKEN_DIVISOR = 4


@lru_cache(maxsize=64)
def _encoding(model: str | None = None) -> Any | None:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except Exception:
        return None

    model_name = (model or "").strip()
    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            pass
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def tokenizer_available(model: str | None = None) -> bool:
    """Return whether a real tokenizer is available for counting."""
    return _encoding(model) is not None


def count_text_tokens(text: str | None, *, model: str | None = None) -> int:
    """Count tokens for text using the configured tokenizer when possible."""
    if not text:
        return 0
    encoding = _encoding(model)
    if encoding is not None:
        return len(encoding.encode(text, disallowed_special=()))
    return max(1, (len(text) + _FALLBACK_TOKEN_DIVISOR - 1) // _FALLBACK_TOKEN_DIVISOR)


def count_unknown_tokens(value: Any, *, model: str | None = None) -> int:
    """Count tokens for JSON-like data without losing structure."""
    if value is None:
        return 0
    if isinstance(value, str):
        return count_text_tokens(value, model=model)
    if isinstance(value, (int, float, bool)):
        return count_text_tokens(str(value), model=model)
    try:
        return count_text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True), model=model)
    except (TypeError, ValueError):
        return count_text_tokens(str(value), model=model)


def count_tool_tokens(
    *,
    name: str | None = None,
    arguments: dict[str, Any] | None = None,
    result: str | None = None,
    data: dict[str, Any] | None = None,
    model: str | None = None,
) -> int:
    """Count the visible payload for a tool interaction."""
    return (
        count_text_tokens(name, model=model)
        + count_unknown_tokens(arguments, model=model)
        + count_text_tokens(result, model=model)
        + count_unknown_tokens(data, model=model)
    )


def format_compact_tokens(value: int | float | None) -> str:
    """Format token counts as compact labels: 999, 1k, 1.1k, 2m."""
    count = max(0, int(value or 0))
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        return _format_compact(count / 1_000, "k")
    return _format_compact(count / 1_000_000, "m")


def _format_compact(value: float, suffix: str) -> str:
    if value >= 10 or value.is_integer():
        return f"{value:.0f}{suffix}"
    return f"{value:.1f}{suffix}"


def token_animation_step(current: int, target: int) -> int:
    """Return a display step: slow & visible for small counts, fast for large."""
    gap = max(0, target - current)
    if gap <= 0:
        return 0
    step = max(1, gap // 15)
    if target <= 500:
        return min(step, 5)
    if target <= 2_000:
        return min(step, 20)
    if target <= 10_000:
        return min(step, 100)
    return min(step, 600)

