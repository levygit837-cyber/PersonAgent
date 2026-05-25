"""Shared utility functions for the blackboard decomposition.

These are zero-dependency helpers used across blackboard_json_parsing,
blackboard_scoring, and blackboard_claim_graph. Extracted here to break
circular import chains.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["_clamp_float", "_string_list"]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_string_list(item))
        return values
    if isinstance(value, str) and value.strip():
        if "," in value or ";" in value:
            return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
        return [value.strip()]
    return []


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))
