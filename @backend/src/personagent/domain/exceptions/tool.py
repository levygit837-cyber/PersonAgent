from personagent.domain.exceptions.base import ErrorCategory, PersonAgentError


class ToolError(PersonAgentError):
    """Tool execution failed."""

    code = "tool.error"
    category = ErrorCategory.TOOL
    http_status = 500


class ToolNotFoundError(ToolError):
    """Requested tool is not registered."""

    code = "tool.not_found"
    http_status = 404


class ToolInputValidationError(ToolError):
    """Tool input validation failed."""

    code = "tool.input_invalid"
    http_status = 400


class ToolPermissionRequiredError(ToolError):
    """Tool call requires user permission."""

    code = "tool.permission_required"
    http_status = 409


class ToolPermissionDeniedError(ToolError):
    """Tool call was denied."""

    code = "tool.permission_denied"
    http_status = 403


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""

    code = "tool.timeout"
    http_status = 504
    retryable = True


class ToolInterruptedError(ToolError):
    """Tool execution was interrupted."""

    code = "tool.interrupted"
    http_status = 499


class ToolResultTooLargeError(ToolError):
    """Tool result exceeded configured limits."""

    code = "tool.result_too_large"
    http_status = 413


class ToolLoopLimitExceededError(ToolError):
    """Maximum tool iteration count was reached."""

    code = "tool.loop_limit_exceeded"
    http_status = 409


