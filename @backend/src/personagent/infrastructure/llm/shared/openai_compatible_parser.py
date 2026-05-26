"""Helpers for OpenAI-compatible chat response normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

THINK_TAGS = (
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
    ("<reasoning>", "</reasoning>"),
)


@dataclass(slots=True)
class ThinkingTagState:
    """Streaming parser state for `<think>...</think>` content."""

    inside_think: bool = False
    pending: str = ""
    active_end_tag: str = "</think>"


def extract_reasoning_field(data: dict[str, Any]) -> str:
    """Return reasoning/thinking text from known OpenAI-compatible extensions."""
    for key in (
        "reasoning_content",
        "reasoningContent",
        "reasoning",
        "thinking_content",
        "thinkingContent",
        "thinking",
        "thoughts",
    ):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def normalize_message_content(message: dict[str, Any]) -> tuple[str, str]:
    """Split final assistant message into visible content and reasoning."""
    raw_content = message.get("content", "") or ""
    reasoning = extract_reasoning_field(message)
    visible, tagged_reasoning = split_thinking_tags(raw_content, flush=True)
    return visible, reasoning + tagged_reasoning


def accumulate_tool_call_delta(
    deltas: list[dict[str, Any]],
    accumulator: dict[int, dict[str, Any]],
) -> None:
    """Accumulate OpenAI-compatible streaming tool call deltas.

    Some providers send function names as true fragments, while others resend
    the full name in every chunk. Merge names defensively so repeated snapshots
    such as "shell" + "shell" do not become "shellshell".
    """
    for delta in deltas:
        index = int(delta.get("index", len(accumulator)))
        current = accumulator.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if delta.get("id"):
            current["id"] = delta["id"]
        if delta.get("type"):
            current["type"] = delta["type"]

        function_delta = delta.get("function") or {}
        function = current.setdefault("function", {"name": "", "arguments": ""})
        if function_delta.get("name"):
            function["name"] = _merge_streamed_name(
                str(function.get("name") or ""),
                str(function_delta["name"]),
            )
        if function_delta.get("arguments"):
            function["arguments"] = (
                str(function.get("arguments") or "") + function_delta["arguments"]
            )


def split_thinking_tags(
    text: str,
    state: ThinkingTagState | None = None,
    *,
    flush: bool = False,
) -> tuple[str, str]:
    """Split visible answer text from `<think>...</think>` regions.

    The function supports incremental streaming by keeping incomplete tag
    prefixes in `state.pending` until enough text arrives to disambiguate them.
    """
    if not text and not flush:
        return "", ""

    state = state or ThinkingTagState()
    buffer = state.pending + text
    state.pending = ""
    visible_parts: list[str] = []
    reasoning_parts: list[str] = []

    while buffer:
        if state.inside_think:
            index = _find_case_insensitive(buffer, state.active_end_tag)
            if index >= 0:
                reasoning_parts.append(buffer[:index])
                buffer = buffer[index + len(state.active_end_tag) :]
                state.inside_think = False
                state.active_end_tag = "</think>"
                continue

            safe, pending = _split_possible_suffix(buffer, state.active_end_tag)
            reasoning_parts.append(safe)
            state.pending = pending
            break

        start_match = _find_first_tag(buffer, start=True)
        end_match = _find_first_tag(buffer, start=False)
        if end_match is not None and (start_match is None or end_match[0] < start_match[0]):
            index, _, end_tag = end_match
            reasoning_parts.append(buffer[:index])
            buffer = buffer[index + len(end_tag) :]
            state.inside_think = False
            state.active_end_tag = "</think>"
            continue

        if start_match is not None:
            index, start_tag, end_tag = start_match
            visible_parts.append(buffer[:index])
            buffer = buffer[index + len(start_tag) :]
            state.inside_think = True
            state.active_end_tag = end_tag
            continue

        safe, pending = _split_possible_suffixes(buffer, [start for start, _ in THINK_TAGS])
        visible_parts.append(safe)
        state.pending = pending
        break

    if flush and state.pending:
        if state.inside_think:
            reasoning_parts.append(state.pending)
        else:
            visible_parts.append(state.pending)
        state.pending = ""

    return "".join(visible_parts), "".join(reasoning_parts)


def _merge_streamed_name(current: str, incoming: str) -> str:
    if not current:
        return incoming
    if not incoming or incoming == current or current.endswith(incoming):
        return current
    if incoming.startswith(current):
        return incoming

    max_overlap = min(len(current), len(incoming))
    for overlap in range(max_overlap, 0, -1):
        if current.endswith(incoming[:overlap]):
            return current + incoming[overlap:]
    return current + incoming


def _find_first_tag(text: str, *, start: bool) -> tuple[int, str, str] | None:
    matches: list[tuple[int, str, str]] = []
    for start_tag, end_tag in THINK_TAGS:
        pattern = start_tag if start else end_tag
        index = _find_case_insensitive(text, pattern)
        if index >= 0:
            matches.append((index, start_tag, end_tag))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])


def _find_case_insensitive(text: str, pattern: str) -> int:
    return text.lower().find(pattern)


def _split_possible_suffixes(text: str, patterns: list[str]) -> tuple[str, str]:
    candidates = [_split_possible_suffix(text, pattern) for pattern in patterns]
    return min(candidates, key=lambda item: len(item[0]))


def _split_possible_suffix(text: str, pattern: str) -> tuple[str, str]:
    max_suffix = min(len(text), len(pattern) - 1)
    lowered_text = text.lower()
    for length in range(max_suffix, 0, -1):
        suffix = lowered_text[-length:]
        if pattern.startswith(suffix):
            return text[:-length], text[-length:]
    return text, ""
