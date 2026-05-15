# AI-Guide: Build Context Use Case

## Propósito

Orquestra a montagem de contexto completo para uma conversa: workspace, git status, persona.md, regras do projeto, e memória de longo prazo. Atualiza o `StateManager` singleton com os resultados.

---

## Entry Points

### `BuildContextUseCase.execute` @ `application/use_cases/context/build_context.py:60`
```python
async def execute(
    self,
    conversation_id: str,
    use_cache: bool = True,
) -> ContextBuildResult
```
- **Parâmetros**:
  - `conversation_id` — UUID da conversa
  - `use_cache` — se `True`, usa contexto cacheado do `ContextRepository`
- **Retorna**: `ContextBuildResult` com `system_context` e `user_context`
- **Side effects**: Atualiza `StateManager` com conversation_id, workspace_root, system_context, user_context

### `BuildContextUseCase.clear_context` @ `:90`
```python
async def clear_context(self, conversation_id: str) -> None
```
- Limpa cache do `ContextBuilder` e invalida caches do `StateManager`

---

## Construtor

### `BuildContextUseCase.__init__` @ `:26`
```python
def __init__(
    self,
    workspace_root: str | Path,
    context_repository: ContextRepository | None = None,
    enable_persona_md: bool = True,
    additional_directories: list[str | Path] | None = None,
    memory_repository: MemoryRepository | None = None,
) -> None
```
- Inicializa `ContextBuilder` com os mesmos parâmetros
- Obtém `StateManager.get_instance()` (singleton)

---

## Fluxo de `execute`

```
execute(conversation_id, use_cache=True)
├── StateManager.set_conversation_id(conversation_id)
├── StateManager.set_workspace_root(str(workspace_root))
├── ContextBuilder.build_context(conversation_id=..., use_cache=...)
│   ├── Carrega persona.md (se enable_persona_md)
│   ├── Carrega .personagent/rules
│   ├── Carrega git context (branch, dirty, ahead/behind)
│   ├── Carrega context attachments
│   └── Consulta memory_repository (se disponível)
├── ContextBuildResult retornado
├── StateManager.set_system_context(asdict(result.system_context))
└── StateManager.set_user_context(asdict(result.user_context))
```

---

## Dependências Internas

| Componente | Arquivo | Função |
|------------|---------|--------|
| `ContextBuilder` | `domain/context/services/context_builder.py` | Lógica real de montagem de contexto |
| `ContextBuildResult` | `domain/context/models.py` | Dataclass de resultado |
| `ContextRepository` | `domain/context/repositories.py` | Port para cache de contexto |
| `MemoryRepository` | `domain/memory/repositories/memory_repository.py` | Port para memória de longo prazo |
| `StateManager` | `application/state/services/state_manager.py` | Estado global singleton |

---

## Quando Modificar

### Adicionar nova fonte de contexto
1. Modificar `ContextBuilder.build_context()` em `domain/context/services/context_builder.py`
2. Adicionar campo ao `ContextBuildResult` em `domain/context/models.py`
3. Atualizar este AI-Guide

### Mudar prioridade de persona.md
- Parâmetro `enable_persona_md` no construtor @ `:30`
- Ou modificar `ContextBuilder` para suportar múltiplos arquivos de persona

### Adicionar cache de contexto
- Implementar `ContextRepository` (porta abstrata)
- Injetar no construtor via `context_repository`

---

## Anti-patterns

- **Nunca** ler arquivos do filesystem diretamente neste use case — delegar ao `ContextBuilder`
- **Nunca** modificar `StateManager` fora dos métodos `execute`/`clear_context`
- **Nunca** passar `use_cache=False` em hot path sem razão — gera I/O repetido

---

## Dependências

- `domain.context.models` — `ContextBuildResult`
- `domain.context.repositories` — `ContextRepository`
- `domain.context.services.context_builder` — `ContextBuilder`
- `domain.memory.repositories.memory_repository` — `MemoryRepository`
- `application.state.services.state_manager` — `StateManager`
- Consumido por: `ChatCompletionUseCase` (via DIContainer)
