"""Portas e stores para registros de tarefas usados pelas tools Task*."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Registro persistente de tarefa."""

    id: str
    title: str
    description: str = ""
    status: str = "open"
    priority: str = "normal"
    conversation_id: str | None = None
    workspace_root: str | None = None
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "conversation_id": self.conversation_id,
            "workspace_root": self.workspace_root,
            "output": self.output,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TaskStore(Protocol):
    """Porta de persistência para Task tools."""

    async def create(self, record: TaskRecord) -> TaskRecord: ...

    async def get(self, task_id: str) -> TaskRecord | None: ...

    async def update(self, task_id: str, values: dict[str, Any]) -> TaskRecord | None: ...

    async def list(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]: ...


class InMemoryTaskStore:
    """Store leve para testes e ambientes sem banco."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    async def create(self, record: TaskRecord) -> TaskRecord:
        self._records[record.id] = record
        return record

    async def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)

    async def update(self, task_id: str, values: dict[str, Any]) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        allowed = {
            key: value
            for key, value in values.items()
            if key in {"title", "description", "status", "priority", "output", "metadata"}
            and value is not None
        }
        updated = replace(record, **allowed, updated_at=datetime.now(UTC))
        self._records[task_id] = updated
        return updated

    async def list(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        records = list(self._records.values())
        if conversation_id is not None:
            records = [record for record in records if record.conversation_id == conversation_id]
        if status is not None:
            records = [record for record in records if record.status == status]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records[: max(1, limit)]


def new_task_record(
    *,
    title: str,
    description: str = "",
    status: str = "open",
    priority: str = "normal",
    conversation_id: str | None = None,
    workspace_root: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskRecord:
    """Cria um TaskRecord com id novo."""
    return TaskRecord(
        id=str(uuid4()),
        title=title,
        description=description,
        status=status,
        priority=priority,
        conversation_id=conversation_id,
        workspace_root=workspace_root,
        metadata=metadata or {},
    )


__all__ = ["InMemoryTaskStore", "TaskRecord", "TaskStore", "new_task_record"]
