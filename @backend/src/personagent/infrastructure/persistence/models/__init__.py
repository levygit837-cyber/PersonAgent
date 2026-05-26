"""ORM models package — re-exports all model classes."""

import importlib.util
import sys
from pathlib import Path

from personagent.infrastructure.persistence.models.core import (
    ConversationORM,
    MessageORM,
    TenantORM,
)

# The legacy models.py module is shadowed by this package during normal
# imports.  Load it explicitly so we can re-export classes that have not
# yet been extracted into submodules.
_legacy_spec = importlib.util.spec_from_file_location(
    "_models_legacy",
    Path(__file__).parent.parent / "models.py",
)
_legacy = importlib.util.module_from_spec(_legacy_spec)
sys.modules[_legacy_spec.name] = _legacy
_legacy_spec.loader.exec_module(_legacy)

# Re-export remaining ORM classes from the legacy module.
# These will be moved into dedicated submodules in follow-up slices.
BrowserAnnotationORM = _legacy.BrowserAnnotationORM
BrowserAutomationRunORM = _legacy.BrowserAutomationRunORM
BrowserAutomationStepORM = _legacy.BrowserAutomationStepORM
BrowserCooperationEventORM = _legacy.BrowserCooperationEventORM
BrowserTabORM = _legacy.BrowserTabORM
BrowserTimelineEventORM = _legacy.BrowserTimelineEventORM
BrowserWorkspaceORM = _legacy.BrowserWorkspaceORM
MemoryConsolidationLockORM = _legacy.MemoryConsolidationLockORM
MemoryDecisionORM = _legacy.MemoryDecisionORM
MemoryEmbeddingORM = _legacy.MemoryEmbeddingORM
MemoryFileORM = _legacy.MemoryFileORM
MemoryJobORM = _legacy.MemoryJobORM
MemoryOutboxORM = _legacy.MemoryOutboxORM
MemoryRecallLogORM = _legacy.MemoryRecallLogORM
MemorySessionORM = _legacy.MemorySessionORM
OperationalMemoryChunkORM = _legacy.OperationalMemoryChunkORM
OperationalMemoryEventORM = _legacy.OperationalMemoryEventORM
QAArtifactORM = _legacy.QAArtifactORM
QACodeEdgeORM = _legacy.QACodeEdgeORM
QACodeNodeORM = _legacy.QACodeNodeORM
QARequestRunORM = _legacy.QARequestRunORM
QARuntimeEventORM = _legacy.QARuntimeEventORM
QASessionORM = _legacy.QASessionORM
StructuredMemoryItemORM = _legacy.StructuredMemoryItemORM
TaskRecordORM = _legacy.TaskRecordORM
TeamBlackboardEventORM = _legacy.TeamBlackboardEventORM
TeamMemorySnapshotORM = _legacy.TeamMemorySnapshotORM
TeamRunORM = _legacy.TeamRunORM

__all__ = [
    "BrowserAnnotationORM",
    "BrowserAutomationRunORM",
    "BrowserAutomationStepORM",
    "BrowserCooperationEventORM",
    "BrowserTabORM",
    "BrowserTimelineEventORM",
    "BrowserWorkspaceORM",
    "ConversationORM",
    "MemoryConsolidationLockORM",
    "MemoryDecisionORM",
    "MemoryEmbeddingORM",
    "MemoryFileORM",
    "MemoryJobORM",
    "MemoryOutboxORM",
    "MemoryRecallLogORM",
    "MemorySessionORM",
    "MessageORM",
    "OperationalMemoryChunkORM",
    "OperationalMemoryEventORM",
    "QAArtifactORM",
    "QACodeEdgeORM",
    "QACodeNodeORM",
    "QARequestRunORM",
    "QARuntimeEventORM",
    "QASessionORM",
    "StructuredMemoryItemORM",
    "TaskRecordORM",
    "TeamBlackboardEventORM",
    "TeamMemorySnapshotORM",
    "TeamRunORM",
    "TenantORM",
]
