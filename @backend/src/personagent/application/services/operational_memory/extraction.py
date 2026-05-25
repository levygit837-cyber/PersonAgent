"""Extract structured memory items from raw operational memory events."""

from __future__ import annotations

import re

from personagent.domain.memory.models.operational import (
    MemoryChunk,
    MemoryEvent,
    MemoryItemStatus,
    OperationalMemoryEventType,
    StructuredMemoryItem,
    StructuredMemoryType,
)
from personagent.domain.memory.services.operational_memory import stable_hash


class OperationalMemoryExtractor:
    """Derives structured memory items from captured operational events."""

    def structured_items_from_event(
        self,
        event: MemoryEvent,
        chunks: list[MemoryChunk],
    ) -> list[StructuredMemoryItem]:
        """Build structured-memory items from an event and its chunks."""
        items: list[StructuredMemoryItem] = []
        item_type = _structured_type_from_event(event.event_type)
        for chunk in chunks:
            compact = _compact_text(chunk.content)
            if not compact:
                continue
            paths = list(dict.fromkeys([path for path in [chunk.file_path, *event.paths] if path]))
            summary = _structured_summary(
                item_type=item_type,
                event=event,
                path=paths[0] if paths else None,
                text=compact,
            )
            items.append(
                StructuredMemoryItem(
                    type=item_type,
                    summary=summary,
                    evidence=[_compact_text(chunk.content, limit=350)],
                    paths=paths,
                    source_ids=[str(chunk.id)],
                    event_types=[event.event_type.value],
                    status=_structured_status_from_event(event).value,
                    trust_level=_trust_level_from_event(event),
                    importance=_importance_from_event(event),
                    created_at=event.created_at,
                    metadata={
                        "project_slug": event.project_slug,
                        "conversation_id": event.conversation_id,
                        "session_id": event.session_id,
                        "workspace_root": event.workspace_root,
                        "source_type": event.event_type.value,
                        "source_id": str(event.id),
                        "content_hash": stable_hash(
                            "|".join([item_type.value, event.source_hash or "", str(chunk.id)])
                        ),
                        "is_latest": item_type
                        in {
                            StructuredMemoryType.LATEST_STATE,
                            StructuredMemoryType.DECISION,
                            StructuredMemoryType.FILE_STATE,
                        },
                    },
                )
            )
        return items


def _structured_type_from_event(event_type: OperationalMemoryEventType) -> StructuredMemoryType:
    if event_type == OperationalMemoryEventType.OPERATIONAL_SUMMARY:
        return StructuredMemoryType.SESSION_SUMMARY
    if event_type == OperationalMemoryEventType.DECISION:
        return StructuredMemoryType.DECISION
    if event_type == OperationalMemoryEventType.AGENT_STATE:
        return StructuredMemoryType.LATEST_STATE
    if event_type in {
        OperationalMemoryEventType.ERROR_FOUND,
        OperationalMemoryEventType.SOLUTION_ATTEMPTED,
    }:
        return StructuredMemoryType.ERROR_SOLUTION
    if event_type in {
        OperationalMemoryEventType.FILE_CREATED,
        OperationalMemoryEventType.FILE_EDITED,
        OperationalMemoryEventType.FILE_READ,
        OperationalMemoryEventType.DIFF_APPLIED,
    }:
        return StructuredMemoryType.FILE_STATE
    if event_type in {
        OperationalMemoryEventType.COMMAND_EXECUTED,
        OperationalMemoryEventType.DEPENDENCY_INSTALLED,
    }:
        return StructuredMemoryType.COMMAND_RESULT
    if event_type == OperationalMemoryEventType.TEST_RESULT:
        return StructuredMemoryType.TEST_RESULT
    if event_type in {OperationalMemoryEventType.TOOL_CALL, OperationalMemoryEventType.TOOL_RESULT}:
        return StructuredMemoryType.TOOL_TRACE
    return StructuredMemoryType.FACT


def _structured_status_from_event(event: MemoryEvent) -> MemoryItemStatus:
    text = " ".join(
        str(part or "")
        for part in [
            event.status,
            event.error,
            event.resolution,
            event.task,
            event.metadata.get("status") if isinstance(event.metadata, dict) else "",
        ]
    )
    if re.search(r"(?i)\bsuperseded|substitu", text):
        return MemoryItemStatus.SUPERSEDED
    if re.search(r"(?i)\brejected|rejeitad", text):
        return MemoryItemStatus.REJECTED
    if re.search(r"(?i)\bstale|obsoleto|desatualizad", text):
        return MemoryItemStatus.STALE
    return MemoryItemStatus.ACTIVE


def _trust_level_from_event(event: MemoryEvent) -> str:
    if event.event_type in {
        OperationalMemoryEventType.USER_MESSAGE,
        OperationalMemoryEventType.ASSISTANT_MESSAGE,
    }:
        return "low"
    if event.event_type in {
        OperationalMemoryEventType.TOOL_CALL,
        OperationalMemoryEventType.TOOL_RESULT,
        OperationalMemoryEventType.FILE_READ,
        OperationalMemoryEventType.COMMAND_EXECUTED,
    }:
        return "medium"
    return "high"


def _importance_from_event(event: MemoryEvent) -> float:
    if event.event_type in {
        OperationalMemoryEventType.DECISION,
        OperationalMemoryEventType.AGENT_STATE,
        OperationalMemoryEventType.DIFF_APPLIED,
        OperationalMemoryEventType.ERROR_FOUND,
        OperationalMemoryEventType.SOLUTION_ATTEMPTED,
    }:
        return 0.95
    if event.event_type in {
        OperationalMemoryEventType.TEST_RESULT,
        OperationalMemoryEventType.FILE_CREATED,
        OperationalMemoryEventType.FILE_EDITED,
        OperationalMemoryEventType.DEPENDENCY_INSTALLED,
    }:
        return 0.8
    if event.event_type in {
        OperationalMemoryEventType.COMMAND_EXECUTED,
        OperationalMemoryEventType.TOOL_RESULT,
    }:
        return 0.6
    if event.event_type in {
        OperationalMemoryEventType.USER_MESSAGE,
        OperationalMemoryEventType.ASSISTANT_MESSAGE,
    }:
        return 0.2
    return 0.5


def _structured_summary(
    *,
    item_type: StructuredMemoryType,
    event: MemoryEvent,
    path: str | None,
    text: str,
) -> str:
    label = {
        StructuredMemoryType.SESSION_SUMMARY: "Session summary",
        StructuredMemoryType.DECISION: "Decision",
        StructuredMemoryType.LATEST_STATE: "Latest state",
        StructuredMemoryType.ERROR_SOLUTION: "Error or fix",
        StructuredMemoryType.FILE_STATE: "File state",
        StructuredMemoryType.COMMAND_RESULT: "Command result",
        StructuredMemoryType.TEST_RESULT: "Test result",
        StructuredMemoryType.TOOL_TRACE: "Tool trace",
        StructuredMemoryType.FACT: "Operational fact",
    }[item_type]
    source = event.event_type.value.replace("_", " ")
    if event.tool_name:
        source = f"{source} via {event.tool_name}"
    if path:
        source = f"{source} in {path}"
    return f"{label} from {source}: {_compact_text(text, limit=420)}"


def _compact_text(text: str | None, *, limit: int = 420) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    head_size = max(120, limit // 2 - 3)
    tail_size = max(120, limit - head_size - 5)
    return f"{compact[:head_size]} ... {compact[-tail_size:]}"
