# QA Tracing no PersonAgent

## Visão geral

O subsistema de QA permite indexar o código-fonte do backend, rastrear a execução de requests em tempo real e analisar o caminho percorrido por uma requisição.

## Componentes

| Componente | Função |
|------------|--------|
| `PythonCodeIndexer` | Indexa código estático em grafo |
| `PythonRuntimeTracer` | Captura call/return/line/exception em tempo real |
| `QASessionService` | Coordena sessões, indexação e execução |
| `QARuntimeEventBus` | Pub/sub em memória para SSE |

## Fluxo

1. **Criar sessão**: `POST /qa/sessions` vincula a um repo/workspace.
2. **Indexar**: `POST /qa/sessions/{id}/index` constrói o grafo estático.
3. **Executar**: `POST /qa/sessions/{id}/requests` roda um request ASGI sob tracing.
4. **Stream**: `GET /qa/sessions/{id}/stream` emite eventos SSE em tempo real.
5. **Analisar**: `GET /qa/sessions/{id}/graph` retorna grafo + runtime overlay.

## Grafo de Código

- **Nodes**: módulos, controllers, services, repositories, functions, endpoints.
- **Edges**: imports, calls, inheritance, runtime_call.
- Persistido em `qa_code_nodes` e `qa_code_edges`.

## Tracing

- Usa `sys.monitoring` (Python 3.12+) com fallback para `sys.settrace`.
- Exclui paths internos do QA, site-packages e `.venv`.
- Redacta headers e payloads antes de persistir.

## Sandbox

- Modo `worktree` cria uma branch Git temporária para testes seguros.
- `branch_name`: `codex/qa/{session_id}`.

## Referências

- ADR 0014: QA Tracing System
