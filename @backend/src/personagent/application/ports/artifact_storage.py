"""Application port for artifact persistence.

The application layer uses this protocol to store large tool results and
generated images without depending on the infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredArtifactRef:
    artifact_id: str
    url: str
    size_bytes: int
    sha256: str


class ArtifactStoragePort(Protocol):
    """Store runtime artifacts (tool results, generated images, etc.)."""

    def persist_tool_result(
        self,
        content: str,
        conversation_id: str,
        tool_call_id: str,
        root: Path | None,
    ) -> str | None:
        """Store oversized tool result; return a storage ref or None on failure."""
        ...

    def store_bytes(
        self,
        *,
        category: str,
        conversation_id: str,
        content: bytes,
        suffix: str,
        mime_type: str,
        root: Path | None,
        ttl_seconds: int | None,
    ) -> StoredArtifactRef:
        """Store binary payload and return reference."""
        ...
