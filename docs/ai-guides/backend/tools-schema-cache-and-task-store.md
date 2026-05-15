# AI-Guide: Tool Schema Cache and Task Store


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

`ToolSchemaCache` evita reconstrução repetida de schemas OpenAI-compatible para tools. `TaskStore` (com implementação `InMemoryTaskStore`) persiste tarefas criadas por ferramentas do grupo `TASK`.

---

## ToolSchemaCache

### `ToolSchemaCache.get_or_build` @ `application/tools/schema_cache.py:22`
```python
def get_or_build(
    self,
    *,
    tools: list[Tool],
    allowed_tools: set[str] | None,
    include_deferred: bool,
    cache_scope: str,
) -> list[dict[str, Any]]
```
- **Parâmetros**:
  - `tools` — lista de instâncias `Tool`
  - `allowed_tools` — subset permitido (se `None`, todas)
  - `include_deferred` — incluir tools que devem ser deferred?
  - `cache_scope` — string para namespace do cache (ex: `"chat:{conversation_id}"`)
- **Retorna**: lista de schemas `{"type":"function","function":{...}}`
- Side effect: incrementa `hits` ou `misses`

### `ToolSchemaCache.clear` @ `:46`
```python
def clear(self) -> None
```
- Limpa cache interno e reseta contadores

### Cache Key
- Gerado por `_key()` @ `:52`
- Inclui: `scope`, `allowed_tools` sorted, `include_deferred`, e para cada tool: `name`, `aliases`, `strict`, `defer`, `always_load`, `enabled`
- Hash: SHA256 de JSON sort_keys

---

## TaskStore

### Protocolo `TaskStore` @ `application/tools/task_store.py:43`
```python
class TaskStore(Protocol):
    async def create(self, record: TaskRecord) -> TaskRecord: ...
    async def get(self, task_id: str) -> TaskRecord | None: ...
    async def update(self, task_id: str, values: dict[str, Any]) -> TaskRecord | None: ...
    async def list(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]: ...
```

### `InMemoryTaskStore` @ `:61`
- Implementação em memória para testes
- `_records: dict[str, TaskRecord]`
- `update()` aceita apenas: `title`, `description`, `status`, `priority`, `output`, `metadata`
- `list()` filtra por `conversation_id` e `status`, ordena por `updated_at` desc

### `TaskRecord` @ `:11`
```python
@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str
    title: str
    description: str = ""
    status: str = "open"           # open | in_progress | done | cancelled
    priority: str = "normal"      # low | normal | high | urgent
    conversation_id: str | None = None
    workspace_root: str | None = None
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
```
- `to_dict()` — serializa para dict com ISO datetime strings

### `new_task_record` @ `:104`
```python
def new_task_record(
    *,
    title: str,
    description: str = "",
    status: str = "open",
    priority: str = "normal",
    conversation_id: str | None = None,
    workspace_root: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskRecord
```
- Gera `id = str(uuid4())`

---

## Quando Modificar

### Adicionar persistência SQL a TaskStore
1. Criar `SQLAlchemyTaskStore` implementando protocolo `TaskStore`
2. Adicionar tabela `tasks` no ORM
3. Registrar no DIContainer em vez de `InMemoryTaskStore`

### Mudar campos de TaskRecord
1. Adicionar campo ao dataclass @ `:11`
2. Atualizar `to_dict()` @ `:27`
3. Atualizar `InMemoryTaskStore.update()` @ `:74` para aceitar novo campo
4. Atualizar `new_task_record()` @ `:104`

### Ajustar cache de schemas
- Modificar `_key()` @ `:52` para incluir novos atributos relevantes
- O cache usa `copy.deepcopy` — seguro para schemas mutáveis

---

## Anti-patterns

- **Nunca** modificar a lista retornada por `get_or_build()` — é uma deep copy, mas alterá-la não afeta o cache
- **Nunca** usar `InMemoryTaskStore` em produção sem persistência — dados se perdem em restart
- **Nunca** criar `TaskRecord` diretamente — use `new_task_record()` para garantir UUID e timestamps

---

## Dependências

- `domain.tools` — `Tool`
- Consumido por: `ToolOrchestrator` (schema cache), `ToolRegistry` (task store)