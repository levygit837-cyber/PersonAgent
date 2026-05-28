"""Individual chat message widget with Markdown rendering for agent messages."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.app import RenderableType
from textual.reactive import reactive
from textual.widgets import Static


class ChatMessage(Static):
    """A single chat bubble."""

    thinking_visible: reactive[bool] = reactive(True)
    aborted: reactive[bool] = reactive(False)

    def __init__(self, role: str, content: str, thinking: str = "", **kwargs: Any) -> None:
        self.role = role
        self._content = content
        self._thinking = thinking
        super().__init__(**kwargs)
        self.update(self._build_renderable())
        self.add_class("-user" if role == "user" else "-agent")

    def watch_thinking_visible(self, visible: bool) -> None:
        """Reactive watcher: re-render when toggle changes."""
        self.update(self._build_renderable())

    def watch_aborted(self, aborted: bool) -> None:
        """Reactive watcher: re-render when abort flag changes."""
        self.update(self._build_renderable())

    def _build_renderable(self) -> RenderableType:
        if self.role == "user":
            return Text(self._content)
        # Agent message: thinking panel + content
        parts: list[RenderableType] = []
        if self._thinking and self.thinking_visible:
            # Plain text thinking block without background panel
            parts.append(Text(self._thinking, style="dim italic"))
        if self._content:
            parts.append(Markdown(self._content))
        if self.aborted:
            parts.append(Text("(aborted)", style="red dim italic"))
        if not parts:
            return Text("")
        if len(parts) == 1:
            return parts[0]
        return Group(*parts)

    def update_content(self, content: str) -> None:
        """Update the message content (used for streaming agent responses)."""
        self._content = content
        self.update(self._build_renderable())
        self.refresh()

    def update_thinking(self, thinking: str) -> None:
        """Update the reasoning/thinking text."""
        self._thinking = thinking
        self.update(self._build_renderable())
        self.refresh()
