"""Prompt-facing memory trace helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.domain.memory.models.relevant_memory import RelevantMemory

MAX_SNIPPET_CHARS = 500
MAX_PROMPT_CHARS = 12_000


class MemoryTraceBuilder:
    """Builds a UI-safe trace of memory that entered the prompt."""

    @classmethod
    def build(
        cls,
        *,
        classic_memories: list[RelevantMemory],
        operational_package: Any | None,
        prompt_blocks: list[str],
    ) -> dict[str, Any] | None:
        classic = [cls._classic_item(memory) for memory in classic_memories]
        operational = [
            cls._operational_item(item)
            for item in (getattr(operational_package, "items", None) or [])
        ]
        total_used = len(classic) + len(operational)
        omitted_count = _int_or_zero(getattr(operational_package, "omitted_count", 0))
        if total_used <= 0 and omitted_count <= 0:
            return None

        formatted_prompt = "\n\n".join(block.strip() for block in prompt_blocks if block.strip())
        prompt_payload: dict[str, Any] = {}
        if formatted_prompt:
            prompt_payload = {
                "formatted": _truncate(formatted_prompt, MAX_PROMPT_CHARS),
                "truncated": len(formatted_prompt) > MAX_PROMPT_CHARS,
            }

        trace: dict[str, Any] = {
            "classic": classic,
            "operational": operational,
            "summary": {
                "total_used": total_used,
                "classic_count": len(classic),
                "rag_count": len(operational),
                "omitted_count": omitted_count,
                "budget_used": _int_or_zero(getattr(operational_package, "budget_used", 0)),
                "budget_tokens": _int_or_zero(getattr(operational_package, "budget_tokens", 0)),
                "latency_ms": _int_or_zero(getattr(operational_package, "latency_ms", 0)),
                "recall_scope": str(getattr(operational_package, "recall_scope", "") or ""),
                "query_intent": str(getattr(operational_package, "query_intent", "") or ""),
                "candidate_count": _int_or_zero(
                    getattr(operational_package, "candidate_count", 0)
                ),
            },
            "filters_applied": _json_safe_dict(
                getattr(operational_package, "filters_applied", None) or {}
            ),
            "included_reasons": _json_safe_list(
                getattr(operational_package, "included_reasons", None) or []
            ),
        }
        if prompt_payload:
            trace["prompt"] = prompt_payload
        return trace

    @staticmethod
    def _classic_item(memory: RelevantMemory) -> dict[str, Any]:
        path = memory.path
        return {
            "path": path,
            "name": Path(path).name,
            "header": memory.header,
            "mtime_ms": memory.mtime_ms,
            "snippet": _snippet(memory.content),
        }

    @staticmethod
    def _operational_item(item: Any) -> dict[str, Any]:
        item_type = getattr(item, "type", "")
        created_at = getattr(item, "created_at", None)
        return {
            "type": item_type.value if hasattr(item_type, "value") else str(item_type),
            "summary": str(getattr(item, "summary", "") or ""),
            "evidence": _string_list(getattr(item, "evidence", []), limit=4),
            "paths": _string_list(getattr(item, "paths", []), limit=8),
            "source_ids": _string_list(getattr(item, "source_ids", []), limit=8),
            "event_types": _string_list(getattr(item, "event_types", []), limit=8),
            "score": _float_or_zero(getattr(item, "score", 0.0)),
            "status": str(getattr(item, "status", "") or "active"),
            "trust_level": str(getattr(item, "trust_level", "") or "medium"),
            "importance": _float_or_zero(getattr(item, "importance", 0.5)),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
            "metadata": _json_safe_dict(getattr(item, "metadata", {}) or {}),
        }


def _snippet(text: str) -> str:
    compact = " ".join((text or "").split())
    return _truncate(compact, MAX_SNIPPET_CHARS)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 3)].rstrip()}..."


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in list(value)[:limit] if str(item).strip()]


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _json_safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[str(key)] = item
        elif isinstance(item, (list, tuple)):
            safe[str(key)] = [
                entry
                for entry in item
                if isinstance(entry, (str, int, float, bool)) or entry is None
            ]
        elif isinstance(item, dict):
            safe[str(key)] = _json_safe_dict(item)
        else:
            safe[str(key)] = str(item)
    return safe


def _json_safe_list(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    safe = []
    for item in value:
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe.append(item)
        elif isinstance(item, dict):
            safe.append(_json_safe_dict(item))
        else:
            safe.append(str(item))
    return safe
