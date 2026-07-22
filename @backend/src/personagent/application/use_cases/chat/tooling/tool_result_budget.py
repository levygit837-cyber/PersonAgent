"""Aggregate tool result budget enforcement (Layer 2).

Operates on rendered OpenAI-shaped messages BEFORE they are sent to the LLM.
Groups tool results by assistant-turn boundary, enforces a 200K char aggregate
limit per group, and replaces the largest *fresh* results with previews.

State is tracked via ContentReplacementState so the same preview is re-applied
byte-identically across turns (prompt cache stability).  Original conversation
messages are NOT mutated — the budget is a render-time transformation.
"""

from __future__ import annotations

from typing import Any

from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.tools.tool_result_budget import (
    ContentReplacementState,
    MAX_TOOL_RESULTS_PER_MESSAGE_CHARS,
    ToolResultReplacementRecord,
    reconstruct_content_replacement_state,
)

from .tool_result_budget_helpers import (
    _MutablePartition,
    _ToolResultCandidate,
    _build_tool_name_map,
    _collect_candidates_by_assistant_turn,
    _partition_mutable,
    _persist_all,
    _replace_tool_result_contents,
    _select_fresh_to_replace,
)


class ToolResultBudgetService:
    """Enforces per-message aggregate tool result budget."""

    def __init__(self, artifact_storage: ArtifactStoragePort | None = None) -> None:
        self._artifact_storage = artifact_storage

    # ---- Public API -----------------------------------------------------

    async def enforce_budget(
        self,
        rendered_messages: list[dict[str, Any]],
        conversation: Conversation,
        state: ContentReplacementState,
        skip_tool_names: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[ToolResultReplacementRecord]]:
        """Apply aggregate budget enforcement to rendered messages.

        Returns the budget-adjusted message list and any *new* replacement
        records made this call (for persistence to conversation metadata).
        """
        if self._artifact_storage is None:
            return rendered_messages, []

        skip_tool_names = skip_tool_names or set()

        # Build tool_call_id -> tool_name map from assistant messages so we can
        # skip tools with infinite caps.
        name_by_tool_call_id = _build_tool_name_map(rendered_messages)
        should_skip = lambda tid: (name_by_tool_call_id.get(tid) or "") in skip_tool_names

        candidates_by_group = _collect_candidates_by_assistant_turn(rendered_messages)
        limit = MAX_TOOL_RESULTS_PER_MESSAGE_CHARS

        replacement_map: dict[str, str] = {}
        to_persist: list[_ToolResultCandidate] = []
        newly_replaced: list[ToolResultReplacementRecord] = []
        groups_over_budget = 0
        reapplied_count = 0

        for candidates in candidates_by_group:
            partition = _partition_mutable(candidates, state)

            # Re-apply cached replacements (pure dict lookup, zero I/O)
            for c in partition.must_reapply:
                replacement_map[c.tool_call_id] = c.content
                reapplied_count += 1

            # Mark all candidates as seen so their fate is frozen
            for c in candidates:
                state.add_seen(c.tool_call_id)

            # If there are no fresh candidates, nothing new to decide
            if not partition.fresh:
                continue

            # Skip tools with infinite caps (e.g. Read). They don't count
            # toward fresh size.
            eligible = [c for c in partition.fresh if not should_skip(c.tool_call_id)]

            frozen_size = sum(c.size for c in partition.frozen)
            fresh_size = sum(c.size for c in eligible)

            selected = (
                _select_fresh_to_replace(eligible, frozen_size, limit)
                if frozen_size + fresh_size > limit
                else []
            )

            if selected:
                groups_over_budget += 1
                to_persist.extend(selected)

        if not replacement_map and not to_persist:
            return rendered_messages, []

        # Persist selected candidates concurrently
        persist_results = await _persist_all(
            to_persist,
            str(conversation.id),
            self._artifact_storage,
        )

        for candidate, replacement in zip(to_persist, persist_results):
            if replacement is None:
                # Persistence failed — the original content was already sent to
                # the model (since we're operating on rendered messages), so
                # treating it as frozen going forward is correct.
                continue
            preview_message, original_size = replacement
            replacement_map[candidate.tool_call_id] = preview_message
            state.add_replacement(candidate.tool_call_id, preview_message)
            newly_replaced.append(
                ToolResultReplacementRecord(
                    tool_call_id=candidate.tool_call_id,
                    replacement=preview_message,
                )
            )

        if not replacement_map:
            return rendered_messages, []

        adjusted = _replace_tool_result_contents(rendered_messages, replacement_map)
        return adjusted, newly_replaced

    async def apply_budget(
        self,
        rendered_messages: list[dict[str, Any]],
        conversation: Conversation,
        state: ContentReplacementState | None,
        skip_tool_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience wrapper that returns only the adjusted messages.

        New replacement records are written to ``conversation.metadata``
        automatically so they survive resume.
        """
        if state is None:
            return rendered_messages
        adjusted, newly_replaced = await self.enforce_budget(
            rendered_messages,
            conversation,
            state,
            skip_tool_names=skip_tool_names,
        )
        if newly_replaced:
            existing = conversation.metadata.get("tool_result_replacements", [])
            new_records = [
                {"tool_call_id": r.tool_call_id, "replacement": r.replacement}
                for r in newly_replaced
            ]
            if isinstance(existing, list):
                conversation.metadata["tool_result_replacements"] = [
                    *existing,
                    *new_records,
                ]
            else:
                conversation.metadata["tool_result_replacements"] = new_records
        return adjusted


def reconstruct_state_from_conversation(
    conversation: Conversation,
) -> ContentReplacementState:
    """Rebuild ContentReplacementState from conversation metadata on resume.

    Iterates all TOOL messages to populate seen_ids, then populates
    replacements from stored metadata records.
    """
    seen_ids: list[str] = []
    for msg in conversation.messages:
        if msg.role == Role.TOOL and msg.tool_call_id:
            seen_ids.append(msg.tool_call_id)

    raw_records = conversation.metadata.get("tool_result_replacements", [])
    records: list[ToolResultReplacementRecord] = []
    if isinstance(raw_records, list):
        for r in raw_records:
            if isinstance(r, dict) and "tool_call_id" in r and "replacement" in r:
                records.append(
                    ToolResultReplacementRecord(
                        tool_call_id=r["tool_call_id"],
                        replacement=r["replacement"],
                    )
                )

    return reconstruct_content_replacement_state(records, seen_ids)


__all__ = [
    "ToolResultBudgetService",
    "reconstruct_state_from_conversation",
]
