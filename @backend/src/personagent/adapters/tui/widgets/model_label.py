"""Model name label displayed below the input bar."""

from __future__ import annotations

from typing import Any

from textual.reactive import reactive
from textual.widgets import Static


class ModelLabel(Static):
    """Displays the active model name in muted text."""

    model_name: reactive[str] = reactive("deepseek-v4-flash")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(content="", **kwargs)
        self.update(self._text())

    def _text(self) -> str:
        return f"◈ {self.model_name}"

    def watch_model_name(self, model_name: str) -> None:
        """Reactive watcher: update text when model changes."""
        self.update(self._text())
    