"""Slash command autocomplete palette widget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.reactive import reactive
from textual.widgets import Static


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """A slash command entry for the palette."""

    name: str
    description: str
    argument_hint: str = ""

    @property
    def display_text(self) -> str:
        hint = f" {self.argument_hint}" if self.argument_hint else ""
        return f"/{self.name}{hint}"


BUILTIN_COMMANDS: list[SlashCommand] = [
    SlashCommand("sessions", "Show all chat sessions.", ""),
    SlashCommand("clear", "Start a clean chat session.", ""),
    SlashCommand("help", "Show supported slash commands.", ""),
    SlashCommand("plan", "Enter planning flow before making changes.", ""),
    SlashCommand("memory", "Inspect or work with memory.", "[search terms]"),
    SlashCommand("mcp", "Inspect MCP servers and resources.", "[server]"),
    SlashCommand("skills", "List or inspect enabled skills.", "[skill name]"),
    SlashCommand("permissions", "Inspect tool permission policy.", "[tool name]"),
    SlashCommand("model", "Inspect or change the selected model.", "[provider/model]"),
    SlashCommand("effort", "Change reasoning effort.", "[low|medium|high|max]"),
    SlashCommand("context", "Inspect model-visible context.", ""),
    SlashCommand("compact", "Request context compaction.", ""),
    SlashCommand("diff", "Inspect current workspace changes.", ""),
    SlashCommand("files", "Inspect files in the workspace.", "[path]"),
    SlashCommand("branch", "Inspect git branch state.", ""),
    SlashCommand("usage", "Inspect token and tool usage.", ""),
    SlashCommand("status", "Summarize workspace and session state.", ""),
    SlashCommand("doctor", "Run a local health check.", ""),
]


class CommandPalette(Static):
    """A small overlay showing matching slash commands."""

    query: reactive[str] = reactive("")
    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rows: list[Static] = []

    def watch_query(self, query: str) -> None:
        """Rebuild the list when the query changes."""
        self.selected_index = 0
        self._rebuild()

    def watch_selected_index(self, index: int) -> None:
        """Highlight the selected row and scroll it into view."""
        for i, row in enumerate(self._rows):
            row.set_class(i == index, "-selected")
        if 0 <= index < len(self._rows):
            self.scroll_to_widget(self._rows[index])

    def _matching_commands(self) -> list[SlashCommand]:
        """Return commands matching the current query (without leading '/')."""
        q = self.query.lstrip("/").lower()
        if not q:
            return BUILTIN_COMMANDS
        return [
            cmd
            for cmd in BUILTIN_COMMANDS
            if q in cmd.name.lower() or q in cmd.description.lower()
        ]

    def _rebuild(self) -> None:
        """Clear and rebuild command rows."""
        for child in list(self.children):
            child.remove()
        self._rows = []

        matches = self._matching_commands()
        if not matches:
            empty = Static("No matching commands")
            empty.add_class("palette-empty")
            self.mount(empty)
            return

        for i, cmd in enumerate(matches):
            row = Static(f"{cmd.display_text}\n  {cmd.description}")
            row.add_class("palette-row")
            if i == self.selected_index:
                row.add_class("-selected")
            self.mount(row)
            self._rows.append(row)

    def move_selection(self, delta: int) -> None:
        """Move the selection by delta rows."""
        count = len(self._matching_commands())
        if count == 0:
            return
        new_index = self.selected_index + delta
        new_index = max(0, min(new_index, count - 1))
        self.selected_index = new_index

    def get_selected_command(self) -> SlashCommand | None:
        """Return the currently selected command."""
        matches = self._matching_commands()
        if not matches or self.selected_index >= len(matches):
            return None
        return matches[self.selected_index]
