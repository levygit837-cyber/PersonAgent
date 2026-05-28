"""Text input widget for the chat composer."""

from __future__ import annotations

from typing import Any

from textual.widgets import TextArea


class InputBar(TextArea):
    """Multi-line chat input with no line numbers or syntax highlighting."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            show_line_numbers=False,
            language=None,
            theme="css",
            **kwargs,
        )
        self.cursor_blink = False

    def on_key(self, event) -> None:
        """Intercept Tab, arrows, and Enter for slash commands and message sending."""
        if event.key == "tab":
            self.app.action_palette_select()
            event.stop()
            return
        if event.key in ("up", "down"):
            if self.app._command_palette is not None:
                if event.key == "up":
                    self.app.action_palette_up()
                else:
                    self.app.action_palette_down()
                event.stop()
                return
        if event.key in ("shift+enter", "ctrl+enter"):
            # Insert newline manually (TextArea only handles plain "enter")
            self.insert("\n")
            return
        if event.key == "enter":
            # Plain Enter = submit message (or slash command)
            self.app.action_submit()
            event.stop()
            event.prevent_default()
            return
        parent_on_key = getattr(super(), "on_key", None)
        if parent_on_key is not None:
            parent_on_key(event)
