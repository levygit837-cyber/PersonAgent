from personagent.domain.exceptions.base import ErrorCategory
from personagent.domain.exceptions.tool import ToolError


class WebError(ToolError):
    """Web tool failed."""

    code = "web.error"
    category = ErrorCategory.WEB


class WebURLInvalidError(WebError):
    """URL is invalid for web access."""

    code = "web.url_invalid"
    http_status = 400


class WebDomainBlockedError(WebError):
    """URL host is blocked by policy."""

    code = "web.domain_blocked"
    http_status = 403


class WebFetchTimeoutError(WebError):
    """Web fetch timed out."""

    code = "web.fetch_timeout"
    http_status = 504
    retryable = True


