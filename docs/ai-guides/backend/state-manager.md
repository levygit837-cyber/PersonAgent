# AI-Guide: State Manager


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Singleton que mantém estado global da aplicação em memória: contexto da conversa atual, workspace, permissões, métricas, caches de prompt. Thread-safe por design (processo único).

---

## Entry Points

### `StateManager.get_instance` @ `application/state/services/state_manager.py:29`
```python
@classmethod
def get_instance(cls) -> StateManager
```
- Cria instância se não existir
- **Nunca** chamar `StateManager()` diretamente — sempre `get_instance()`

### `StateManager.reset` @ `:40`
```python
@classmethod
def reset(cls) -> None
```
- Reseta singleton (útil apenas para testes)

---

## Estado da Conversa

### `set_conversation_id` @ `:68`
```python
def set_conversation_id(self, conversation_id: str) -> None
```
- Delega para `AppState.with_conversation()`

### `get_conversation_id` @ `:76`
```python
def get_conversation_id(self) -> str
```

### `set_workspace_root` @ `:80`
```python
def set_workspace_root(self, workspace_root: str) -> None
```

### `get_workspace_root` @ `:88`
```python
def get_workspace_root(self) -> str
```

---

## Contexto

### `set_system_context` @ `:121`
```python
def set_system_context(self, context: dict[str, Any]) -> None
```
- Armazena cópia do dict
- Atualiza timestamp

### `set_user_context` @ `:134`
```python
def set_user_context(self, context: dict[str, Any]) -> None
```

### `get_system_context` @ `:117`
```python
def get_system_context(self) -> dict[str, Any]
```
- Retorna **cópia** (não referência)

---

## Permissões e Allowlist

### `set_permission_mode` @ `:92`
```python
def set_permission_mode(self, mode: str) -> None
```
- Modos: `auto`, `manual`, `ask`

### `add_allowed_tool` @ `:143`
```python
def add_allowed_tool(self, tool_name: str) -> None
```

### `remove_allowed_tool` @ `:151`
```python
def remove_allowed_tool(self, tool_name: str) -> None
```

### `get_allowed_tools` @ `:159`
```python
def get_allowed_tools(self) -> set[str]
```

---

## Métricas

### `increment_request_count` @ `:163`
```python
def increment_request_count(self) -> int
```

### `add_cost` @ `:172`
```python
def add_cost(self, cost_usd: float) -> float
```

### `add_api_duration` @ `:184`
```python
def add_api_duration(self, duration_ms: int) -> int
```

### `add_tool_duration` @ `:196`
```python
def add_tool_duration(self, duration_ms: int) -> int
```

### `add_tokens_used` @ `:208`
```python
def add_tokens_used(self, tokens: int) -> int
```

### `get_metrics` @ `:220`
```python
def get_metrics(self) -> dict[str, Any]
```
- Retorna: `total_cost_usd`, `total_api_duration_ms`, `total_tool_duration_ms`, `total_tokens_used`, `request_count`

---

## Cache

### `cache_system_prompt` @ `:238`
```python
def cache_system_prompt(self, key: str, value: str) -> None
```

### `get_cached_system_prompt` @ `:247`
```python
def get_cached_system_prompt(self, key: str) -> str | None
```

### `cache_context` @ `:258`
```python
def cache_context(self, key: str, value: dict[str, Any]) -> None
```

### `get_cached_context` @ `:267`
```python
def get_cached_context(self, key: str) -> dict[str, Any] | None
```

### `clear_caches` @ `:234`
```python
def clear_caches(self) -> None
```
- Limpa todos os caches do `AppState`

---

## AppState

`AppState` @ `application/state/app_state.py` — dataclass que realmente mantém os dados.
- `conversation_id: str = ""`
- `workspace_root: str = ""`
- `permission_mode: str = "manual"`
- `system_context: dict[str, Any] = {}`
- `user_context: dict[str, Any] = {}`
- `settings: dict[str, Any] = {}`
- `allowed_tools: set[str] = set()`
- `request_count: int = 0`
- `total_cost_usd: float = 0.0`
- `total_api_duration_ms: int = 0`
- `total_tool_duration_ms: int = 0`
- `total_tokens_used: int = 0`
- `session_id: str = ""`

---

## Quando Modificar

### Adicionar novo campo global
1. Adicionar campo a `AppState` em `app_state.py`
2. Adicionar getter/setter em `StateManager`
3. Atualizar `reset_state()` se necessário

### Ajustar modo de permissão default
- Modificar default em `AppState` ou `set_permission_mode()`

---

## Anti-patterns

- **Nunca** criar `StateManager()` diretamente — use `get_instance()`
- **Nunca** modificar `_state` diretamente — use setters
- **Nunca** confiar em `get_system_context()` para mutação — ele retorna cópia
- **Nunca** manter referências a dicts retornados — sempre trabalhe com cópias

---

## Dependências

- `application.state.app_state` — `AppState`
- Consumido por: `BuildContextUseCase`, `ChatCompletionUseCase`, `PromptBuilder`, `ToolOrchestrator`