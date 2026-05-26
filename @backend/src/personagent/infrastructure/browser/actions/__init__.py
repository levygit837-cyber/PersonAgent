"""Visible-page browser actions extracted from the LightPanda god file."""

from __future__ import annotations

from typing import TYPE_CHECKING

from personagent.infrastructure.browser.actions._capture import _CaptureMixin
from personagent.infrastructure.browser.actions._console import _ConsoleMixin
from personagent.infrastructure.browser.actions._constants import (
    _BROWSER_SCRIPT_CDP_ALLOWLIST,
    _MAX_BROWSER_SCRIPT_CHARS,
    _MAX_BROWSER_SCRIPT_RESULT_CHARS,
    _MAX_CONSOLE_ENTRIES_PER_PAGE,
)
from personagent.infrastructure.browser.actions._interaction import _InteractionMixin
from personagent.infrastructure.browser.actions._script import _ScriptMixin
from personagent.infrastructure.browser.actions._state import _StateMixin

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

__all__ = [
    "BrowserActions",
    "_BROWSER_SCRIPT_CDP_ALLOWLIST",
    "_MAX_BROWSER_SCRIPT_CHARS",
    "_MAX_BROWSER_SCRIPT_RESULT_CHARS",
    "_MAX_CONSOLE_ENTRIES_PER_PAGE",
]


class BrowserActions(_InteractionMixin, _CaptureMixin, _ConsoleMixin, _ScriptMixin, _StateMixin):
    """Visible-page actions: click, type, screenshot, scroll, console, script, wait."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker
