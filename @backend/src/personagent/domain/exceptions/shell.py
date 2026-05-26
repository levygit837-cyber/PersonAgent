from personagent.domain.exceptions.base import ErrorCategory
from personagent.domain.exceptions.tool import (
    ToolError,
    ToolPermissionDeniedError,
    ToolTimeoutError,
)


class ShellCommandDeniedError(ToolPermissionDeniedError):
    """Shell command was denied by policy."""

    code = "shell.command_denied"
    category = ErrorCategory.SHELL


class ShellTimeoutError(ToolTimeoutError):
    """Shell command timed out."""

    code = "shell.timeout"
    category = ErrorCategory.SHELL


class ShellCommandFailedError(ToolError):
    """Shell command exited with a non-zero code."""

    code = "shell.non_zero_exit"
    category = ErrorCategory.SHELL


