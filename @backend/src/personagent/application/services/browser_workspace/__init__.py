"""Browser workspace service package.

Re-exports every public symbol that external consumers previously
imported from ``personagent.application.services.browser_workspace``.
"""

from personagent.application.services.browser_workspace.service import (
    BrowserWorkspaceService,
)

__all__ = [
    "BrowserWorkspaceService",
]
