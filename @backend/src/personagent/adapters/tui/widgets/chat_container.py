"""Scrollable container for chat messages."""

from __future__ import annotations

from textual.containers import VerticalScroll

from .chat_message import ChatMessage


class ChatContainer(VerticalScroll):
    """Scrollable chat feed that auto-scrolls to the bottom on new messages."""

    def add_message(self, role: str, content: str, thinking: str = "") -> ChatMessage:
        """Append a new message to the feed and scroll to it."""
        message = ChatMessage(role=role, content=content, thinking=thinking)
        self.mount(message)
        self.scroll_end(animate=False)
        self.refresh(layout=True)
        return message

    def update_message(self, message: ChatMessage, content: str) -> None:
        """Update an existing message's content and scroll to bottom."""
        message.update_content(content)
        self.scroll_end(animate=False)
        self.refresh(layout=True)

    def update_thinking(self, message: ChatMessage, thinking: str) -> None:
        """Update an agent message's reasoning/thinking text."""
        message.update_thinking(thinking)
        self.scroll_end(animate=False)
        self.refresh(layout=True)

    def mark_aborted(self, message: ChatMessage) -> None:
        """Mark an agent message as aborted and show the red label."""
        message.aborted = True
        self.scroll_end(animate=False)
        self.refresh(layout=True)
