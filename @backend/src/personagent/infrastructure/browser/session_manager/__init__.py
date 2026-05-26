"""Browser session lifecycle — create, reuse, resolve, cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from personagent.infrastructure.browser.session_manager._acquisition import _SessionAcquisitionMixin
from personagent.infrastructure.browser.session_manager._cleanup import _SessionCleanupMixin
from personagent.infrastructure.browser.session_manager._pages import _SessionPagesMixin
from personagent.infrastructure.browser.session_manager._resolution import _PageResolutionMixin

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

__all__ = ["BrowserSessionManager"]


class BrowserSessionManager(
    _SessionAcquisitionMixin,
    _SessionPagesMixin,
    _PageResolutionMixin,
    _SessionCleanupMixin,
):
    """Owns per-conversation browser sessions and page resolution."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker
