"""Application services for prompt-adjacent chat behavior."""

from personagent.application.services.browser_cooperation import BrowserCooperationService
from personagent.application.services.browser_workspace import BrowserWorkspaceService
from personagent.application.services.insights.next_step import NextStepSuggestionService
from personagent.application.services.operational_memory import OperationalMemoryService
from personagent.application.services.session.operational_memory_queue import OperationalMemoryQueue
from personagent.application.services.session.session_memory import SessionMemoryService
from personagent.application.services.session_titles import SessionTitleService

__all__ = [
    "NextStepSuggestionService",
    "BrowserCooperationService",
    "BrowserWorkspaceService",
    "OperationalMemoryService",
    "OperationalMemoryQueue",
    "SessionMemoryService",
    "SessionTitleService",
]
