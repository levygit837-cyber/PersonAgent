"""Pure helpers and internal models for tool result budget enforcement.

These functions have no side-effects and depend only on their arguments.
They are extracted from ``tool_result_budget.py`` to keep that module
focused on the service orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.domain.tools.tool_result_budget import (
    ContentReplacementState,
    MAX_TOOL_RESULTS_PER_MESSAGE_CHARS,
    PERSISTED_OUTPUT_CLOSING_TAG,
    PERSISTED_OUTPUT_TAG,
    PREVIEW_SIZE_CHARS,
    ToolResultReplacementRecord,
    generate_preview,
)


# ---------------------------------------------------------------------------
# Internal models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ToolResultCandidate:
    """A single tool_result message eligible for budget enforcement."""

    tool_call_id: str
    content: str
    size: int


class _MutablePartition:
    """Mutable partition of candidates by prior decision state."""

    def __init__(self) -> None:
        self.must_reapply: list[_ToolResultCandidate] = []
        self.frozen: list[_ToolResultCandidate] = []
        self.fresh: list[_ToolResultCandidate] = []


# ---------------------------------------------------------------------------
# Content predicates
# ---------------------------------------------------------------------------


def _is_content_already_compacted(content: str) -> bool:
    """True when the content was already replaced with a persisted preview."""
    return content.strip().startswith(PERSISTED_OUTPUT_TAG)


def _is_content_empty(content: str) -> bool:
    return content.strip() == ""


def _content_size(content: str) -> int:
    return len(content)


# ---------------------------------------------------------------------------
# Preview message builders
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Candidate collection and grouping
# ---------------------------------------------------------------------------


def _collect_candidates_by_assistant_turn(
    rendered_messages: list[dict[str, Any]],
) -> list[list[_ToolResultCandidate]]:
    """Group tool_result messages by the assistant turn that produced them.

    A group starts after each assistant message and ends at the next assistant
    message.  This mirrors how parallel tool results are batched on the wire.
    """
    groups: list[list[_ToolResultCandidate]] = []
    current: list[_ToolResultCandidate] = []

    def flush() -> None:
        if current:
            groups.append(current)

    for msg in rendered_messages:
        role = msg.get("role")
        if role == "tool":
            content = msg.get("content") or ""
            tool_call_id = msg.get("tool_call_id") or ""
            # Skip already-compacted or empty results
            if _is_content_already_compacted(content):
                continue
            if _is_content_empty(content):
                continue
            current.append(
                _ToolResultCandidate(
                    tool_call_id=tool_call_id,
                    content=content,
                    size=_content_size(content),
                )
            )
        elif role == "assistant":
            flush()
            current = []
    flush()
    return groups


def _build_tool_name_map(
    rendered_messages: list[dict[str, Any]],
) -> dict[str, str]:
    """Walk assistant messages and map tool_call_id -> tool name.

    tool_use always precedes its tool_result, so by the time budget
    enforcement sees a result, its name is known.
    """
    name_map: dict[str, str] = {}
    for msg in rendered_messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                tid = tc.get("id")
                func = tc.get("function") or {}
                if isinstance(func, dict):
                    name = func.get("name") or ""
                else:
                    name = ""
                if tid:
                    name_map[str(tid)] = str(name)
    return name_map


# ---------------------------------------------------------------------------
# Candidate partitioning and selection
# ---------------------------------------------------------------------------


def _partition_mutable(
    candidates: list[_ToolResultCandidate],
    state: ContentReplacementState,
) -> _MutablePartition:
    partition = _MutablePartition()
    for c in candidates:
        replacement = state.get_replacement(c.tool_call_id)
        if replacement is not None:
            partition.must_reapply.append(
                _ToolResultCandidate(
                    tool_call_id=c.tool_call_id,
                    content=replacement,
                    size=len(replacement),
                )
            )
        elif state.has_seen(c.tool_call_id):
            partition.frozen.append(c)
        else:
            partition.fresh.append(c)
    return partition


def _select_fresh_to_replace(
    fresh: list[_ToolResultCandidate],
    frozen_size: int,
    limit: int,
) -> list[_ToolResultCandidate]:
    """Pick the largest fresh results to replace until the group is under budget.

    If frozen results alone already exceed the limit, we accept the overage
    (micro-compact or auto-compact will eventually clear them).
    """
    sorted_by_size = sorted(fresh, key=lambda c: c.size, reverse=True)
    selected: list[_ToolResultCandidate] = []
    remaining = frozen_size + sum(c.size for c in fresh)
    for c in sorted_by_size:
        if remaining <= limit:
            break
        selected.append(c)
        # Approximate: preview size is much smaller than original, so
        # subtracting the full size is a close-enough heuristic for selection.
        remaining -= c.size
    return selected


# ---------------------------------------------------------------------------
# Content replacement
# ---------------------------------------------------------------------------


def _replace_tool_result_contents(
    rendered_messages: list[dict[str, Any]],
    replacement_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Return a new message list where each tool_call_id in replacement_map
    has its content replaced.  Messages without replacements are passed
    through by reference.
    """
    if not replacement_map:
        return rendered_messages

    result: list[dict[str, Any]] = []
    for msg in rendered_messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue
        tool_call_id = msg.get("tool_call_id")
        if tool_call_id not in replacement_map:
            result.append(msg)
            continue
        replaced = dict(msg)
        replaced["content"] = replacement_map[tool_call_id]
        result.append(replaced)
    return result


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def _build_replacement(
    candidate: _ToolResultCandidate,
    conversation_id: str,
    artifact_storage: ArtifactStoragePort,
    tool_name_hint: str = "",
) -> tuple[str, int] | None:
    """Persist the full content to disk and return a preview message.

    Returns (preview_message, original_size) or None on persistence failure.
    """
    storage_ref = artifact_storage.persist_tool_result(
        content=candidate.content,
        conversation_id=conversation_id,
        tool_call_id=candidate.tool_call_id,
        root=None,
    )
    if storage_ref is None:
        return None

    preview_text, has_more = generate_preview(candidate.content, PREVIEW_SIZE_CHARS)
    preview_message = _build_preview_message(
        storage_ref=storage_ref,
        original_size=candidate.size,
        preview_text=preview_text,
        has_more=has_more,
    )
    return preview_message, candidate.size


async def _persist_all(
    candidates: list[_ToolResultCandidate],
    conversation_id: str,
    artifact_storage: ArtifactStoragePort,
) -> list[tuple[str, int] | None]:
    """Persist all candidates concurrently and return their previews."""
    import asyncio

    async def _one(c: _ToolResultCandidate) -> tuple[str, int] | None:
        return await _build_replacement(c, conversation_id, artifact_storage)

    return await asyncio.gather(*[_one(c) for c in candidates])


__all__ = [
    "_ToolResultCandidate",
    "_MutablePartition",
    "_is_content_already_compacted",
    "_is_content_empty",
    "_content_size",
    "_build_preview_message",
    "_collect_candidates_by_assistant_turn",
    "_build_tool_name_map",
    "_partition_mutable",
    "_select_fresh_to_replace",
    "_replace_tool_result_contents",
    "_build_replacement",
    "_persist_all",
]
