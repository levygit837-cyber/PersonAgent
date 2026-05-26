from personagent.domain.exceptions.base import ErrorCategory
from personagent.domain.exceptions.tool import ToolError


class BrowserError(ToolError):
    """Browser tool failed."""

    code = "browser.error"
    category = ErrorCategory.BROWSER


class BrowserUnavailableError(BrowserError):
    """Browser backend is unavailable."""

    code = "browser.unavailable"
    http_status = 503
    retryable = True


class BrowserNavigationTimeoutError(BrowserError):
    """Browser navigation timed out."""

    code = "browser.navigation_timeout"
    http_status = 504
    retryable = True


