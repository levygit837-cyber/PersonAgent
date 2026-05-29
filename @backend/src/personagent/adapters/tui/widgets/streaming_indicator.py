"""Animated spinner shown above the input bar while streaming."""

from __future__ import annotations

from typing import Any

from rich.spinner import Spinner
from textual.reactive import reactive
from textual.widgets import Static


class StreamingIndicator(Static):
    """Loading indicator above the input bar."""

    # Available styles: "star", "arc", "dots", "line", "pipe", "circle", "flip"
    SPINNER_STYLE = "star"
    SPINNER_SPEED = 0.08  # seconds between frames

    is_streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(content="", **kwargs)
        self.set_class(True, "-hidden")
        self._spinner = Spinner(self.SPINNER_STYLE, text="Thinking...")
        self._tick_task = None

    def on_mount(self) -> None:
        self._tick_task = self.set_interval(self.SPINNER_SPEED, self._tick)

    def on_unmount(self) -> None:
        if self._tick_task:
            self._tick_task.stop()

    def _tick(self) -> None:
        if self.is_streaming:
            self.update(self._spinner)

    def watch_is_streaming(self, is_streaming: bool) -> None:
        """Reactive watcher: show/hide indicator."""
        self.set_class(not is_streaming, "-hidden")
        if is_streaming:
            self.update(self._spinner)
        else:
            self.update("")
