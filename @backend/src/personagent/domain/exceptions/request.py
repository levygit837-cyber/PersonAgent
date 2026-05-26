from personagent.domain.exceptions.base import ErrorCategory, PersonAgentError


class InvalidRequestError(PersonAgentError):
    """The request is invalid."""

    code = "request.invalid"
    category = ErrorCategory.REQUEST
    http_status = 400


class InvalidMessageError(InvalidRequestError):
    """Invalid message supplied."""

    code = "request.invalid_message"


class ConflictStateError(PersonAgentError):
    """The requested operation conflicts with current state."""

    code = "request.conflict_state"
    category = ErrorCategory.REQUEST
    http_status = 409


class ConversationNotFoundError(PersonAgentError):
    """Conversation not found."""

    code = "conversation.not_found"
    category = ErrorCategory.CONVERSATION
    http_status = 404


class ConfigurationError(PersonAgentError):
    """System configuration is invalid."""

    code = "config.invalid"
    category = ErrorCategory.CONFIG
    http_status = 500


class WorkspaceScopeError(PersonAgentError):
    """Path is outside the configured workspace scope."""

    code = "workspace.scope_denied"
    category = ErrorCategory.WORKSPACE
    http_status = 403


class FileSystemError(PersonAgentError):
    """Filesystem operation failed."""

    code = "filesystem.error"
    category = ErrorCategory.FILESYSTEM
    http_status = 500
