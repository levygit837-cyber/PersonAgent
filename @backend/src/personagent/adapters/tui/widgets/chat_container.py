"""Scrollable container for chat messages."""

from __future__ import annotations

from textual.containers import VerticalScroll

from .chat_message import ChatMessage, ChatMessageRow
from .tool_call_group import MemoryRecallBlock, ToolCallGroup


class ChatContainer(VerticalScroll):
    """Scrollable chat feed that auto-scrolls to the bottom on new messages."""

    # Only auto-scroll if user is within this many rows of the bottom
    _AUTO_SCROLL_THRESHOLD: int = 3

    def _should_auto_scroll(self) -> bool:
        """Return True when the user is already near the bottom."""
        if self.max_scroll_y <= 0:
            return True
        return self.max_scroll_y - self.scroll_offset.y <= self._AUTO_SCROLL_THRESHOLD

    def _auto_scroll(self) -> None:
        """Scroll to bottom only when the user hasn't scrolled up to read history."""
        if self._should_auto_scroll():
            self.scroll_end(animate=False)

    def on_mouse_scroll_up(self, event) -> None:
        self.scroll_to(y=max(0, self.scroll_y - 5), animate=False)
        event.stop()

    def on_mouse_scroll_down(self, event) -> None:
        self.scroll_to(
            y=min(self.max_scroll_y, self.scroll_y + 5), animate=False
        )
        event.stop()

    def add_message(
        self,
        role: str,
        content: str,
        thinking: str = "",
        aborted: bool = False,
        token_count: int | None = None,
        model: str | None = None,
    ) -> ChatMessage:
        """Append a new message to the feed and scroll to it."""
        message = ChatMessage(
            role=role,
            content=content,
            thinking=thinking,
            aborted=aborted,
            token_count=token_count,
            model=model,
        )
        self.mount(ChatMessageRow(role=role, message=message))
        self._auto_scroll()
        return message

    def add_tool_group(self, *, model: str | None = None) -> ToolCallGroup:
        """Append a grouped tool-call block."""
        group = ToolCallGroup(model=model)
        self.mount(ChatMessageRow(role="agent", message=group))
        self._auto_scroll()
        return group

    def add_memory_recall(self, *, model: str | None = None) -> MemoryRecallBlock:
        """Append a memory recall block."""
        block = MemoryRecallBlock(model=model)
        self.mount(ChatMessageRow(role="agent", message=block))
        self._auto_scroll()
        return block

    def update_message(self, message: ChatMessage, content: str) -> None:
        """Update an existing message's content and scroll to bottom."""
        message.update_content(content)
        self._auto_scroll()

    def update_thinking(self, message: ChatMessage, thinking: str) -> None:
        """Update an agent message's reasoning/thinking text."""
        message.update_thinking(thinking)
        self._auto_scroll()

    def mark_aborted(self, message: ChatMessage) -> None:
        """Mark an agent message as aborted and show the red label."""
        message.aborted = True
        self._auto_scroll()
