"""Exceções de domínio do PersonAgent."""


class PersonAgentError(Exception):
    """Exceção base do sistema."""

    pass


class ConversationNotFoundError(PersonAgentError):
    """Conversa não encontrada no repositório."""

    pass


class LLMBackendError(PersonAgentError):
    """Erro de comunicação com o backend LLM."""

    pass


class LLMBackendConnectionError(LLMBackendError):
    """Não foi possível conectar ao llama-server."""

    pass


class LLMBackendTimeoutError(LLMBackendError):
    """Timeout na requisição ao llama-server."""

    pass


class InvalidMessageError(PersonAgentError):
    """Mensagem inválida fornecida."""

    pass


class ConfigurationError(PersonAgentError):
    """Erro na configuração do sistema."""

    pass
