# AI-Guide: Build Context Use Case


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Orquestra a montagem de contexto completo para uma conversa: workspace, git status, persona.md, regras do projeto, e memória de longo prazo. Retorna o `ContextBuildResult` puro ou, via `build_request_context`, um snapshot imutável `RequestContext` pronto para ser propagado pela cadeia de chamadas.

> **Histórico**: até a Fase 0.3 deste roadmap o use case mutava um `StateManager` singleton com os resultados. Esse padrão foi removido — todo o estado por requisição agora vive em `RequestContext`.

---

## Entry Points

### `BuildContextUseCase.execute` @ `application/use_cases/context/build_context.py:59`
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
- **Side effects**: Nenhum estado global. Toca apenas o `ContextRepository` injetado.

### `BuildContextUseCase.build_request_context` @ `:78`
```python
async def build_request_context(
    self,
    conversation_id: str,
    *,
    use_cache: bool = True,
    permission_mode: PermissionMode = "manual",
    tenant_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
) -> RequestContext
```
- Combina `execute()` com `RequestContext.from_build_result`
- Use sempre que o consumidor precisar passar o contexto adiante na call chain

### `BuildContextUseCase.clear_context` @ `:106`
```python
async def clear_context(self, conversation_id: str) -> None
```
- Limpa cache do `ContextBuilder` para a conversa
- Não toca em nenhum estado global (não há mais singleton para invalidar)

---

## Construtor

### `BuildContextUseCase.__init__` @ `:29`
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
- **Não** captura nenhum singleton

---

## Fluxo de `execute`

```
execute(conversation_id, use_cache=True)
└── ContextBuilder.build_context(conversation_id=..., use_cache=...)
    ├── Carrega persona.md (se enable_persona_md)
    ├── Carrega .personagent/rules
    ├── Carrega git context (branch, dirty, ahead/behind)
    ├── Carrega context attachments
    └── Consulta memory_repository (se disponível)
└── retorna ContextBuildResult
```

## Fluxo de `build_request_context`

```
build_request_context(conversation_id, permission_mode="manual", ...)
├── execute(conversation_id, use_cache=...)
└── RequestContext.from_build_result(
        conversation_id=...,
        workspace_root=str(self._workspace_root),
        result=...,
        permission_mode=...,
        tenant_id=...,
        user_id=...,
        request_id=...,
    )
```

---

## Dependências Internas

| Componente | Arquivo | Função |
|------------|---------|--------|
| `ContextBuilder` | `domain/context/services/context_builder.py` | Lógica real de montagem de contexto |
| `ContextBuildResult` | `domain/context/models.py` | Dataclass de resultado |
| `ContextRepository` | `domain/context/repositories.py` | Port para cache de contexto |
| `MemoryRepository` | `domain/memory/repositories/memory_repository.py` | Port para memória de longo prazo |
| `RequestContext` | `application/state/request_context.py` | Snapshot imutável por requisição |

---

## Quando Modificar

### Adicionar nova fonte de contexto
1. Modificar `ContextBuilder.build_context()` em `domain/context/services/context_builder.py`
2. Adicionar campo ao `ContextBuildResult` em `domain/context/models.py`
3. Atualizar este AI-Guide

### Mudar prioridade de persona.md
- Parâmetro `enable_persona_md` no construtor @ `:33`
- Ou modificar `ContextBuilder` para suportar múltiplos arquivos de persona

### Adicionar cache de contexto
- Implementar `ContextRepository` (porta abstrata)
- Injetar no construtor via `context_repository`

### Adicionar campo por requisição
- Adicionar em `RequestContext` (não em `BuildContextUseCase`)
- Atualizar `RequestContext.from_build_result` e `with_overrides`
- Atualizar o passthrough em `build_request_context`

---

## Anti-patterns

- **Nunca** ler arquivos do filesystem diretamente neste use case — delegar ao `ContextBuilder`
- **Nunca** reintroduzir um singleton global para guardar `conversation_id`/`workspace_root` — use `RequestContext`
- **Nunca** passar `use_cache=False` em hot path sem razão — gera I/O repetido

---

## Dependências

- `domain.context.models` — `ContextBuildResult`
- `domain.context.repositories` — `ContextRepository`
- `domain.context.services.context_builder` — `ContextBuilder`
- `domain.memory.repositories.memory_repository` — `MemoryRepository`
- `application.state` — `RequestContext`, `PermissionMode`
- Consumido por: `ChatCompletionUseCase` (via DIContainer)
