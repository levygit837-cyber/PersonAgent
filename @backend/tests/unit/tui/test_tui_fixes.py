"""Tests for TUI fixes: thinking blocks, model card, interrupt label, scroll."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from rich.text import Text

from personagent.adapters.tui.app import ChatApp
from personagent.adapters.tui.client.types import StreamChunk
from personagent.adapters.tui.widgets.chat_message import ChatMessage, ChatMessageRow


@pytest.fixture
def app() -> ChatApp:
    return ChatApp(base_url="http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunks(*specs: tuple[str, bool, str | None]) -> list[StreamChunk]:
    """Build StreamChunk objects from (content, is_thinking, reasoning) tuples."""
    chunks = []
    for content, is_thinking, reasoning in specs:
        chunks.append(
            StreamChunk(
                content=content or None,
                is_thinking=is_thinking,
                reasoning_content=reasoning,
            )
        )
    chunks.append(StreamChunk(finish_reason="stop"))
    return chunks


def _agent_messages(app: ChatApp) -> list[ChatMessage]:
    """Return all agent ChatMessage widgets in the chat container."""
    container = app.query_one("#chat-container")
    return [m for m in container.query(ChatMessage) if m.role == "agent"]


@pytest.mark.asyncio
async def test_chat_messages_are_wrapped_in_aligned_rows(app: ChatApp) -> None:
    """Messages are wrapped in full-width rows so alignment does not stretch text."""
    async with app.run_test() as pilot:
        container = app.query_one("#chat-container")
        user_message = container.add_message("user", "short user prompt")
        agent_message = container.add_message("agent", "agent response")
        await pilot.pause()

        rows = list(container.query(ChatMessageRow))
        assert len(rows) == 2
        assert rows[0].message is user_message
        assert rows[0].has_class("-user")
        assert rows[1].message is agent_message
        assert rows[1].has_class("-agent")


# ---------------------------------------------------------------------------
# 1. Thinking blocks → separate persistent messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thinking_blocks_are_separate_messages(app: ChatApp) -> None:
    """Multiple thinking phases create separate ChatMessage widgets."""
    chunks = _make_chunks(
        ("", True, "Thinking part 1..."),
        ("Answer one.", False, None),
        ("", True, "Thinking part 2..."),
        ("Answer two.", False, None),
    )

    async def mock_stream(*args: Any, **kwargs: Any):
        for chunk in chunks:
            yield chunk

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.stream_chat_completion", mock_stream):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "test"
            await pilot.press("enter")
            await pilot.pause()

        agent_msgs = _agent_messages(app)
        assert len(agent_msgs) == 4

        thinking_msgs = [m for m in agent_msgs if m._thinking]
        assert len(thinking_msgs) == 2
        assert any("Thinking part 1" in m._thinking for m in thinking_msgs)
        assert any("Thinking part 2" in m._thinking for m in thinking_msgs)

        content_msgs = [m for m in agent_msgs if m._content]
        assert len(content_msgs) == 2
        assert any("Answer one" in m._content for m in content_msgs)
        assert any("Answer two" in m._content for m in content_msgs)


# ---------------------------------------------------------------------------
# 2. /model → floating ModelList card overlay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_card_appears_without_args(app: ChatApp) -> None:
    """/model without args opens a floating ModelList card; chat stays visible."""
    models_data = {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    async def mock_list_models(*args: Any, **kwargs: Any):
        return models_data

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.list_models", mock_list_models):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "/model"
            await pilot.press("enter")
            await pilot.pause()

        from personagent.adapters.tui.widgets.model_list import ModelList

        model_list = app.query_one("#model-list", ModelList)
        assert model_list is not None
        assert len(model_list.models) == 2
        # Chat container remains visible behind the transparent overlay
        assert app.query_one("#chat-container") is not None


@pytest.mark.asyncio
async def test_model_card_selects_model(app: ChatApp) -> None:
    """Selecting a model from the card updates model_name and closes the overlay."""
    models_data = {"data": [{"id": "provider/model-x"}, {"id": "model-y"}]}

    async def mock_list_models(*args: Any, **kwargs: Any):
        return models_data

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.list_models", mock_list_models):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "/model"
            await pilot.press("enter")
            await pilot.pause()

        # Press Enter to select the first model
        await pilot.press("enter")
        await pilot.pause()

        assert app.model_name == "provider/model-x"
        # Floating card should be removed
        assert app._model_list is None


# ---------------------------------------------------------------------------
# 3. Esc / Ctrl+C interrupt → interrupted label
# ---------------------------------------------------------------------------


def _slow_stream(*chunks: StreamChunk):
    """Return an async generator that yields chunks and checks abort signal."""
    async def gen(*args: Any, **kwargs: Any):
        signal = kwargs.get("signal")
        for chunk in chunks:
            yield chunk
        # Keep alive until aborted (short sleeps so pilot.pause doesn't spin)
        while True:
            if signal and signal.is_set():
                return
            await asyncio.sleep(0.05)
    return gen


@pytest.mark.asyncio
async def test_esc_interrupt_shows_label(app: ChatApp) -> None:
    """Pressing Esc during streaming marks the message as interrupted."""
    stream = _slow_stream(StreamChunk(content="Hello"))

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.stream_chat_completion", stream):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "test"
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("escape")
            await asyncio.sleep(0.15)

        agent_msgs = _agent_messages(app)
        assert any(m.aborted for m in agent_msgs)


@pytest.mark.asyncio
async def test_ctrl_c_interrupt_shows_label(app: ChatApp) -> None:
    """Pressing Ctrl+C during streaming marks the message as interrupted."""
    stream = _slow_stream(StreamChunk(content="Hello"))

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.stream_chat_completion", stream):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "test"
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("ctrl+c")
            await asyncio.sleep(0.15)

        agent_msgs = _agent_messages(app)
        assert any(m.aborted for m in agent_msgs)


@pytest.mark.asyncio
async def test_interrupt_before_any_message_shows_label(app: ChatApp) -> None:
    """Aborting before any chunk creates an interrupted message."""
    stream = _slow_stream()  # no chunks: stream never yields before abort

    async with app.run_test() as pilot:
        with patch("personagent.adapters.tui.app.stream_chat_completion", stream):
            input_bar = app.query_one("#input-bar")
            input_bar.text = "test"
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("escape")
            await asyncio.sleep(0.15)

        agent_msgs = _agent_messages(app)
        assert len(agent_msgs) == 1
        assert agent_msgs[0].aborted


# ---------------------------------------------------------------------------
# 4. Manual mouse scroll works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mouse_scroll_changes_offset(app: ChatApp) -> None:
    """Posting MouseScrollUp/Down events changes the chat container offset."""
    from rich.style import Style
    from textual.events import MouseScrollDown, MouseScrollUp

    async with app.run_test(size=(80, 24)) as pilot:
        container = app.query_one("#chat-container")

        # Add enough tall messages to overflow the container
        for i in range(20):
            container.add_message("agent", f"Line {i}\n" * 40)

        await pilot.pause()

        # Scroll to bottom so we have room to scroll up
        container.scroll_end(animate=False)
        await pilot.pause()

        initial_y = container.scroll_offset.y
        assert initial_y > 0, "Container should be scrollable"

        # Post MouseScrollUp to a ChatMessage (simulates mouse over a message)
        msg = container.query(ChatMessage).first()
        event_up = MouseScrollUp(
            widget=msg,
            x=5,
            y=5,
            delta_x=0,
            delta_y=3,
            button=0,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=5,
            screen_y=5,
            style=Style.null(),
        )
        msg.post_message(event_up)
        await pilot.pause()
        assert container.scroll_offset.y < initial_y, "MouseScrollUp should scroll up"

        # Post MouseScrollDown to scroll back down
        event_down = MouseScrollDown(
            widget=msg,
            x=5,
            y=5,
            delta_x=0,
            delta_y=-3,
            button=0,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=5,
            screen_y=5,
            style=Style.null(),
        )
        msg.post_message(event_down)
        await pilot.pause()
        assert container.scroll_offset.y == initial_y, "MouseScrollDown should scroll back down"


# ---------------------------------------------------------------------------
# User message token counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_message_shows_no_token_label(app: ChatApp) -> None:
    """User messages should not display a token count."""
    async with app.run_test() as pilot:
        container = app.query_one("#chat-container")
        msg = container.add_message("user", "Hello world")
        await pilot.pause()
        renderable = msg._build_renderable()
        assert isinstance(renderable, Text)
        assert "tok" not in renderable.plain


@pytest.mark.asyncio
async def test_agent_message_shows_token_label(app: ChatApp) -> None:
    """Agent messages should still display a token count."""
    async with app.run_test() as pilot:
        container = app.query_one("#chat-container")
        msg = container.add_message("agent", "Response text")
        await pilot.pause()
        # Directly check the token label helper; agent messages do track tokens
        assert msg._token_label() != ""


# ---------------------------------------------------------------------------
# Token animation step
# ---------------------------------------------------------------------------


from personagent.domain.token_counting import token_animation_step


def test_token_animation_small_targets_are_slow() -> None:
    """0→500 should tick slowly (max 5 per step) for a smooth visible count."""
    assert token_animation_step(0, 500) == 5
    assert token_animation_step(400, 500) == 5
    # Tiny gap rounds up to minimum step of 1
    assert token_animation_step(498, 500) == 1


def test_token_animation_large_targets_are_fast() -> None:
    """20k+ targets should tick faster so the animation doesn't drag."""
    # At start, gap = 20k → step capped at 600
    assert token_animation_step(0, 20_000) == 600
    # Near finish, gap = 1k → gap//15 = 66, still capped at 600 for >10k target
    assert token_animation_step(19_000, 20_000) == 66
    # Very close to finish — tiny gap rounds up to 1
    assert token_animation_step(19_990, 20_000) == 1


def test_token_animation_mid_range() -> None:
    """2k–10k targets use a medium cap."""
    assert token_animation_step(0, 2_000) == 20
    assert token_animation_step(0, 5_000) == 100
    assert token_animation_step(0, 10_000) == 100
    # gap = 1k → 1000//15 = 66, capped at 100 for 10k target
    assert token_animation_step(9_000, 10_000) == 66
