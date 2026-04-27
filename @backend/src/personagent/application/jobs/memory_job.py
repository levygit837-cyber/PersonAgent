"""Models para jobs de memória em background.

Define os tipos de job, status e a entidade MemoryJob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobType(StrEnum):
    """Tipos de job de memória."""

    EXTRACT_MEMORIES = "extract_memories"
    AUTO_DREAM = "auto_dream"
    TEAM_SYNC = "team_sync"


class JobStatus(StrEnum):
    """Status de execução de um job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MemoryJob:
    """Job de memória em background."""

    id: str
    type: JobType
    conversation_id: str | None
    project_slug: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None

    def mark_running(self) -> None:
        """Marca o job como em execução."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def mark_completed(self, result: dict[str, Any] | None = None) -> None:
        """Marca o job como concluído."""
        self.status = JobStatus.COMPLETED
        self.finished_at = datetime.now(UTC)
        self.result = result

    def mark_failed(self, error_message: str) -> None:
        """Marca o job como falho."""
        self.status = JobStatus.FAILED
        self.finished_at = datetime.now(UTC)
        self.error_message = error_message
