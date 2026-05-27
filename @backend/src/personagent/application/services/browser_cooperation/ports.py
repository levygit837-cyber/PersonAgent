"""Browser cooperation repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrowserCooperationRepository(ABC):
    """Abstract repository for browser cooperation persistence."""

    @abstractmethod
    async def get_or_create_workspace(
        self,
        conversation_id: str,
        browser_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Return workspace dict; create if absent."""
        ...

    @abstractmethod
    async def update_workspace_state(self, workspace_id: str, state: dict[str, Any]) -> None:
        """Persist workspace.state."""
        ...

    @abstractmethod
    async def next_sequence(self, workspace_id: str) -> int:
        """Return max(sequence)+1 for cooperation events in the workspace."""
        ...

    @abstractmethod
    async def existing_event_ids(self, workspace_id: str, event_ids: list[str]) -> set[str]:
        """Return the subset of *event_ids* that already exist."""
        ...

    @abstractmethod
    async def persist_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        """Bulk-insert cooperation events."""
        ...

    @abstractmethod
    async def latest_raw_events(self, workspace_id: str, limit: int) -> list[dict[str, Any]]:
        """Return recent raw cooperation events ordered by sequence asc."""
        ...

    @abstractmethod
    async def enforce_retention(self, workspace_id: str, limit: int) -> None:
        """Delete oldest events beyond *limit* count."""
        ...

    @abstractmethod
    async def commit(self) -> None:
        """Commit the current transaction."""
        ...
