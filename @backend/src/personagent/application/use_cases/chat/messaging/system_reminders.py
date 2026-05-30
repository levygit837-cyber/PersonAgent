"""System-message augmentation helpers for the chat completion pipeline.

Extracted from ``message_preparation.py`` so that ``MessagePreparer`` stays
focused on conversation-to-messages transform and compaction, while reminder
injection lives in a dedicated, reusable module.
"""

from __future__ import annotations

from typing import Any

_FINAL_ANSWER_REMINDER = (
    "The previous provider pass stopped after tool results without a visible "
    "final answer. Use the tool results already present in the conversation "
    "and respond now with the final answer. Do not call more tools for this "
    "recovery pass."
)

_SYNTHESIS_REMINDER_PREFIX = (
    "Synthesis reminder: Use gathered tool evidence. Do not call more tools "
    "unless evidence is missing and the evidence gate allows it. Produce the "
    "requested concise final answer. Name representative files/functions and "
    "uncertainty."
)


def with_system_reminder(
    messages: list[dict[str, Any]], reminder: str
) -> list[dict[str, Any]]:
    """Append ``reminder`` to the first system message in ``messages``.

    If the first message is not a system message, prepend one.  The
    original list and dicts are **not** mutated; a copy is returned.
    """

    if messages and messages[0].get("role") == "system":
        updated = dict(messages[0])
        updated["content"] = f"{updated.get('content') or ''}\n\n{reminder}"
        return [updated, *messages[1:]]
    return [
        {"role": "system", "content": reminder},
        *messages,
    ]


def with_final_answer_reminder(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject a "respond now, do not call more tools" recovery reminder."""

    return with_system_reminder(messages, _FINAL_ANSWER_REMINDER)


def with_synthesis_reminder(
    messages: list[dict[str, Any]],
    evidence_summary: Any,
) -> list[dict[str, Any]]:
    """Inject the final-synthesis reminder for evidence-ready turns."""

    summary_text = _format_evidence_summary(evidence_summary)
    reminder = _SYNTHESIS_REMINDER_PREFIX
    if summary_text:
        reminder = f"{reminder} Evidence summary: {summary_text}"
    return with_system_reminder(messages, reminder)


def with_evidence_gate_reminder(
    messages: list[dict[str, Any]],
    reminder: str,
) -> list[dict[str, Any]]:
    """Inject an evidence-gate nudge telling the model to keep exploring."""

    return with_system_reminder(messages, reminder)


def _format_evidence_summary(evidence_summary: Any) -> str:
    """Return a compact, provider-safe evidence summary string."""

    if evidence_summary is None:
        return ""
    if isinstance(evidence_summary, str):
        return evidence_summary.strip()
    if isinstance(evidence_summary, dict):
        parts: list[str] = []
        for key in (
            "reason",
            "objective",
            "phase",
            "coverage_status",
            "read_files",
            "searched_patterns",
            "missing",
            "checklist",
        ):
            value = evidence_summary.get(key)
            if value in (None, "", [], {}, ()):  # keep the reminder concise
                continue
            parts.append(f"{key}={_compact_value(value)}")
        return "; ".join(parts)
    return str(evidence_summary).strip()


def _compact_value(value: Any) -> str:
    if isinstance(value, dict):
        items = list(value.items())[:8]
        rendered = ", ".join(f"{key}: {val}" for key, val in items)
        if len(value) > len(items):
            rendered = f"{rendered}, ..."
        return "{" + rendered + "}"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [str(item) for item in list(value)[:8]]
        rendered = ", ".join(items)
        if len(value) > len(items):
            rendered = f"{rendered}, ..."
        return "[" + rendered + "]"
    return str(value)
