# AI-Guide: QA Indexer and Redaction

## Propósito

`PythonCodeIndexer` constrói grafo estático do código Python/FastAPI (módulos, classes, funções, endpoints, imports, calls). `QARedactionPolicy` remove dados sensíveis de traces e artifacts antes de persistência.

---

## PythonCodeIndexer

### `PythonCodeIndexer.__init__` @ `application/qa/indexer.py:50`
```python
def __init__(self, repo_root: Path, *, app: FastAPI | None = None) -> None
```
- `repo_root` — raiz do repositório a indexar
- `app` — instância FastAPI opcional para extrair rotas runtime

### `PythonCodeIndexer.build` @ `:59`
```python
def build(self, *, include_tests: bool = True) -> QACodeGraph
```
- Retorna `QACodeGraph` com nodes e edges
- Pipeline:
  1. `_parse_modules()` — parseia AST de todos os `.py`
  2. `_index_file_node()` — cria node FILE por módulo
  3. `_index_module()` — cria nodes CLASS, FUNCTION, METHOD
  4. `_index_import_edges()` — cria edges IMPORT
  5. `_link_static_calls()` — tenta linkar calls a definitions
  6. `_index_fastapi_runtime_routes()` — adiciona nodes ENDPOINT (se `app` fornecido)

### Diretórios ignorados
`IGNORED_DIRS` @ `:25`
```python
{
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "__pycache__", "build", "dist", "node_modules",
}
```

---

## Tipos de Node (CodeNodeKind)

| Kind | Descrição | Fonte |
|------|-----------|-------|
| `FILE` | Arquivo Python | AST module |
| `CLASS` | Definição de classe | AST ClassDef |
| `FUNCTION` | Função/ método de módulo | AST FunctionDef / AsyncFunctionDef |
| `METHOD` | Método de classe | AST FunctionDef dentro de ClassDef |
| `ENDPOINT` | Rota FastAPI | Runtime app.routes |
| `VARIABLE` | Variável de módulo | AST Assign |

## Tipos de Edge (CodeEdgeKind)

| Kind | Descrição |
|------|-----------|
| `IMPORT` | `from X import Y` |
| `INHERITANCE` | `class A(B)` |
| `CALL` | Chamada de função |
| `CONTAINS` | FILE → contém → CLASS/FUNCTION |
| `RUNTIME_ROUTE` | ENDPOINT → aponta para → FUNCTION handler |

---

## QACodeGraph

```python
@dataclass
class QACodeGraph:
    nodes: list[CodeNodeData]
    edges: list[CodeEdgeData]
    stats: dict[str, Any]
```

### CodeNodeData
- `id: str` — hash determinístico
- `kind: CodeNodeKind`
- `name: str`
- `file_path: str | None`
- `start_line: int | None`
- `end_line: int | None`
- `parent_id: str | None`

### CodeEdgeData
- `id: str`
- `kind: CodeEdgeKind`
- `source_id: str`
- `target_id: str | None`
- `label: str | None`

---

## QARedactionPolicy

### `redact_mapping` @ `application/qa/redaction.py:24`
```python
def redact_mapping(
    value: Mapping[str, Any] | None,
    *, max_string: int = 2_000,
) -> dict[str, Any]
```
- Redacta valores cujas keys contêm fragments sensíveis
- Recursivo para mappings aninhados

### `redact_value` @ `:32`
```python
def redact_value(value: Any, *, max_string: int = 2_000) -> Any
```
- Entry point quando não há contexto de key

### Fragments sensíveis (`SENSITIVE_KEY_FRAGMENTS` @ `:8`)
```python
(
    "authorization", "api_key", "apikey", "access_token",
    "refresh_token", "secret", "password", "passwd",
    "cookie", "session", "private_key", "client_secret",
)
```

### Regras de redação
- Key match → valor substituído por `"[REDACTED]"`
- Strings > `max_string` chars → truncadas
- Bytes → decode UTF-8 + truncate
- Listas/tuplas → processadas recursivamente (max 100 items)

---

## Quando Modificar

### Adicionar novo tipo de node
1. Adicionar valor a `CodeNodeKind` em `contracts.py`
2. Modificar `_index_module()` ou método equivalente em `indexer.py`
3. Atualizar `QASessionService` se necessário

### Ajustar redação
- Adicionar fragment a `SENSITIVE_KEY_FRAGMENTS` @ `redaction.py:8`
- Modificar `max_string` default se necessário

### Suportar outro framework web
- Modificar `_index_fastapi_runtime_routes()` para extrair rotas do framework
- Ou adicionar método paralelo

---

## Anti-patterns

- **Nunca** persistir trace sem chamar `redact_mapping()` primeiro
- **Nunca** confiar 100% em `_link_static_calls()` — é best-effort e pode falhar com imports dinâmicos
- **Nunca** indexar `.venv` ou `node_modules` — verificar `IGNORED_DIRS`

---

## Dependências

- `application.qa.contracts` — `QACodeGraph`, `CodeNodeData`, `CodeEdgeData`, `CodeNodeKind`, `CodeEdgeKind`
- `fastapi` — `FastAPI`, `APIRoute`, `APIWebSocketRoute` (para indexar endpoints)
- Consumido por: `QASessionService` (indexação), `QARuntimeTracer` (redação de payloads)
