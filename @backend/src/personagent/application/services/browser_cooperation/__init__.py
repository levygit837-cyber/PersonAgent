"""Browser cooperation service package.

Re-exports every public symbol that external consumers previously
imported from ``personagent.application.services.browser_cooperation``.
"""

from personagent.application.services.browser_cooperation.event_processing import (
    _normalize_event,
)
from personagent.application.services.browser_cooperation.helpers import (
    BROWSER_COOPERATION_DEFAULT_MODE,
    BROWSER_COOPERATION_METADATA_KEY,
    BROWSER_COOPERATION_MODES,
    BrowserEventEnvelope,
    attach_browser_action_proposal,
    browser_agent_context_reminder,
    build_browser_agent_context,
    shared_browser_workspace_reminder,
)
from personagent.application.services.browser_cooperation.service import (
    BrowserCooperationService,
)

__all__ = [
    "BROWSER_COOPERATION_DEFAULT_MODE",
    "BROWSER_COOPERATION_METADATA_KEY",
    "BROWSER_COOPERATION_MODES",
    "BrowserCooperationService",
    "BrowserEventEnvelope",
    "_normalize_event",
    "attach_browser_action_proposal",
    "browser_agent_context_reminder",
    "build_browser_agent_context",
    "shared_browser_workspace_reminder",
]
