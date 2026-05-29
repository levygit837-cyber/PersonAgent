"""Individual chat message widget with Markdown rendering for agent messages."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from textual.app import RenderableType
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from personagent.domain.token_counting import (
    count_text_tokens,
    format_compact_tokens,
    token_animation_step,
)


class ChatMessage(Static):
    """A single chat bubble."""

    thinking_visible: reactive[bool] = reactive(True)
    aborted: reactive[bool] = reactive(False)

    def __init__(
        self,
        role: str,
        content: str,
        thinking: str = "",
        aborted: bool = False,
        token_count: int | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.role = role
        self._content = content
        self._thinking = thinking
        self.model = model
        self._displayed_tokens = 0
        self._target_tokens = max(
            0,
            token_count
            if token_count is not None
            else count_text_tokens(thinking or content, model=model),
        )
        self._token_timer = None
        super().__init__(**kwargs)
        self.aborted = aborted
        self.update(self._build_renderable())
        self.add_class("-user" if role == "user" else "-agent")

    def on_mount(self) -> None:
        self._token_timer = self.set_interval(0.04, self._tick_token_display)

    def on_unmount(self) -> None:
        if self._token_timer:
            self._token_timer.stop()

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
            token_label = self._token_label()
            suffix = f"  {token_label}" if token_label else ""
            parts.append(Text(f"● {self._thinking}{suffix}", style="dim italic"))
        if self._content:
            table = Table(show_header=False, show_edge=False, box=None, padding=0)
            table.add_column(width=2)
            table.add_column()
            token_label = self._token_label()
            if token_label:
                table.add_column(width=len(token_label))
                table.add_row(Text("● "), Markdown(self._content), Text(token_label, style="dim"))
            else:
                table.add_row(Text("● "), Markdown(self._content))
            parts.append(table)
        if self.aborted:
            parts.append(Text("● (interrupted)", style="red dim italic"))
        if not parts:
            return Text("")
        if len(parts) == 1:
            return parts[0]
        return Group(*parts)

    def update_content(self, content: str) -> None:
        """Update the message content (used for streaming agent responses)."""
        self._content = content
        self._set_token_target(count_text_tokens(content, model=self.model))
        self.update(self._build_renderable())
        self.refresh()

    def update_thinking(self, thinking: str) -> None:
        """Update the reasoning/thinking text."""
        self._thinking = thinking
        self._set_token_target(count_text_tokens(thinking, model=self.model))
        self.update(self._build_renderable())
        self.refresh()

    def _set_token_target(self, token_count: int) -> None:
        self._target_tokens = max(0, int(token_count or 0))
        if self._target_tokens < self._displayed_tokens:
            self._displayed_tokens = self._target_tokens

    def _tick_token_display(self) -> None:
        if self._displayed_tokens >= self._target_tokens:
            return
        self._displayed_tokens += token_animation_step(
            self._displayed_tokens,
            self._target_tokens,
        )
        self.update(self._build_renderable())

    def _token_label(self) -> str:
        if self._displayed_tokens <= 0 and self._target_tokens <= 0:
            return ""
        return f"{format_compact_tokens(self._displayed_tokens)} tok"


class ChatMessageRow(Horizontal):
    """Full-width row that positions a chat message without stretching it."""

    def __init__(self, role: str, message: ChatMessage, **kwargs: Any) -> None:
        self.role = role
        self.message = message
        super().__init__(message, **kwargs)
        self.add_class("-user" if role == "user" else "-agent")
