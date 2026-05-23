# AI-Guide: Backend Dependency Graph


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Visão geral

Este documento mapea as dependências entre subsistemas do backend. Use-o para entender o impacto de uma mudança antes de editar código.

---

## Grafo de Subsistemas

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DIContainer                                    │
│  (interfaces/config/di_container.py)                                        │
│  Wire todos os singletons e factories                                       │
└──────────┬────────────────────────────────────────────────────────────────┘
           │
     ┌─────┴─────┬─────────────┬──────────────┬──────────────┬──────────┐
     ▼           ▼             ▼              ▼              ▼          ▼
┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│LLM     │  │Process   │  │Tool      │  │Prompt    │  │State     │  │Context  │
│Backends│  │Managers  │  │Registry  │  │Builder   │  │Manager   │  │Builder  │
└────┬───┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘
     │           │             │             │             │             │
     ▼           │             │             │             │             │
┌──────────────────────────────────────────────────────────────────────────┐
│                    ChatCompletionUseCase                                   │
│   (application/use_cases/chat_completion.py)                               │
│   Orquestra: prompt → LLM → tools → streaming → persistência              │
└──────┬────────────────┬───────────────┬─────────────┬──────────────────────┘
       │                │               │             │
       ▼                ▼               ▼             ▼
┌─────────────┐  ┌────────────┐  ┌──────────┐  ┌──────────┐
│SessionTitle │  │NextStep    │  │Session   │  │Build     │
│Service      │  │Suggestion  │  │Memory    │  │Context   │
└─────────────┘  └────────────┘  └──────────┘  └──────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     ToolOrchestrator                                  │
│  (application/tools/orchestrator.py)                                 │
│  Executa tool calls: valida → permissão → executa → resultado       │
└──────┬────────────┬──────────────┬───────────────────────────────────┘
       │            │              │
       ▼            ▼              ▼
┌──────────┐  ┌──────────┐  ┌────────────────┐
│ToolSchema│  │TaskStore │  │BrowserAction   │
│Cache     │  │(tasks)   │  │Arbiter         │
└──────────┘  └──────────┘  └────────────────┘
       │                           │
       │                           ▼
       │              ┌────────────────────────┐
       │              │BrowserCooperation     │
       │              │BrowserWorkspace       │
       │              └────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        LLM Adapters                                   │
│  LlamaCpp | NvidiaNim | DeepSeek | ZenMux | Vertex | Kimi | Codex    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Matriz de Impacto

### Se modificar X, quem quebra?

| Modificar em... | Impacta diretamente | Testes que quebram |
|-------------------|---------------------|-------------------|
| `LLMBackendRepository` interface | Todos os 7 adapters | `tests/unit/llm/`, `tests/integration/test_chat.py` |
| `LlamaCppAdapter` | Chat, Team Mode, SessionTitle, NextStep, SessionMemory | `tests/integration/test_llama_local.py` |
| `ToolOrchestrator` | Chat, Team Mode | `tests/integration/test_tools.py`, `tests/test_browser_tools.py` |
| `BrowserActionArbiter` | Browser tools | `tests/test_browser_cooperation.py` |
| `BrowserCooperation` | BrowserActionArbiter, BrowserWorkspace | `tests/integration/test_browser.py` |
| `PromptBuilder` | Chat, Team Mode | `tests/unit/prompts/test_prompt_builder.py` |
| `PromptContextAnalyzer` | Chat (auto-mode) | `tests/unit/prompts/test_context_analyzer.py` |
| `BuildContextUseCase` | Chat | `tests/unit/use_cases/test_context.py` |
| `RequestContext` | Chat, BuildContext | `tests/unit/test_request_context.py` |
| `SessionTitleService` | Chat (background job) | `tests/unit/services/test_session_titles.py` |
| `OperationalMemoryService` | Chat (recall), Memory jobs | `tests/integration/test_memory.py` |
| `MemoryJobScheduler` | Background jobs | `tests/unit/jobs/test_scheduler.py` |
| `CommandRegistry` | Chat (slash commands) | `tests/unit/domain/prompts/test_commands.py` |
| `ToolRegistry` | ToolOrchestrator | `tests/unit/tools/test_registry.py` |
| `DIContainer` | Tudo | `tests/integration/` (smoke tests) |
| `AppState` | (none — dataclass passiva) | n/a |
| `QARuntimeTracer` | QA subsystem apenas | `tests/integration/test_qa.py` |
| `PythonCodeIndexer` | QA subsystem apenas | `tests/unit/qa/test_indexer.py` |

---

## Camadas de Dependência

### Regra: Domain não conhece nenhuma outra camada

```
Domain (entidades, contratos, exceções)
    ▲
    │ (interfaces/ports)
Application (use cases, serviços, orquestradores)
    ▲
    │ (implementações concretas)
Infrastructure (adapters, ORM, process managers)
    ▲
    │ (wiring)
Interfaces (FastAPI, DIContainer, lifespan)
```

### Quebras da regra (documentadas)

| Quebra | Onde | Por quê |
|--------|------|---------|
| ~~`StateManager` singleton acessado de use cases~~ | Removido na Fase 0.3 | Substituído por `RequestContext` imutável por requisição |
| `DIContainer` importa tudo | `interfaces/config/di_container.py` | É o wiring layer; aceitável |

---

## Dependências Externas (Bibliotecas)

| Biblioteca | Onde usada | Substituição?
|------------|-----------|--------------|
| `fastapi` | Interfaces layer | Difícil — reescreveria toda API |
| `sqlalchemy[asyncio]` | Infrastructure persistence | Difícil — reescreveria todo ORM |
| `asyncpg` | Infrastructure persistence | Possível (psycopg3) |
| `httpx` | LLM adapters | Possível (aiohttp) |
| `structlog` | Logging em todo lugar | Possível (logging padrão) |
| `apscheduler` | MemoryJobScheduler | Possível (celery, arq) |
| `aio-pika` | OperationalMemoryQueue | Possível (redis, kafka) |
| `tenacity` | LlamaCppAdapter retry | Possível (retry manual) |
| `tiktoken` | Token counting (se usado) | Possível (tokenizers) |

---

## Subsistemas Orfãos (sem upstream)

Subsistemas que nenhum outro depende diretamente (podem ser modificados livremente):
- `QA` (usado apenas por rotas `/qa/*`)
- `SessionPanel` (usado apenas por rotas de sessão)
- `NextStepSuggestion` (feature opt-in, pode ser removido)

---

## Subsistemas de Alto Acoplamento (modificar com cuidado)

Subsistemas com >5 dependências downstream:
- `DIContainer` — afeta tudo
- `ChatCompletionUseCase` — orquestra 8+ subsistemas
- `ToolOrchestrator` — afeta chat e team mode
- `PromptBuilder` — afeta todo fluxo de chat