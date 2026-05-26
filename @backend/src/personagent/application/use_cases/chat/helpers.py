"""Pure helpers extracted from ``chat_completion.py``.

Everything in this module is a free function: no ``self``, no
implicit state, no DB or network access. The chat completion use case
wires these into the turn lifecycle, but they are reusable enough that
they can also be imported directly by tests, by debugging scripts, and
by future use cases that need the same primitives (e.g. session-export
endpoints that want to materialize plan-approval artifacts the same
way the chat loop does).

Two categories of helpers live here:

* **Detection / extraction** -- the ``_browser_target_*`` and
  ``_detect_memory_*`` families, plus :func:`is_relative_to`.
* **Conversation mutation** -- :func:`apply_workspace_metadata`,
  :func:`set_session_status`, :func:`attach_plan_approval_artifact`,
  and the after-turn metadata builders.

All names are exported without leading underscores so callers can rely
on them; the original underscore-prefixed names stay as aliases in
``chat_completion`` for backwards compatibility while the file is
being split up incrementally.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from personagent.application.use_cases.chat.messaging.state import AssistantStreamState
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.prompts.services.prompt_builder import estimate_text_tokens


def browser_target_from_context_attachments(
    attachments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first ``browser_tab`` attachment as a normalized target.

    Browser tabs are the only attachment type that becomes a per-turn
    target; the helper short-circuits on the first match and normalizes
    the various id fields (``page_id``/``window_id``/``tab_id``) so
    downstream code only has to read one shape.
    """

    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "browser_tab":
            continue
        page_id = str(
            attachment.get("page_id")
            or attachment.get("window_id")
            or attachment.get("tab_id")
            or ""
        ).strip()
        browser_id = str(attachment.get("browser_id") or "").strip()
        url = str(attachment.get("url") or "").strip()
        if not page_id and not browser_id and not url:
            continue
        return {
            "type": "browser_tab",
            "browser_id": browser_id,
            "page_id": page_id,
            "window_id": page_id,
            "tab_id": str(attachment.get("tab_id") or page_id).strip(),
            "url": url,
            "title": str(attachment.get("title") or "").strip(),
            "label": str(attachment.get("label") or "@Browser").strip(),
        }
    return None


def browser_target_reminder(target: dict[str, Any] | None) -> str | None:
    """Render the system-prompt reminder for a per-turn Browser target.

    Three shapes are emitted depending on whether the user pinned a
    specific tab, a window, or just a URL -- the LLM uses the reminder
    to keep Browser tool calls scoped to the attached resource.
    """

    if not target:
        return None
    page_id = str(target.get("page_id") or target.get("window_id") or target.get("tab_id") or "").strip()
    url = str(target.get("url") or "").strip()
    if page_id:
        return (
            "# Browser Tab Target\n\n"
            "The latest user message attached a specific shared Browser tab. For this turn, "
            "Browser tools must default to this page_id/window_id, and actions must stay on "
            "this referenced tab unless the user attaches another Browser tab.\n\n"
            "```json\n"
            + json.dumps(target, ensure_ascii=False, indent=2)
            + "\n```"
        )
    if not url:
        return (
            "# Browser Window Target\n\n"
            "The latest user message attached the shared Browser window. For this turn, "
            "Browser tools should operate inside this conversation's shared Browser workspace. "
            "Use BrowserListTabs or the current Browser workspace context when a concrete page "
            "identifier is needed.\n\n"
            "```json\n"
            + json.dumps(target, ensure_ascii=False, indent=2)
            + "\n```"
        )
    return (
        "# Browser Window Target\n\n"
        "The latest user message attached a shared Browser window or URL target. For this turn, "
        "use BrowserOpen with the target URL in this conversation's shared Browser workspace "
        "before browser work if the workspace is not already on that page.\n\n"
        "```json\n"
        + json.dumps(target, ensure_ascii=False, indent=2)
        + "\n```"
    )


_MEMORY_FILE_PATH_RE = re.compile(
    r"(?:[\w.@+-]+/)+[\w.@+-]+\.(?:py|ts|tsx|js|jsx|json|md|toml|ya?ml|css|html|sql|rs|go)"
)


def detect_memory_file_paths(message: str) -> list[str]:
    """Extract distinct file paths mentioned in a user message."""

    return list(dict.fromkeys(match.group(0) for match in _MEMORY_FILE_PATH_RE.finditer(message)))


def detect_memory_source_types(message: str) -> list[str]:
    """Heuristically tag which memory ``source_type`` buckets a turn is asking about.

    The order in which we add to ``source_types`` matters because
    ``dict.fromkeys`` preserves insertion order; that order is then used
    by the recall pipeline to bias retrieval.
    """

    normalized = message.lower()
    source_types: list[str] = []
    if re.search(r"\b(decis[aã]o|decis[õo]es|decision|decisions)\b", normalized):
        source_types.extend(["decision"])
    if re.search(r"\b(arquivo|arquivos|file|path|diff)\b", normalized):
        source_types.extend(["file_state", "file_read", "file_created", "file_edited", "diff_applied"])
    if re.search(r"\b(comando|command|shell|terminal)\b", normalized):
        source_types.extend(["command_result", "command_executed"])
    if re.search(r"\b(erro|error|falha|failure|solution|solu[cç][aã]o)\b", normalized):
        source_types.extend(["error_solution", "error_found", "solution_attempted"])
    if re.search(r"\b(resumo|summary|sess[aã]o|session)\b", normalized):
        source_types.extend(["session_summary", "operational_summary"])
    return list(dict.fromkeys(source_types))


def is_relative_to(path: Path, root: Path) -> bool:
    """Backport of :meth:`Path.is_relative_to` that never raises."""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


CONTEXT_USAGE_METADATA_KEYS: tuple[str, ...] = (
    "context_tokens_estimated",
    "context_window_tokens",
    "context_compacted",
    "prompt_tokens_estimated",
    "memory_trace",
    "memory_budget_tokens",
    "memory_budget_used",
    "memory_items_injected",
    "memory_items_omitted",
    "memory_latency_ms",
    "memory_filters_applied",
    "memory_recall_scope",
    "memory_query_intent",
    "memory_candidate_count",
    "memory_discarded_candidates",
    "memory_included_reasons",
    "memory_ranking_breakdown",
    "memory_token_usage",
)


def context_usage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Filter ``metadata`` down to the keys we surface as context-usage telemetry."""

    return {
        key: metadata[key]
        for key in CONTEXT_USAGE_METADATA_KEYS
        if metadata.get(key) is not None
    }


def context_after_turn_metadata(
    context_metadata: dict[str, Any],
    state: AssistantStreamState,
) -> dict[str, Any]:
    """Estimate the conversation's token usage *after* the current turn.

    Prefers the provider-reported total (``total_tokens`` or any of its
    camelCase / snake_case aliases). When the provider doesn't return
    one, falls back to the pre-turn estimate plus a rough re-tokenization
    of the assistant's output and tool calls.
    """

    total_tokens = usage_int(
        state.usage,
        ("total_tokens", "totalTokenCount", "total_token_count"),
    )
    if total_tokens is not None:
        return {"context_tokens_after_turn_estimated": total_tokens}

    base_tokens = optional_int(context_metadata.get("context_tokens_estimated"))
    if base_tokens is None:
        return {}

    output_tokens = usage_int(
        state.usage,
        ("completion_tokens", "output_tokens", "candidatesTokenCount", "candidates_token_count"),
    )
    if output_tokens is None:
        output_text = state.content + state.reasoning_content
        output_tokens = estimate_text_tokens(output_text)
        if state.tool_calls:
            output_tokens += estimate_text_tokens(json.dumps(state.tool_calls, ensure_ascii=False))
    return {"context_tokens_after_turn_estimated": base_tokens + max(0, output_tokens)}


def image_suffix(mime_type: str) -> str:
    """Map an image MIME type to the conventional file suffix.

    Defaults to ``.png`` because that's what models without an explicit
    encoding hint produce most often.
    """

    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    return ".png"


def usage_int(usage: dict[str, int] | None, keys: tuple[str, ...]) -> int | None:
    """Return the first integer value found under any of ``keys`` in ``usage``."""

    if not isinstance(usage, dict):
        return None
    for key in keys:
        parsed = optional_int(usage.get(key))
        if parsed is not None:
            return parsed
    return None


def optional_int(value: Any) -> int | None:
    """Coerce ``value`` to ``int``, returning ``None`` for blanks/sentinels.

    Treats both ``None`` and the literal ``"-"`` (which some provider
    payloads use to mean "no usage reported") as missing.
    """

    try:
        if value is None or value == "-":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_workspace_metadata(
    conversation: Conversation, tool_context: dict[str, Any] | None
) -> None:
    """Persist the resolved workspace root on the conversation metadata."""

    workspace_root = (tool_context or {}).get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        conversation.metadata["workspace_root"] = workspace_root.strip()


def set_session_status(conversation: Conversation, status: str) -> None:
    """Update ``conversation.metadata['session_status']`` to an allowed value.

    Silently ignores anything outside the known set so a typo in a
    caller can't leak a bogus status into the UI.
    """

    if status in {"idle", "error", "pending", "running"}:
        conversation.metadata["session_status"] = status


def attach_plan_approval_artifact(
    conversation: Conversation, state: dict[str, Any]
) -> None:
    """Stamp the latest assistant message with the plan-approval payload.

    Used when Plan Mode auto-finalizes mid-turn: the UI looks for the
    ``plan_approval`` metadata on the last assistant message to render
    the approval card.
    """

    approval_id = str(state.get("approval_id") or "")
    plan_content = str(state.get("plan_content") or "")
    if not approval_id or not plan_content:
        return
    last_assistant = next(
        (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
        None,
    )
    if last_assistant is None:
        return
    last_assistant.metadata["plan_approval"] = {
        "conversationId": str(conversation.id),
        "approvalId": approval_id,
        "planId": str(state.get("plan_id") or ""),
        "planContent": plan_content,
        "planStatus": str(state.get("status") or "awaiting_approval"),
        "feedback": state.get("feedback"),
    }


__all__ = [
    "CONTEXT_USAGE_METADATA_KEYS",
    "apply_workspace_metadata",
    "attach_plan_approval_artifact",
    "browser_target_from_context_attachments",
    "browser_target_reminder",
    "context_after_turn_metadata",
    "context_usage_metadata",
    "detect_memory_file_paths",
    "detect_memory_source_types",
    "image_suffix",
    "is_relative_to",
    "optional_int",
    "set_session_status",
    "usage_int",
]
