"""Browser workspace repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrowserWorkspaceRepository(ABC):
    """Abstract repository for browser workspace persistence.

    Implementations live in the infrastructure layer and encapsulate all
    SQLAlchemy / ORM interactions.
    """

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
    async def update_workspace_state(
        self,
        workspace_id: str,
        state: dict[str, Any],
    ) -> None:
        """Persist workspace.state."""
        ...

    @abstractmethod
    async def set_workspace_fields(
        self,
        workspace_id: str,
        *,
        active_runtime: str | None = None,
        active_tab_id: str | None = None,
        current_url: str | None = None,
        current_title: str | None = None,
    ) -> None:
        """Update scalar fields on the workspace row."""
        ...

    @abstractmethod
    async def upsert_tabs(
        self,
        workspace_id: str,
        tabs: list[dict[str, Any]],
        *,
        active_tab_id: str,
        runtime: str,
    ) -> None:
        """Merge tab list into persisted tabs for the workspace."""
        ...

    @abstractmethod
    async def get_tabs(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return tab dicts ordered by active then updated."""
        ...

    @abstractmethod
    async def get_annotations(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return annotation dicts ordered by created_at asc."""
        ...

    @abstractmethod
    async def get_timeline_events(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return timeline event dicts ordered by sequence asc."""
        ...

    @abstractmethod
    async def append_timeline_event(
        self,
        workspace_id: str,
        browser_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert event and return the persisted dict."""
        ...

    @abstractmethod
    async def create_annotation(
        self,
        workspace_id: str,
        browser_id: str,
        annotation: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert annotation and return the persisted dict."""
        ...

    @abstractmethod
    async def delete_annotation(
        self,
        workspace_id: str,
        annotation_id: str,
    ) -> None:
        """Delete annotation by public annotation_id."""
        ...

    @abstractmethod
    async def clear_timeline(self, workspace_id: str) -> None:
        """Delete all timeline events for the workspace."""
        ...

    @abstractmethod
    async def next_sequence(self, workspace_id: str) -> int:
        """Return max(sequence)+1 for the workspace."""
        ...

    @abstractmethod
    async def trim_timeline(self, workspace_id: str, keep: int = 500) -> None:
        """Delete oldest events beyond *keep* count."""
        ...

    @abstractmethod
    async def migrate_legacy_annotations(
        self,
        workspace_id: str,
        browser_id: str,
        annotations: list[dict[str, Any]],
    ) -> None:
        """Bulk-insert legacy annotations that do not already exist."""
        ...

    @abstractmethod
    async def migrate_legacy_events(
        self,
        workspace_id: str,
        browser_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        """Bulk-insert legacy timeline events that do not already exist."""
        ...

    @abstractmethod
    async def commit(self) -> None:
        """Commit the current transaction."""
        ...
