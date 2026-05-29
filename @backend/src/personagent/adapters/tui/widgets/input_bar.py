"""Text input widget for the chat composer."""

from __future__ import annotations

from typing import Any

from textual.widgets import TextArea


class InputBar(TextArea):
    """Multi-line chat input that grows/shrinks with content."""

    _MIN_HEIGHT: int = 3
    _MAX_HEIGHT: int = 8

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            show_line_numbers=False,
            language=None,
            theme="css",
            **kwargs,
        )
        self.cursor_blink = False

    def on_mount(self) -> None:
        self._update_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_height()

    def _update_height(self) -> None:
        line_count = max(1, len(self.text.split("\n")))
        new_height = min(max(line_count + 1, self._MIN_HEIGHT), self._MAX_HEIGHT)
        if self.styles.height != new_height:
            self.styles.height = new_height
            self.refresh(layout=True)

    def on_blur(self) -> None:
        """Refocus immediately unless an app overlay is active."""
        app = self.app
        has_overlay = any(
            [
                getattr(app, "_command_palette", None),
                getattr(app, "_session_overlay", None),
                getattr(app, "_model_list", None),
            ]
        )
        if not has_overlay:
            self.focus()

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
