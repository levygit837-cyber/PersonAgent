from personagent.domain.exceptions.base import ErrorCategory, PersonAgentError


class MemoryError(PersonAgentError):
    """Memory subsystem failed."""

    code = "memory.error"
    category = ErrorCategory.MEMORY
    http_status = 500


class TeamError(PersonAgentError):
    """Team mode failed."""

    code = "team.error"
    category = ErrorCategory.TEAM
    http_status = 500


class TeamValidationSystemError(TeamError):
    """Team mode validation failed."""

    code = "team.validation"
    http_status = 400


class BackgroundJobError(PersonAgentError):
    """Background job failed."""

    code = "background.job_failed"
    category = ErrorCategory.BACKGROUND
    http_status = 500


class DatabaseError(PersonAgentError):
    """Database operation failed."""

    code = "database.error"
    category = ErrorCategory.DATABASE
    http_status = 500
    retryable = True


class InternalSystemError(PersonAgentError):
    """Unexpected internal system error."""

    code = "system.internal_error"
    category = ErrorCategory.SYSTEM
    http_status = 500
    safe_for_model = False


