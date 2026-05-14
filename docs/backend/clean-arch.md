# Clean Architecture no PersonAgent

## Visão geral

O backend segue **Clean Architecture** com quatro camadas bem definidas, garantindo que regras de negócio (domain) nunca dependam de frameworks ou bibliotecas externas.

## Camadas

| Camada | Responsabilidade | Exemplos |
|--------|-----------------|----------|
| **Domain** | Entidades, regras de negócio, contratos abstratos | `Conversation`, `Message`, `ToolDefinition`, `LLMBackendRepository` (interface) |
| **Application** | Casos de uso, orquestração, serviços de aplicação | `ChatCompletionUseCase`, `ToolOrchestrator`, `BuildContextUseCase` |
| **Infrastructure** | Adaptadores concretos para bancos, LLMs, processos | `SQLAlchemyConversationRepository`, `LlamaBackendAdapter`, `LlamaServerProcessManager` |
| **Interfaces** | Web framework, DI container, rotas API | `FastAPI routes`, `DIContainer`, `lifespan` |

## Regra de dependência

- Domain **não conhece** nenhuma outra camada.
- Application conhece apenas Domain.
- Infrastructure conhece Domain + Application.
- Interfaces conhece todas as camadas (wiring).

## Exemplo prático

```python
# Domain: contrato puro
class ConversationRepository(Protocol):
    async def get_by_id(self, id: UUID) -> Conversation | None: ...

# Infrastructure: implementação concreta
class SQLAlchemyConversationRepository:
    async def get_by_id(self, id: UUID) -> Conversation | None:
        ...

# Application: caso de uso
class ChatCompletionUseCase:
    def __init__(self, conversation_repo: ConversationRepository) -> None:
        self._conversation_repo = conversation_repo
```

## Anti-padrões a evitar

- Importar `sqlalchemy` em arquivos de `domain/`.
- Chamar `requests.get()` diretamente de um caso de uso (use a interface `LLMBackendRepository`).
- Lógica de negócio em rotas FastAPI.

## Testes

- Testes de domínio: zero mocks, apenas objetos puros.
- Testes de aplicação: mockar apenas interfaces do domínio.
- Testes de infraestrutura: usam containers reais (Postgres, llama-server).

## Referências

- ADR 0001: Clean Architecture
