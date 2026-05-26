"""Tests for the helpers extracted from ``chat_completion.py``.

These helpers used to live as private module-level functions inside the
2.7k-line god-file; pinning their behavior here is what made the
extraction safe. Each test targets a single behavior of a single
helper so a regression names itself.
"""

from __future__ import annotations

from pathlib import Path

from personagent.application.use_cases.chat.helpers import (
    apply_workspace_metadata,
    attach_plan_approval_artifact,
    browser_target_from_context_attachments,
    browser_target_reminder,
    context_after_turn_metadata,
    context_usage_metadata,
    detect_memory_file_paths,
    detect_memory_source_types,
    image_suffix,
    is_relative_to,
    optional_int,
    set_session_status,
    usage_int,
)
from personagent.application.use_cases.chat.messaging.state import AssistantStreamState
from personagent.domain.conversation.models import Conversation, Message, Role

# ---------------------------------------------------------------------------
# Browser target helpers
# ---------------------------------------------------------------------------


def test_browser_target_from_context_attachments_returns_none_for_empty_list() -> None:
    assert browser_target_from_context_attachments([]) is None


def test_browser_target_from_context_attachments_ignores_non_browser_attachments() -> None:
    attachments = [
        {"type": "file", "path": "/tmp/x"},
        {"type": "memory", "id": "abc"},
    ]
    assert browser_target_from_context_attachments(attachments) is None


def test_browser_target_from_context_attachments_normalizes_identifiers() -> None:
    """``window_id`` falls back to ``page_id`` and vice versa."""

    attachments = [
        {
            "type": "browser_tab",
            "page_id": "page-1",
            "browser_id": "browser-2",
            "url": "https://example.com",
            "title": "Example",
        }
    ]

    target = browser_target_from_context_attachments(attachments)

    assert target is not None
    assert target["type"] == "browser_tab"
    assert target["page_id"] == "page-1"
    assert target["window_id"] == "page-1"
    assert target["tab_id"] == "page-1"
    assert target["browser_id"] == "browser-2"
    assert target["url"] == "https://example.com"
    assert target["label"] == "@Browser"


def test_browser_target_from_context_attachments_skips_empty_browser_tab() -> None:
    """A ``browser_tab`` attachment with no identifiers is not a target."""

    attachments = [{"type": "browser_tab"}]
    assert browser_target_from_context_attachments(attachments) is None


def test_browser_target_reminder_returns_none_for_missing_target() -> None:
    assert browser_target_reminder(None) is None


def test_browser_target_reminder_uses_tab_template_when_page_id_present() -> None:
    reminder = browser_target_reminder({"page_id": "p1", "url": "https://x"})
    assert reminder is not None
    assert "Browser Tab Target" in reminder


def test_browser_target_reminder_uses_window_template_when_only_window() -> None:
    """No ``page_id`` *and* no ``url`` -> the generic window reminder.

    The target dict is intentionally non-empty: ``browser_target_reminder``
    treats falsy inputs (``None`` / ``{}``) as "no attachment at all" and
    returns ``None``. The window-target branch fires when something is
    attached (e.g. a browser id) but the user didn't pin a page or URL.
    """

    reminder = browser_target_reminder({"browser_id": "browser-1"})
    assert reminder is not None
    assert "Browser Window Target" in reminder


def test_browser_target_reminder_uses_url_template_when_only_url() -> None:
    reminder = browser_target_reminder({"url": "https://example.com"})
    assert reminder is not None
    assert "BrowserOpen" in reminder


# ---------------------------------------------------------------------------
# Memory detection helpers
# ---------------------------------------------------------------------------


def test_detect_memory_file_paths_extracts_distinct_paths() -> None:
    message = "Veja src/app.py e tests/test_app.py, e também src/app.py de novo."
    assert detect_memory_file_paths(message) == ["src/app.py", "tests/test_app.py"]


def test_detect_memory_file_paths_ignores_unknown_extensions() -> None:
    assert detect_memory_file_paths("docs/spec.pdf") == []


def test_detect_memory_source_types_orders_and_dedupes() -> None:
    message = "Tive um erro lendo um arquivo durante o comando."
    result = detect_memory_source_types(message)

    # All three category groups must show up, and dict.fromkeys preserves
    # insertion order so the buckets must appear in the order they were
    # tested for.
    assert "file_state" in result
    assert "command_result" in result
    assert "error_solution" in result
    assert result == list(dict.fromkeys(result))


def test_detect_memory_source_types_returns_empty_for_unrelated_text() -> None:
    assert detect_memory_source_types("Apenas uma conversa normal.") == []


# ---------------------------------------------------------------------------
# Path / int helpers
# ---------------------------------------------------------------------------


def test_is_relative_to_true_when_inside_root() -> None:
    assert is_relative_to(Path("/tmp/foo/bar"), Path("/tmp/foo")) is True


def test_is_relative_to_false_when_outside_root() -> None:
    assert is_relative_to(Path("/tmp/other"), Path("/tmp/foo")) is False


def test_optional_int_returns_int_for_numeric_strings() -> None:
    assert optional_int("42") == 42
    assert optional_int(42) == 42


def test_optional_int_returns_none_for_blank_sentinels() -> None:
    assert optional_int(None) is None
    assert optional_int("-") is None
    assert optional_int("not a number") is None


def test_usage_int_returns_first_matching_key() -> None:
    usage = {"alpha": 7, "beta": 3}
    assert usage_int(usage, ("missing", "alpha")) == 7
    assert usage_int(usage, ("missing", "beta")) == 3


def test_usage_int_returns_none_when_no_match() -> None:
    assert usage_int({"alpha": 1}, ("beta",)) is None
    assert usage_int(None, ("alpha",)) is None


# ---------------------------------------------------------------------------
# Image suffix
# ---------------------------------------------------------------------------


def test_image_suffix_maps_known_mime_types() -> None:
    assert image_suffix("image/jpeg") == ".jpg"
    assert image_suffix("image/webp") == ".webp"
    assert image_suffix("image/png") == ".png"


def test_image_suffix_falls_back_to_png() -> None:
    assert image_suffix("application/octet-stream") == ".png"


def test_image_suffix_strips_parameters() -> None:
    assert image_suffix("image/jpeg; charset=binary") == ".jpg"


# ---------------------------------------------------------------------------
# Context usage / after-turn metadata
# ---------------------------------------------------------------------------


def test_context_usage_metadata_filters_to_known_keys_and_drops_none() -> None:
    metadata = {
        "context_tokens_estimated": 1234,
        "memory_trace": {"items": []},
        "unrelated": "value",
        "context_compacted": None,
    }
    result = context_usage_metadata(metadata)

    assert result == {
        "context_tokens_estimated": 1234,
        "memory_trace": {"items": []},
    }


def test_context_after_turn_metadata_prefers_total_tokens() -> None:
    state = AssistantStreamState(usage={"total_tokens": 999})
    assert context_after_turn_metadata({}, state) == {
        "context_tokens_after_turn_estimated": 999
    }


def test_context_after_turn_metadata_falls_back_to_estimate() -> None:
    state = AssistantStreamState()
    state.content_chunks.append("hi")
    result = context_after_turn_metadata({"context_tokens_estimated": 100}, state)

    assert "context_tokens_after_turn_estimated" in result
    assert result["context_tokens_after_turn_estimated"] >= 100


def test_context_after_turn_metadata_empty_without_total_or_base() -> None:
    state = AssistantStreamState()
    assert context_after_turn_metadata({}, state) == {}


# ---------------------------------------------------------------------------
# Conversation mutators
# ---------------------------------------------------------------------------


def test_apply_workspace_metadata_persists_workspace_root() -> None:
    conversation = Conversation()
    apply_workspace_metadata(conversation, {"workspace_root": "  /home/user/proj  "})
    assert conversation.metadata["workspace_root"] == "/home/user/proj"


def test_apply_workspace_metadata_no_op_on_missing_context() -> None:
    conversation = Conversation()
    apply_workspace_metadata(conversation, None)
    apply_workspace_metadata(conversation, {})
    assert "workspace_root" not in conversation.metadata


def test_set_session_status_accepts_known_values() -> None:
    conversation = Conversation()
    for status in ("idle", "error", "pending", "running"):
        set_session_status(conversation, status)
        assert conversation.metadata["session_status"] == status


def test_set_session_status_ignores_unknown_value() -> None:
    conversation = Conversation()
    set_session_status(conversation, "bogus")
    assert "session_status" not in conversation.metadata


def test_attach_plan_approval_artifact_requires_approval_id_and_content() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.ASSISTANT, content="ok"))

    attach_plan_approval_artifact(conversation, {"approval_id": "", "plan_content": ""})
    assert "plan_approval" not in conversation.messages[-1].metadata


def test_attach_plan_approval_artifact_stamps_last_assistant_message() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="hi"))
    conversation.add_message(Message(role=Role.ASSISTANT, content="planning"))
    conversation.add_message(Message(role=Role.USER, content="ok"))

    state = {
        "approval_id": "approve-1",
        "plan_id": "plan-1",
        "plan_content": "1. ship\n2. it",
        "status": "awaiting_approval",
        "feedback": None,
    }
    attach_plan_approval_artifact(conversation, state)

    # The last *assistant* message (not the last message overall) gets the
    # stamp.
    assistant_messages = [m for m in conversation.messages if m.role == Role.ASSISTANT]
    artifact = assistant_messages[-1].metadata["plan_approval"]
    assert artifact["approvalId"] == "approve-1"
    assert artifact["planId"] == "plan-1"
    assert artifact["planContent"] == "1. ship\n2. it"
    assert artifact["planStatus"] == "awaiting_approval"


def test_attach_plan_approval_artifact_no_assistant_message_is_safe() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="hi"))

    attach_plan_approval_artifact(
        conversation,
        {"approval_id": "a", "plan_content": "p"},
    )
    # No-op when no assistant message exists yet.
    assert all("plan_approval" not in msg.metadata for msg in conversation.messages)
