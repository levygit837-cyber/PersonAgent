# Error Handling no PersonAgent

## Visão geral

Todas as exceções do backend herdam de `PersonAgentError`, garantindo estrutura consistente de código, mensagem, metadados e flag de retry.

## Hierarquia

```
PersonAgentError
├── LLMBackendError
│   ├── LLMBackendConnectionError
│   ├── LLMBackendTimeoutError
│   ├── ProviderOverloadedError
│   └── ProviderRateLimitError
├── ToolError
│   ├── ToolNotFoundError
│   ├── ToolInputValidationError
│   ├── ToolPermissionDeniedError
│   ├── ToolPermissionRequiredError
│   └── ToolTimeoutError
├── ShellCommandDeniedError
├── BrowserError
├── InvalidRequestError
└── (outros)
```

## Campos obrigatórios

```python
@dataclass(slots=True)
class PersonAgentError(Exception):
    message: str
    code: str
    metadata: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    http_status: int = 500
```

## Streaming de erros

Erros durante chat são emitidos como eventos SSE:

```json
{
  "event": "error",
  "error": {
    "code": "tool_permission_denied",
    "message": "Shell command requires approval.",
    "retryable": false
  }
}
```

## Retry

- Erros `retryable=True` são submetidos ao `RetryPolicy` (ADR 0016).
- Erros `retryable=False` (permission denied, validation) param imediatamente.

## Logs

- `structlog` gera JSON logs com contexto de trace.
- Erros incluem `conversation_id`, `tool_name`, `provider`, `model` nos metadados.

## Referências

- ADR 0016: Retry Bounded Budget
