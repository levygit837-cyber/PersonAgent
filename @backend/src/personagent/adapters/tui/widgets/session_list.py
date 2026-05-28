"""Session list overlay widget for selecting a conversation."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static


class SessionList(Static, can_focus=True):
    """Overlay card showing a list of conversations."""

    sessions: reactive[list[dict[str, Any]]] = reactive(list)
    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_rows: list[Static] = []

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
        """Select the current session and notify the app."""
        session_id = self.get_selected_id()
        if session_id:
            self.post_message(self.SessionSelected(session_id))
        self.remove()

    class SessionSelected(Message):
        """Message emitted when a session is selected."""

        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def watch_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Rebuild the list when sessions change."""
        self._rebuild()

    def watch_selected_index(self, index: int) -> None:
        """Highlight the selected row."""
        for i, row in enumerate(self._session_rows):
            row.set_class(i == index, "-selected")

    def _rebuild(self) -> None:
        """Clear and rebuild the session rows."""
        for child in list(self.children):
            child.remove()
        self._session_rows = []

        if not self.sessions:
            empty = Static("No sessions found.")
            empty.add_class("session-empty")
            self.mount(empty)
            return

        for i, session in enumerate(self.sessions):
            title = session.get("title") or "Untitled"
            msg_count = session.get("message_count", 0)
            updated = session.get("updated_at", "")[:10]
            row = Static(f"{title}  ({msg_count} msgs, {updated})")
            row.add_class("session-row")
            if i == self.selected_index:
                row.add_class("-selected")
            self.mount(row)
            self._session_rows.append(row)

        # Add close button at the bottom
        close_btn = Button("Close", variant="primary", id="close-sessions")
        close_btn.add_class("session-close")
        self.mount(close_btn)

    def move_selection(self, delta: int) -> None:
        """Move the selection by delta rows."""
        if not self.sessions:
            return
        new_index = self.selected_index + delta
        new_index = max(0, min(new_index, len(self.sessions) - 1))
        self.selected_index = new_index

    def get_selected_id(self) -> str | None:
        """Return the ID of the currently selected session."""
        if not self.sessions or self.selected_index >= len(self.sessions):
            return None
        return self.sessions[self.selected_index].get("id")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle close button."""
        if event.button.id == "close-sessions":
            self.app.action_palette_close()
