"""E2E tests for slash command behaviours in the TUI."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from personagent.adapters.tui.app import ChatApp
from personagent.adapters.tui.widgets import InputBar
from personagent.adapters.tui.widgets.chat_container import ChatContainer
from personagent.adapters.tui.widgets.chat_message import ChatMessage
from personagent.adapters.tui.widgets.command_palette import BUILTIN_COMMANDS, CommandPalette
from personagent.adapters.tui.widgets.session_list import SessionList


@pytest.fixture
def app() -> ChatApp:
    return ChatApp(base_url="http://localhost:8000")


async def _empty_stream(*args: Any, **kwargs: Any) -> Any:
    """Async generator that yields nothing."""
    return
    yield  # makes it an async generator


def _messages(container: ChatContainer) -> list[ChatMessage]:
    """Return rendered chat messages, ignoring layout rows."""
    return list(container.query(ChatMessage))


# ═══════════════════════════════════════════════════════════════════
# 1. Auto-complete: every command must complete with Tab
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_commands_tab_auto_complete(app: ChatApp) -> None:
    """Every builtin command auto-completes to '/<name> ' on Tab."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        for cmd in BUILTIN_COMMANDS:
            input_bar.text = f"/{cmd.name}"
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()

            assert input_bar.text == f"/{cmd.name} ", (
                f"/{cmd.name} did not auto-complete. "
                f"Got: {input_bar.text!r}"
            )

            # Reset for next command
            input_bar.text = ""
            await pilot.pause()


@pytest.mark.asyncio
async def test_palette_shows_on_slash(app: ChatApp) -> None:
    """Typing '/' mounts the palette with every command visible."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        palette = app.query_one("#command-palette", CommandPalette)
        assert palette is not None
        assert len(palette._matching_commands()) == len(BUILTIN_COMMANDS)


@pytest.mark.asyncio
async def test_palette_filters_while_typing(app: ChatApp) -> None:
    """Typing after '/' narrows the palette to matching commands."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/sess"
        await pilot.pause()

        palette = app.query_one("#command-palette", CommandPalette)
        matches = palette._matching_commands()
        # /sess matches 'sessions' (name) and 'status' (description has 'session')
        names = [m.name for m in matches]
        assert "sessions" in names
        assert "status" in names


@pytest.mark.asyncio
async def test_palette_no_match_shows_empty(app: ChatApp) -> None:
    """Typing garbage after '/' shows 'No matching commands'."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/xyz123"
        await pilot.pause()

        palette = app.query_one("#command-palette", CommandPalette)
        assert len(palette._matching_commands()) == 0


# ═══════════════════════════════════════════════════════════════════
# 2. Palette navigation with Up / Down
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_palette_navigation_down_then_up(app: ChatApp) -> None:
    """Down moves selection down; Up moves it back."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        palette = app.query_one("#command-palette", CommandPalette)
        assert palette.selected_index == 0

        await pilot.press("down")
        await pilot.pause()
        assert palette.selected_index == 1

        await pilot.press("up")
        await pilot.pause()
        assert palette.selected_index == 0


@pytest.mark.asyncio
async def test_palette_navigation_wraps_at_bounds(app: ChatApp) -> None:
    """Up at top and Down at bottom clamp instead of wrapping."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        palette = app.query_one("#command-palette", CommandPalette)
        count = len(BUILTIN_COMMANDS)

        # Already at 0; Up should stay at 0
        await pilot.press("up")
        await pilot.pause()
        assert palette.selected_index == 0

        # Move to last item
        for _ in range(count):
            await pilot.press("down")
        await pilot.pause()
        assert palette.selected_index == count - 1

        # Down at bottom stays at bottom
        await pilot.press("down")
        await pilot.pause()
        assert palette.selected_index == count - 1


@pytest.mark.asyncio
async def test_navigate_then_tab_completes_selected(app: ChatApp) -> None:
    """Down x2 + Tab should complete the third command."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        await pilot.press("down", "down")  # move to index 2
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        expected = f"/{BUILTIN_COMMANDS[2].name} "
        assert input_bar.text == expected


# ═══════════════════════════════════════════════════════════════════
# 3. Enter behaviour after auto-complete
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enter_submits_auto_completed_command(app: ChatApp) -> None:
    """After Tab produces '/help ', Enter should submit (not insert \n)."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/help"
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert input_bar.text == "/help "

        await pilot.press("enter")
        await pilot.pause()

        assert input_bar.text == ""  # cleared after submission


@pytest.mark.asyncio
async def test_shift_enter_inserts_newline_for_regular_text(app: ChatApp) -> None:
    """Shift+Enter in normal chat text inserts a newline."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "Hello world"
        await pilot.pause()

        await pilot.press("shift+enter")
        await pilot.pause()

        assert "\n" in input_bar.text


@pytest.mark.asyncio
async def test_ctrl_enter_inserts_newline_for_regular_text(app: ChatApp) -> None:
    """Ctrl+Enter in normal chat text inserts a newline."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "Hello world"
        await pilot.pause()

        await pilot.press("ctrl+enter")
        await pilot.pause()

        assert "\n" in input_bar.text


@pytest.mark.asyncio
async def test_enter_submits_slash_command_without_trailing_space(app: ChatApp) -> None:
    """Enter on '/help' (no trailing space) submits the command."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/help"
        input_bar.cursor_location = (0, len("/help"))
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert input_bar.text == ""  # cleared after submission


# ═══════════════════════════════════════════════════════════════════
# 4. /clear behaviour
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_clear_removes_messages_and_resets_conversation(app: ChatApp) -> None:
    """/clear wipes the chat and sets conversation_id to None."""
    async with app.run_test() as pilot:
        container = app.query_one("#chat-container", ChatContainer)
        container.add_message("user", "before clear")
        await pilot.pause()

        assert len(list(container.children)) > 0
        app.conversation_id = "old-id"

        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()

        assert len(list(container.children)) == 0
        assert app.conversation_id is None


# ═══════════════════════════════════════════════════════════════════
# 5. /help behaviour
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_help_shows_command_list_in_chat(app: ChatApp) -> None:
    """/help posts an agent message listing all slash commands."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/help"
        await pilot.press("enter")
        await pilot.pause()

        container = app.query_one("#chat-container", ChatContainer)
        messages = _messages(container)
        assert len(messages) > 0

        last = messages[-1]
        assert "Available slash commands" in last._content
        # every command name should appear in the help text
        for cmd in BUILTIN_COMMANDS:
            assert f"/{cmd.name}" in last._content


# ═══════════════════════════════════════════════════════════════════
# 6. /sessions behaviour
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@patch("personagent.adapters.tui.app.list_conversations")
async def test_sessions_shows_overlay(mock_list: AsyncMock, app: ChatApp) -> None:
    """/sessions fetches conversations and displays the overlay."""
    mock_list.return_value = [
        {
            "id": "sess-1",
            "title": "Alpha",
            "message_count": 3,
            "updated_at": "2024-06-01T12:00:00",
        },
        {
            "id": "sess-2",
            "title": "Beta",
            "message_count": 7,
            "updated_at": "2024-06-02T08:30:00",
        },
    ]

    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/sessions"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        session_list = app.query_one("#session-list", SessionList)
        assert session_list is not None
        assert len(session_list.sessions) == 2
        assert session_list.sessions[0]["id"] == "sess-1"


@pytest.mark.asyncio
@patch("personagent.adapters.tui.app.get_conversation")
@patch("personagent.adapters.tui.app.list_conversations")
async def test_sessions_select_switches_conversation(
    mock_list: AsyncMock,
    mock_get_conversation: AsyncMock,
    app: ChatApp,
) -> None:
    """Pressing Enter on a session row switches conversation_id."""
    mock_list.return_value = [
        {
            "id": "target-id",
            "title": "Target",
            "message_count": 1,
            "updated_at": "2024-01-01T00:00:00",
        },
    ]
    mock_get_conversation.return_value = {"messages": []}

    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/sessions"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        session_list = app.query_one("#session-list", SessionList)
        assert session_list is not None

        await pilot.press("enter")
        await pilot.pause()

        assert app.conversation_id == "target-id"
        # overlay should be removed
        assert app._session_list is None


@pytest.mark.asyncio
@patch("personagent.adapters.tui.app.list_conversations")
async def test_sessions_escape_closes_overlay(mock_list: AsyncMock, app: ChatApp) -> None:
    """Escape removes the session list without changing conversation."""
    mock_list.return_value = []

    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/sessions"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        session_list = app.query_one("#session-list", SessionList)
        assert session_list is not None

        await pilot.press("escape")
        await pilot.pause()

        # Widget should no longer be in the DOM
        assert len(list(app.query("#session-list"))) == 0


# ═══════════════════════════════════════════════════════════════════
# 7. Backend slash commands are forwarded as chat messages
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cmd_name", [
    "plan", "memory", "mcp", "context", "compact", "diff",
    "files", "branch", "doctor",
])
@pytest.mark.asyncio
async def test_backend_commands_sent_to_llm(cmd_name: str, app: ChatApp) -> None:
    """Each non-local slash command is streamed to the backend."""
    with patch(
        "personagent.adapters.tui.app.stream_chat_completion",
        side_effect=_empty_stream,
    ) as mock_stream:
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = f"/{cmd_name}"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            mock_stream.assert_called_once()
            payload = mock_stream.call_args[0][1]
            assert payload.message == f"/{cmd_name}"


# ═══════════════════════════════════════════════════════════════════
# 8. Command with arguments forwarded correctly
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_command_with_args_forwarded_to_backend(app: ChatApp) -> None:
    """/plan some task sends the full text to the backend."""
    with patch(
        "personagent.adapters.tui.app.stream_chat_completion",
        side_effect=_empty_stream,
    ) as mock_stream:
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "/plan refactor auth module"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            mock_stream.assert_called_once()
            payload = mock_stream.call_args[0][1]
            assert payload.message == "/plan refactor auth module"


# ═══════════════════════════════════════════════════════════════════
# 9. Escape and palette lifecycle
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_escape_closes_palette(app: ChatApp) -> None:
    """Escape removes the command palette."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        assert app._command_palette is not None

        await pilot.press("escape")
        await pilot.pause()

        assert app._command_palette is None


@pytest.mark.asyncio
async def test_palette_closes_when_space_typed(app: ChatApp) -> None:
    """Typing a space after the command hides the palette."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/sessions"
        await pilot.pause()

        assert app._command_palette is not None

        input_bar.text = "/sessions "
        await pilot.pause()

        assert app._command_palette is None


# ═══════════════════════════════════════════════════════════════════
# 10. Full user flow: type -> Tab -> Enter
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@patch("personagent.adapters.tui.app.list_conversations")
async def test_full_flow_tab_then_enter_clears_input(
    mock_list: AsyncMock,
    app: ChatApp,
) -> None:
    """Complete interaction: '/', Tab auto-completes, Enter submits."""
    mock_list.return_value = []
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert input_bar.text == "/sessions "

        await pilot.press("enter")
        await pilot.pause()
        assert input_bar.text == ""


@pytest.mark.asyncio
async def test_full_flow_navigate_tab_then_enter(app: ChatApp) -> None:
    """Down-arrow to /clear, Tab, Enter -> chat is cleared."""
    async with app.run_test() as pilot:
        container = app.query_one("#chat-container", ChatContainer)
        container.add_message("user", "msg")
        await pilot.pause()

        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/"
        await pilot.pause()

        # /sessions=0, /clear=1
        await pilot.press("down")
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert input_bar.text == "/clear "

        await pilot.press("enter")
        await pilot.pause()

        assert input_bar.text == ""
        assert len(list(container.children)) == 0
        assert app.conversation_id is None


# ═══════════════════════════════════════════════════════════════════
# 11. Local-only commands are handled without backend call
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cmd_name", [
    "model", "effort", "skills", "permissions", "usage", "status", "clear", "new",
])
@pytest.mark.asyncio
async def test_local_commands_not_sent_to_llm(cmd_name: str, app: ChatApp) -> None:
    """Commands with should_query=False are handled locally, not streamed."""
    with patch(
        "personagent.adapters.tui.app.stream_chat_completion",
        side_effect=_empty_stream,
    ) as mock_stream, patch(
        "personagent.adapters.tui.app.list_models",
    ) as mock_list_models:
        mock_list_models.return_value = {"data": []}
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = f"/{cmd_name}"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            mock_stream.assert_not_called()


@pytest.mark.asyncio
async def test_clear_and_new_start_fresh_session(app: ChatApp) -> None:
    """/clear and /new reset conversation_id to None."""
    async with app.run_test() as pilot:
        app.conversation_id = "old-session-id"
        input_bar = app.query_one("#input-bar", InputBar)

        input_bar.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()

        assert app.conversation_id is None

        app.conversation_id = "another-id"
        input_bar.text = "/new"
        await pilot.press("enter")
        await pilot.pause()

        assert app.conversation_id is None


@pytest.mark.asyncio
async def test_effort_sets_env_and_shows_confirmation(app: ChatApp) -> None:
    """/effort high sets PERSONAGENT_REASONING_LEVEL and posts confirmation."""
    import os
    old = os.environ.pop("PERSONAGENT_REASONING_LEVEL", None)
    try:
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "/effort high"
            await pilot.press("enter")
            await pilot.pause()

            assert os.environ.get("PERSONAGENT_REASONING_LEVEL") == "high"
            container = app.query_one("#chat-container", ChatContainer)
            messages = _messages(container)
            assert any("Reasoning effort set to `high`" in m._content for m in messages)
    finally:
        if old is not None:
            os.environ["PERSONAGENT_REASONING_LEVEL"] = old


@pytest.mark.asyncio
async def test_effort_without_args_shows_current_value(app: ChatApp) -> None:
    """/effort with no arguments shows the current reasoning effort."""
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.text = "/effort"
        await pilot.press("enter")
        await pilot.pause()

        container = app.query_one("#chat-container", ChatContainer)
        messages = _messages(container)
        assert any("Current reasoning effort" in m._content for m in messages)


@pytest.mark.asyncio
async def test_model_with_args_sets_env_and_not_sent(app: ChatApp) -> None:
    """/model provider/model sets env vars and is not sent to backend."""
    with patch(
        "personagent.adapters.tui.app.stream_chat_completion",
        side_effect=_empty_stream,
    ) as mock_stream:
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "/model openai/gpt-4o"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            mock_stream.assert_not_called()
            assert app.model_name == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_esc_during_stream_shows_aborted_label(app: ChatApp) -> None:
    """Pressing ESC while streaming marks the agent message as aborted."""
    from personagent.adapters.tui.widgets.chat_message import ChatMessage

    async def _slow_stream(*args: Any, **kwargs: Any) -> Any:
        """Yields one chunk then hangs until aborted."""
        yield MagicMock(
            content="hello",
            reasoning_content=None,
            is_thinking=False,
            finish_reason=None,
            conversation_id="test-id",
            model=None,
            tool_calls=None,
        )
        # Block until abort signal is set
        abort_event = kwargs.get("signal")
        while not abort_event.is_set():
            import asyncio
            await asyncio.sleep(0.01)

    with patch(
        "personagent.adapters.tui.app.stream_chat_completion",
        side_effect=_slow_stream,
    ):
        async with app.run_test() as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "say hello"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            # Streaming should be active with one message
            assert app.is_streaming is True
            messages = list(app.query(ChatMessage))
            assert len(messages) == 2  # user + agent
            agent_msg = messages[1]
            assert agent_msg.role == "agent"
            assert agent_msg._content == "hello"
            assert agent_msg.aborted is False

            # Press ESC to abort
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()

            assert app.is_streaming is False
            assert agent_msg.aborted is True
