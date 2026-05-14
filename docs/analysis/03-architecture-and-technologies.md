# PersonAgent - Arquitetura e Tecnologias

**Data:** 2026-05-14 | **Versao do software:** 0.1.0 (Alpha) | **Classificacao:** Tecnico/Arquitetural

---

## 1. Inventario de Tecnologias

### 1.1 Backend (Python 3.11+)

| Categoria | Tecnologia | Versao | Proposito |
|-----------|-----------|--------|-----------|
| **Web Framework** | FastAPI | >=0.115.0 | API HTTP + SSE + WebSocket |
| **ASGI Server** | Uvicorn | >=0.34.0 | Servidor async |
| **Validacao** | Pydantic + pydantic-settings | >=2.10.0 / >=2.7.0 | Models, settings, validation |
| **Config** | PyYAML + python-dotenv | >=6.0.2 / >=1.0.1 | YAML + .env config |
| **HTTP Client** | httpx + httpx-sse | >=0.28.0 / >=0.4.0 | LLM provider calls, SSE |
| **Auth** | google-auth | >=2.40.0 | Vertex AI authentication |
| **Browser** | Playwright | >=1.56.0 | Browser automation (nao usado diretamente?) |
| **WebSocket** | websockets | >=15.0.0 | Team chat WS |
| **Database** | SQLAlchemy[asyncio] | >=2.0.36 | ORM async |
| **Driver DB** | asyncpg | >=0.30.0 | PostgreSQL async driver |
| **Migrations** | Alembic | >=1.14.0 | Schema migrations (nao implementado) |
| **Vector DB** | pgvector | >=0.4.1 | Embedding storage + HNSW search |
| **Message Queue** | aio-pika | >=9.5.0 | RabbitMQ client (memory queue) |
| **CLI** | Typer + Rich | >=0.15.0 / >=13.9.0 | Command-line interface |
| **Serialization** | orjson | >=3.10.0 | Fast JSON |
| **Logging** | structlog | >=25.1.0 | Structured logging |
| **Retry** | tenacity | >=9.0.0 | Retry logic |
| **Scheduler** | APScheduler | >=3.11.0 | Memory job scheduler |
| **Telemetry** | OpenTelemetry API+SDK | >=1.41.1 | Observabilidade (nao instrumentado) |
| **Build** | Hatchling | - | Build system |

### 1.2 Frontend Desktop (Electron + React)

| Categoria | Tecnologia | Versao | Proposito |
|-----------|-----------|--------|-----------|
| **Runtime** | Electron | >=41.3.0 | Desktop shell |
| **UI Framework** | React | >=19.2.5 | Component system |
| **State** | Zustand | >=5.0.9 | State management |
| **Data Fetching** | TanStack React Query | >=5.100.1 | Server state |
| **Styling** | Tailwind CSS | >=3.4.18 | Utility CSS |
| **UI Primitives** | Radix UI | varios | Dialog, Select, Tabs, Tooltip |
| **Terminal** | node-pty + xterm | >=1.1.0 / >=6.0.0 | Terminal integrado |
| **Markdown** | react-markdown + remark-gfm | - | Chat rendering |
| **Code Highlight** | highlight.js + rehype-highlight | - | Syntax highlighting |
| **Build** | Vite | >=8.0.10 | Bundler + dev server |
| **Language** | TypeScript | >=6.0.3 | Type safety |

### 1.3 Infraestrutura

| Categoria | Tecnologia | Proposito |
|-----------|-----------|-----------|
| **Database** | PostgreSQL 16 + pgvector | Persistencia + vector search |
| **Browser** | LightPanda (nightly) | Browser headless CDP |
| **Message Queue** | RabbitMQ 3.13 | Memory queue (opcional) |
| **LLM Runtime** | llama.cpp + TurboQuant | Inferencia local |
| **Containerizacao** | Docker Compose | Servicos de infra |

---

## 2. Arquitetura Atual

### 2.1 Diagrama de Camadas

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron Desktop App                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │ React UI │  │ Zustand  │  │ API Client│  │ SSE/WS    │  │
│  │ (Chat,   │  │ Stores   │  │ (HTTP)    │  │ Readers   │  │
│  │  Session,│  │           │  │           │  │           │  │
│  │  Browser)│  │           │  │           │  │           │  │
│  └────┬─────┘  └──────────┘  └─────┬─────┘  └─────┬─────┘  │
│       │ IPC/preload                │ HTTP           │ SSE/WS  │
└───────┼────────────────────────────┼────────────────┼────────┘
        │                            │                │
┌───────▼────────────────────────────▼────────────────▼────────┐
│                     FastAPI Backend                           │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ interfaces/api                                          │ │
│  │  Routes: chat, conversations, sessions, memory,         │ │
│  │  workspace, skills, qa, security, artifacts             │ │
│  │  + SSE streaming + WebSocket (team chat)                │ │
│  │  + Local auth middleware + Error mapping                │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │ application                                             │ │
│  │  Use cases: ChatCompletion, BuildContext,               │ │
│  │  Memory (Extract, Consolidate, Recall)                  │ │
│  │  Services: Browser*, Memory*, Session*, NextStep        │ │
│  │  Tools: Orchestrator, Registry, RuntimeConfig           │ │
│  │  Team: TeamChatOrchestrator, Blackboard                 │ │
│  │  State: AppState, StateManager, ToolPermissionContext   │ │
│  │  Security: ProviderDataPolicy                            │ │
│  │  Jobs: MemoryJobScheduler, Workers                      │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │ domain                                                  │ │
│  │  Models: Conversation, Message, InferenceResult         │ │
│  │  Context: ContextBuilder, GitContext, PersonamdLoader   │ │
│  │  Memory: MemoryFile, MemoryTypes, Consolidator,         │ │
│  │         Extractor, RecallSelector, Scanner, Formatter   │ │
│  │  Prompts: PromptBuilder, Sections, Surfaces, Skills     │ │
│  │  Tools: Contracts (Tool, ToolCall, ToolResult, etc.)    │ │
│  │  Repositories: Conversation, LLMBackend (interfaces)    │ │
│  │  Exceptions: 615 LOC de erros tipados                   │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │ infrastructure                                          │ │
│  │  LLM: LlamaCpp, NvidiaNIM, DeepSeek, ZenMux,           │ │
│  │       VertexAI, KimiCoding, CodexSubscription           │ │
│  │  Browser: LightPanda worker, PageCache, ContentCleanup  │ │
│  │  Persistence: PostgreSQL (SQLAlchemy), pgvector,        │ │
│  │               InMemoryContext, FilesystemMemory          │ │
│  │  Tools: Shell, Filesystem, Browser, Web, MCP, LSP,      │ │
│  │         Agent, Planning, Task, Config, Discovery,       │ │
│  │         Worktree, UserInteraction                        │ │
│  │  Config: Settings (pydantic-settings + YAML)            │ │
│  │  Artifacts: File-based artifact storage                  │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
         │              │              │              │
    ┌────▼────┐   ┌─────▼─────┐  ┌────▼────┐  ┌────▼────┐
    │PostgreSQL│   │LightPanda │  │llama.cpp│  │RabbitMQ │
    │+ pgvector│   │  (CDP)    │  │+TurboQnt│  │(opcional)│
    └─────────┘   └───────────┘  └─────────┘  └─────────┘
```

### 2.2 Fluxo de Dados Principal (Chat)

```
Usuario -> Electron Renderer
  -> ChatStore.sendMessage()
    -> API Client POST /chat/completions
      -> ChatRoute.stream_chat()
        -> ChatCompletionUseCase.execute()
          -> BuildContextUseCase (system + user context)
          -> PromptBuilder.build() (system prompt)
          -> enforce_provider_data_policy() (security)
          -> LLMBackend.stream_chat() (inference)
            -> SSE events: reasoning, content, tool_calls
          -> ToolOrchestrator.execute() (tool loop)
            -> ToolRegistry.get() -> Tool.handler()
            -> Tool results -> feed back to LLM
          -> ConversationRepository.persist()
        -> SSE stream to Electron
          -> ChatStore processes events
            -> UI updates (messages, tool blocks, reasoning)
```

### 2.3 Fluxo Team Mode

```
Usuario -> POST /chat/team
  -> TeamChatOrchestrator.run()
    -> Phase 1: Execution Contract (Coordinator)
    -> Phase 2: Independent Round (each agent)
      -> LLMBackend.stream_chat() per agent
      -> Tool execution per agent (if tools_enabled)
    -> Phase 3: Blackboard Publish
      -> Claim deduplication, coverage matrix update
    -> Phase 4: Debate Round (if needed)
    -> Phase 5: Vote
      -> Each agent votes: approve/reject + confidence
    -> Phase 6: Coordinator Final Synthesis
    -> WebSocket events to Electron
```

---

## 3. Avaliacao da Arquitetura

### 3.1 Pontos Fortes da Arquitetura

**A) Clean Architecture Bem Aplicada**

A separacao domain/application/infrastructure/interfaces e genuina:
- Domain nao importa de infrastructure (verificado: domain/ importa apenas de si mesmo)
- Application importa de domain mas nao de infrastructure
- Infrastructure importa de application/domain ports
- Interfaces importa de application e infrastructure

Isso e raro em projetos Python e demonstra maturidade arquitetural.

**B) Tool System Extensivel**

O sistema de ferramentas e bem projetado com:
- ToolDefinition com metadados ricos (group, search_hint, when_to_use, examples)
- ToolRegistry com lookup por nome e alias
- ToolOrchestrator com paralelismo automatico
- build_tool() factory function para criacao declarativa
- ToolPermissionContext com callback de progresso

**C) Provider Abstraction**

LLMBackendRepository como interface abstrata com 7 implementacoes e solido:
- Cada adapter encapsula provider-specific logic
- Streaming SSE uniforme atraves de OpenAI-compatible parser
- Model caching com TTL configuravel
- Timeout e stream_read_timeout separados

**D) Prompt Engineering Sofisticado**

O PromptBuilder com:
- PromptSurfaceRegistry para secoes dinamicas
- AgentStateResolver que adapta o prompt ao estado do agente
- PromptContextAnalyzer que infere modo (writing/exploring/research) da mensagem
- Cache de secoes estaticas
- Token estimation para budget management

### 3.2 Pontos Fracos da Arquitetura

**A) Monolitos de Codigo**

| Arquivo | LOC | Problema |
|---------|-----|----------|
| TeamChatOrchestrator | 3086 | Orquestracao, blackboard, votacao, tool audit, streaming - tudo em um arquivo |
| ChatCompletionUseCase | 2633 | Context build, prompt prep, tool loop, memory, plan mode - tudo em um arquivo |
| LightPandaBrowserWorker | 5735 | CDP connection, page management, content extraction, search, navigation - tudo em um arquivo |
| browser_tools.py | 2786 | 19 ferramentas em um arquivo |
| Settings | 642 | 642 linhas de configuracao em uma classe |

**Impacto**: Dificulta manutencao, testabilidade, e revisao de codigo. Cada um desses deveria ser decomposto em 3-5 modulos.

**B) DIContainer Manual**

O DIContainer (597 LOC) e essencialmente um service locator manual:
- Singletons criados on-demand com lazy initialization
- Sem lifecycle management (exceto close_llm_backends/close_browser_workers)
- Sem escopo por request ou sessao
- Acoplado a Settings (get_settings() como global)

**Impacto**: Impede multi-tenancy, dificulta testes com mocks, nao suporta request-scoped dependencies.

**C) Estado Global**

- AppState e singleton (StateManager.get_instance())
- Settings e singleton (get_settings())
- Browser page cache e global (get_browser_page_cache())
- Tool registry e singleton no container

**Impacto**: Impossivel rodar sessoes isoladas concorrentemente no mesmo processo.

**D) Schema Management Nao-Idiomatico**

O database.py contem:
- TEAM_MODE_SCHEMA_STATEMENTS (8 statements)
- BROWSER_COOPERATION_SCHEMA_STATEMENTS (7 statements)
- OPERATIONAL_MEMORY_SCHEMA_STATEMENTS (30+ statements)

Todos usando `ALTER TABLE ADD COLUMN IF NOT EXISTS` e `CREATE INDEX IF NOT EXISTS`. Isso e:
- Nao versionado (nao da para rollback)
- Nao rastreavel (nao da para saber qual schema esta em producao)
- Nao testavel (nao da para testar migrations)
- Perigoso em producao (DDL sem transacao explicita)

**E) Ausencia de Event Bus/Message Bus**

Comunicacao entre componentes e via chamadas diretas:
- ChatCompletionUseCase chama MemoryService diretamente
- Nao ha desacoplamento entre dominios
- Memory events (capture, recall) sao side-effects inline

**Impacto**: Dificulta adicionar novos consumidores de eventos (analytics, audit, notifications).

---

## 4. Recomendacoes Arquiteturais

### 4.1 Decomposicao de Monolitos

**TeamChatOrchestrator -> Modulos:**
```
team_chat/
  orchestrator.py          # Coordenacao de fases (200 LOC)
  blackboard.py            # Blackboard + claim graph (400 LOC)
  phases/
    independent_round.py   # Logica de round independente
    debate_round.py        # Logica de debate
    vote_round.py          # Votacao + consenso
    execution_contract.py  # Contrato de execucao
    coordinator.py         # Sintese final
  tool_policy.py           # Guarded autonomy + audit
  streaming.py             # WebSocket event emission
```

**ChatCompletionUseCase -> Modulos:**
```
use_cases/chat/
  completion.py            # Orquestracao principal (300 LOC)
  context_preparation.py   # Context build + prompt prep
  tool_loop.py             # Tool execution loop
  stream_state.py          # SSE state management
  plan_mode_integration.py # Plan mode hooks
  memory_integration.py    # Memory recall + capture
```

**LightPandaBrowserWorker -> Modulos:**
```
browser/
  worker.py                # Core CDP connection (500 LOC)
  page_manager.py          # Page lifecycle, tabs, navigation
  content_extractor.py     # DOM extraction + cleanup
  search_handler.py        # Search provider integration
  screenshot.py            # Screenshot capture + cache
  script_runner.py         # JavaScript execution
  session_manager.py       # Browser session TTL
```

### 4.2 DI Container Evolucao

**Atual:** Service Locator manual com singletons

**Recomendado:** Dependency Injection com scoping

```python
# Opcao A: FastAPI Depends (simples, pragmtico)
def get_chat_use_case(
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
    llm_backend: LLMBackendRepository = Depends(get_llm_backend),
    ...
) -> ChatCompletionUseCase:
    return ChatCompletionUseCase(conversation_repo, llm_backend, ...)

# Opcao B: python-inject ou injector (mais estruturado)
# Melhor para multi-tenancy com scoped bindings
```

### 4.3 Multi-Tenancy

**Evolucao necessaria:**
1. AppState -> SessionState (por request/conversation)
2. DIContainer -> Container com scopes (singleton, request, session)
3. Settings -> Settings + TenantConfig (por usuario/workspace)
4. Database -> RLS (Row Level Security) ou tenant_id em todas as tabelas

### 4.4 Event Bus

**Recomendacao:** Implementar event bus interno para desacoplamento:

```python
# Eventos do dominio
class DomainEvent:
    conversation_created: ConversationCreatedEvent
    tool_executed: ToolExecutedEvent
    memory_captured: MemoryCapturedEvent
    browser_action: BrowserActionEvent

# Consumidores
MemoryCaptureConsumer -> escuta tool_executed
AuditLogConsumer -> escuta todos
AnalyticsConsumer -> escuta todos
NotificationConsumer -> escuta conversation_created
```

### 4.5 Migrations Versionadas

**Recomendacao:** Alembic com migrations reais:

```bash
# Inicializar
cd @backend
alembic init infrastructure/persistence/migrations

# Criar migration
alembic revision --autogenerate -m "add_team_mode_tables"

# Aplicar
alembic upgrade head

# Rollback
alembic downgrade -1
```

Remover todos os DDL statements inline do database.py.

### 4.6 Observabilidade

**Stack recomendada:**

| Componente | Tecnologia | Proposito |
|------------|-----------|-----------|
| **Metrics** | Prometheus + Grafana | Request latency, tool execution time, LLM token usage |
| **Traces** | OpenTelemetry + Jaeger | Distributed tracing de requests |
| **Logs** | structlog + Loki | Structured logging centralizado |
| **Alerts** | Alertmanager | Alertas de erro rate, latency, resource usage |

**Instrumentacao prioritaria:**
- LLM inference latency e token usage
- Tool execution time e error rate
- Browser CDP round-trip time
- Memory recall latency
- Database query time

---

## 5. Avaliacao de Tecnologias Especificas

### 5.1 FastAPI - Adequacao: Excelente

FastAPI e a escolha correta para este tipo de aplicacao:
- Async nativo combina com LLM streaming e tool execution
- Pydantic integration para validacao
- SSE e WebSocket nativos
- OpenAPI docs automatico
- Performance competitiva

**Risco baixo**: FastAPI e maduro e bem mantido.

### 5.2 SQLAlchemy Async - Adequacao: Boa

SQLAlchemy async com asyncpg e funcional mas:
- ORM declarative_base e legado (recomendado: DeclarativeBase com mapped_column)
- Sem unit of work pattern explicito
- Pool size 10 com max_overflow 20 e razoavel para single-tenant

**Recomendacao**: Migrar para SQLAlchemy 2.0 style (DeclarativeBase, Mapped, mapped_column).

### 5.3 Electron - Adequacao: Aceitavel

Electron e a escolha padrao para desktop apps com web tech, mas:
- Bundle size grande (~150MB+)
- Consumo de memoria elevado
- node-pty para terminal e funcional mas requer native modules
- Build para multi-plataforma e complexo (electron-builder)

**Alternativas consideradas:**
- **Tauri**: Mais leve, Rust-based, mas sem node-pty nativo
- **Wails**: Go-based, mas ecossistema menor

**Recomendacao**: Manter Electron por ora (node-pty e terminal integrado sao essenciais). Considerar Tauri para versao 2.0 se bundle size for problema.

### 5.4 LightPanda - Adequacao: Risco Medio

LightPanda e um browser headless em Go, leve e rapido, mas:
- Imagem Docker "nightly" (instabilidade)
- CDP implementation parcial (nem todos os comandos funcionam)
- Sem suporte a JavaScript complexo (SPAs podem falhar)
- Documentacao limitada

**Alternativas:**
- **Playwright/Chromium**: Mais completo, mas mais pesado (~300MB)
- **Crawl4AI**: Especializado em extracao, sem CDP interativo

**Recomendacao**: Manter LightPanda como default, adicionar Playwright como fallback para sites que precisam de JS completo.

### 5.5 RabbitMQ - Adequacao: Over-Engineered

RabbitMQ esta no docker-compose mas o memory queue e opcional (MEMORY_QUEUE_ENABLED=false por default). Para single-tenant local, RabbitMQ e overkill.

**Recomendacao**:
- Curto prazo: Remover RabbitMQ, usar asyncio.Queue interno
- Medio prazo: Para multi-tenant SaaS, usar Redis Streams (mais simples e ja planejado)
- Longo prazo: Para escala real, Kafka ou NATS

### 5.6 pgvector - Adequacao: Excelente

pgvector com HNSW indexes e a escolha correta para vector search:
- Integra nativamente com PostgreSQL (sem DB adicional)
- HNSW e eficiente para recall semantico
- subvector search permite queries parciais em embeddings grandes

**Recomendacao**: Manter. Considerar pgvectorscale para melhor performance em escala.

---

## 6. Modificacoes Necessarias para Robustez

### 6.1 Criticas (Impedem Deploy)

| # | Modificacao | Esforco | Detalhes |
|---|-------------|---------|----------|
| 1 | Alembic migrations | 2-3 semanas | Migrar todos os DDL inline para migrations versionadas |
| 2 | Multi-tenancy basico | 4-6 semanas | Session-scoped state, workspace ownership |
| 3 | Container Docker do backend | 1 semana | Dockerfile + compose prod + health checks |
| 4 | CI/CD pipeline | 1-2 semanas | GitHub Actions: lint, test, build, deploy |
| 5 | Decomposicao dos monolitos | 3-4 semanas | TeamChat, ChatCompletion, LightPanda, browser_tools |

### 6.2 Importantes (Impedem Escala)

| # | Modificacao | Esforco | Detalhes |
|---|-------------|---------|----------|
| 6 | DI container com scoping | 2-3 semanas | FastAPI Depends ou python-inject |
| 7 | Event bus interno | 2 semanas | Desacoplamento de dominios |
| 8 | Observabilidade basica | 2 semanas | Metrics endpoint + structured logs + traces |
| 9 | Rate limiting | 1 semana | slowapi ou custom middleware |
| 10 | API versioning | 1 semana | /v1/ prefix em todas as rotas |

### 6.3 Desejaveis (Melhoram Manutenibilidade)

| # | Modificacao | Esforco | Detalhes |
|---|-------------|---------|----------|
| 11 | SQLAlchemy 2.0 style | 2 semanas | DeclarativeBase, Mapped, mapped_column |
| 12 | Settings decomposition | 1 semana | Separar em AppSettings, LlmSettings, DbSettings, etc. |
| 13 | Type-safe API client | 1 semana | Gerar client.ts a partir do OpenAPI schema |
| 14 | Error handling padronizado | 1 semana | Garantir que todas as routes usem error envelope |
| 15 | Test coverage > 80% | 3-4 semanas | Cobrir caminhos nao testados |

---

## 7. A Arquitetura Supre as Necessidades?

### 7.1 Para o Estado Atual (Alpha, single-user, local)

**Sim, a arquitetura supre bem as necessidades atuais.** A separacao em camadas, o sistema de ferramentas extensivel, e a abstracao de providers sao adequados para um agente pessoal local-first. O estado singleton e aceitavel para single-tenant.

### 7.2 Para Deploy Multi-Usuario

**Nao, a arquitetura nao supre sem modificacoes significativas.** Os bloqueadores sao:

1. **Estado global** (AppState, Settings, Browser caches) - precisa de scoping
2. **Sem autenticacao** - precisa de User model + JWT
3. **Sem isolamento de workspace** - precisa de ownership + ACL
4. **DIContainer singleton** - precisa de request/session scoping
5. **Migrations nao-versionadas** - precisa de Alembic real

### 7.3 Para Escala Horizontal

**Nao, a arquitetura nao suporta escala horizontal.** Para isso:

1. **Stateless backend**: Remover estado em memoria (AppState -> Redis, Browser cache -> Redis)
2. **External session store**: Redis para sessoes de usuario
3. **Message queue**: Redis Streams ou Kafka para eventos
4. **Object storage**: S3/MinIO para artifacts (em vez de filesystem local)
5. **Load balancer**: Nginx/HAProxy com sticky sessions ou WebSocket routing

---

## 8. Conclusao

A arquitetura do PersonAgent e **tecnicamente solida para seu estagio de maturidade**. A Clean Architecture e genuina, o sistema de ferramentas e bem projetado, e as abstracoes de dominio sao ricas. No entanto, a arquitetura foi desenhada para **single-tenant local-first** e precisa de evolucao significativa para suportar **multi-usuario e escala horizontal**.

As modificacoes mais urgentes sao:
1. Decomposicao dos monolitos de codigo (manutenibilidade)
2. Alembic migrations versionadas (seguranca de deploy)
3. DI container com scoping (multi-tenancy)
4. Autenticacao e isolamento (seguranca)
5. Observabilidade (operabilidade)
