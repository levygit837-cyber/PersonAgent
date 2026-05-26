"""Browser view-mode action wrappers.

Extracted from ``lightpanda.py`` as part of the god-file decomposition
(Slice 7).  Each ``view_*`` method wraps a low-level browser primitive
(navigate, click, key, scroll, etc.) with view-mode semantics: it
performs the action, then returns a fresh ``browser_view_snapshot``
so the caller always gets the resulting DOM state.

``BrowserViewActions`` receives a back-reference to the worker
(``self._w``) and delegates infrastructure calls through it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from personagent.infrastructure.browser.view_actions._act import _ActMixin
from personagent.infrastructure.browser.view_actions._navigation import _NavigationMixin
from personagent.infrastructure.browser.view_actions._pointer import _PointerMixin
from personagent.infrastructure.browser.view_actions._script import _BROWSER_ACT_SCRIPT

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

__all__ = [
    "BrowserViewActions",
    "_BROWSER_ACT_SCRIPT",
]


class BrowserViewActions(_NavigationMixin, _PointerMixin, _ActMixin):
    """View-mode action wrappers extracted from ``LightPandaBrowserWorker``."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker
