"""Model list overlay widget for selecting a model."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class ModelList(Static, can_focus=True):
    """Overlay card showing a list of available models."""

    models: reactive[list[dict[str, Any]]] = reactive(list)
    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._model_rows: list[Static] = []

    def on_key(self, event) -> None:
        """Handle keyboard navigation."""
        if event.key == "up":
            self.move_selection(-1)
            event.stop()
        elif event.key == "down":
            self.move_selection(1)
            event.stop()
        elif event.key == "enter":
            self._select_current()
            event.stop()
        elif event.key == "escape":
            self.app.action_palette_close()
            event.stop()

    def _select_current(self) -> None:
        """Select the current model and notify the app."""
        model_name = self.get_selected_name()
        if model_name:
            self.post_message(self.ModelSelected(model_name))
        self.remove()

    class ModelSelected(Message):
        """Message emitted when a model is selected."""

        def __init__(self, model_name: str) -> None:
            self.model_name = model_name
            super().__init__()

    def watch_models(self, models: list[dict[str, Any]]) -> None:
        """Rebuild the list when models change."""
        self._rebuild()

    def watch_selected_index(self, index: int) -> None:
        """Highlight the selected row."""
        for i, row in enumerate(self._model_rows):
            row.set_class(i == index, "-selected")

    def _rebuild(self) -> None:
        """Clear and rebuild the model rows."""
        for child in list(self.children):
            child.remove()
        self._model_rows = []

        if not self.models:
            empty = Static("No models found.")
            empty.add_class("model-empty")
            self.mount(empty)
            return

        for i, model in enumerate(self.models):
            name = model.get("id") or model.get("name") or str(model)
            row = Static(f"{name}")
            row.add_class("model-row")
            if i == self.selected_index:
                row.add_class("-selected")
            self.mount(row)
            self._model_rows.append(row)

    def move_selection(self, delta: int) -> None:
        """Move the selection by delta rows."""
        if not self.models:
            return
        new_index = self.selected_index + delta
        new_index = max(0, min(new_index, len(self.models) - 1))
        self.selected_index = new_index

    def get_selected_name(self) -> str | None:
        """Return the name of the currently selected model."""
        if not self.models or self.selected_index >= len(self.models):
            return None
        return self.models[self.selected_index].get("id") or self.models[self.selected_index].get("name")

