"""Application services for prompt-adjacent chat behavior."""

from personagent.application.services.browser_cooperation import BrowserCooperationService
from personagent.application.services.browser_workspace import BrowserWorkspaceService
from personagent.application.services.next_step import NextStepSuggestionService
from personagent.application.services.operational_memory import OperationalMemoryService
from personagent.application.services.session_memory import SessionMemoryService
from personagent.application.services.session_titles import SessionTitleService

__all__ = [
    "NextStepSuggestionService",
    "BrowserCooperationService",
    "BrowserWorkspaceService",
    "OperationalMemoryService",
    "SessionMemoryService",
    "SessionTitleService",
]
