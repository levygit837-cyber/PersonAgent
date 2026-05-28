"""Smoke tests for the TUI ChatApp."""

from __future__ import annotations

import pytest

from personagent.adapters.tui.app import ChatApp


@pytest.fixture
def app() -> ChatApp:
    return ChatApp(base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_app_mounts(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        assert pilot.app is app
        assert app.query_one("#chat-container") is not None
        assert app.query_one("#input-bar") is not None
        assert app.query_one("#model-label") is not None
        assert app.query_one("#streaming-indicator") is not None


@pytest.mark.asyncio
async def test_input_submission(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        input_bar = app.query_one("#input-bar")
        input_bar.text = "Hello"
        await pilot.press("enter")
        assert input_bar.text == ""
