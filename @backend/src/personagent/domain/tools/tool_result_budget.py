"""Domain models and constants for tool result budget management.

Two-layer budget system:
  1. Per-tool limit (50K chars): applied at execution time by _result_capping.
     Oversized results are spilled to disk and replaced with a preview.
  2. Per-message aggregate limit (200K chars): applied at message preparation
     time. All tool results following a single assistant call form one budget
     group. If the group exceeds the limit, the largest *fresh* results are
     replaced with previews until under budget.

ContentReplacementState tracks decisions across turns so the same preview is
re-applied byte-identically (prompt cache stability).  Once a result is *seen*
its fate is frozen: previously-replaced results always get the cached preview;
previously-unreplaced results are never replaced later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Default maximum size in characters for tool results before they get persisted
# to disk.  Individual tools may declare a lower max_result_size_chars, but
# this constant acts as a system-wide cap regardless of what tools declare.
DEFAULT_MAX_RESULT_SIZE_CHARS: int = 50_000

# Default maximum aggregate size in characters for tool_result blocks within
# a SINGLE assistant-turn group (one batch of parallel tool results).  When a
# group's blocks together exceed this, the largest fresh blocks in that group
# are persisted to disk and replaced with previews until under budget.
MAX_TOOL_RESULTS_PER_MESSAGE_CHARS: int = 200_000

# Size of the preview text shown to the model when a result is persisted.
PREVIEW_SIZE_CHARS: int = 500

# Tag used to wrap persisted output messages so the aggregate budget can
# recognise already-compacted results and skip them.
PERSISTED_OUTPUT_TAG: str = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG: str = "</persisted-output>"

# Marker text for empty tool results that would otherwise cause model
# stop-sequence issues.
EMPTY_RESULT_MARKER_TEMPLATE: str = "({tool_name} completed with no output)"


def generate_preview(content: str, max_chars: int) -> tuple[str, bool]:
    """Generate a preview of content, truncating at a newline when possible.

    Returns (preview_text, has_more).
    """
    if len(content) <= max_chars:
        return content, False

    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n")
    # If we found a newline reasonably close to the limit, use it;
    # otherwise fall back to the exact limit.
    cut_point = last_newline if last_newline > max_chars * 0.5 else max_chars
    return content[:cut_point], True


@dataclass(frozen=True, slots=True)
class ToolResultReplacementRecord:
    """Serializable record of one content-replacement decision.

    Stored in conversation metadata so decisions survive resume and the
    budget makes the same choices it made in the original session.
    """

    tool_call_id: str
    replacement: str


@dataclass
class ContentReplacementState:
    """Per-conversation-thread state for the aggregate tool result budget.

    * ``seen_ids`` — results that have passed through the budget check.
      Once seen, a result's fate is frozen for the conversation.
    * ``replacements`` — subset of seen_ids that were persisted to disk and
      replaced with previews, mapped to the exact preview string shown to the
      model.  Re-application is a dict lookup: no file I/O, guaranteed
      byte-identical, cannot fail.

    Lifecycle: one instance per conversation thread.  Reconstructed from
    conversation metadata on every ``prepare()`` call.
    """

    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)

    def clone(self) -> ContentReplacementState:
        """Return an independent copy for cache-sharing forks (subagents)."""
        return ContentReplacementState(
            seen_ids=set(self.seen_ids),
            replacements=dict(self.replacements),
        )

    def add_seen(self, tool_call_id: str) -> None:
        """Mark a result as seen (frozen)."""
        self.seen_ids.add(tool_call_id)

    def add_replacement(self, tool_call_id: str, replacement: str) -> None:
        """Mark a result as replaced and cache the preview string."""
        self.seen_ids.add(tool_call_id)
        self.replacements[tool_call_id] = replacement

    def get_replacement(self, tool_call_id: str) -> str | None:
        """Return the cached preview for a previously-replaced result."""
        return self.replacements.get(tool_call_id)

    def has_seen(self, tool_call_id: str) -> bool:
        """True if this result has already passed through budget check."""
        return tool_call_id in self.seen_ids

    def is_replaced(self, tool_call_id: str) -> bool:
        """True if this result was previously replaced with a preview."""
        return tool_call_id in self.replacements


def create_content_replacement_state() -> ContentReplacementState:
    """Return a fresh empty state."""
    return ContentReplacementState()


def reconstruct_content_replacement_state(
    records: list[ToolResultReplacementRecord],
    seen_tool_call_ids: list[str],
) -> ContentReplacementState:
    """Rebuild state from conversation metadata on resume.

    * ``records`` — stored replacement decisions.
    * ``seen_tool_call_ids`` — every tool_call_id that was ever sent to the
      model (replaced or not).  This freezes unreplaced results against future
      replacement.
    """
    state = create_content_replacement_state()
    for tool_call_id in seen_tool_call_ids:
        state.add_seen(tool_call_id)
    for record in records:
        state.add_replacement(record.tool_call_id, record.replacement)
    return state


__all__ = [
    "DEFAULT_MAX_RESULT_SIZE_CHARS",
    "MAX_TOOL_RESULTS_PER_MESSAGE_CHARS",
    "PREVIEW_SIZE_CHARS",
    "PERSISTED_OUTPUT_TAG",
    "PERSISTED_OUTPUT_CLOSING_TAG",
    "EMPTY_RESULT_MARKER_TEMPLATE",
    "ContentReplacementState",
    "ToolResultReplacementRecord",
    "create_content_replacement_state",
    "reconstruct_content_replacement_state",
    "generate_preview",
]
