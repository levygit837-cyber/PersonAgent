# PersonAgent — Análise de Arquitetura, Harness e Viabilidade de Escala

Análise feita em 2026-05-23 sobre `levygit837-cyber/PersonAgent` (52 commits, ~3 semanas de evolução, atualmente em alpha local-first/desktop).

Resultado: arquitetura tem boa intenção e o harness de agente é dos pontos mais fortes do projeto; mas a base atual é "single-user / single-process" em vários lugares críticos. Dá pra transformar em app escalável — porém **com refator dirigido, não com rewrite em Go**.

---

## Resultado

- A arquitetura Clean (domain → application → infrastructure → interfaces) está honesta no contorno principal: `domain/` tem zero imports vindos de `application` ou `infrastructure`. Isso é raro de ver bem feito.
- O harness de agente é o ativo mais valioso do repo: orquestrador de tools com paralelismo seguro, registry com permission model, Plan Mode, Team Mode (blackboard + debate + voto + execution contract), 7 adapters de LLM com streaming, RAG operacional com pgvector + HNSW, e prompt builder dinâmico por estado/modo/skill.
- O código tem boa intenção mas três classes de problema estruturais: god files (chat_completion 2633 linhas, team_chat 3086, lightpanda 5735, browser_tools 2786, chat-store.ts 3305, session-panel.tsx 3960), `dict[str, Any]` espalhado (985 ocorrências no backend) e estado global mutável singleton.
- Não está pronto para multi-tenant: zero `user_id`/`tenant_id` nos modelos, auth é um token compartilhado local para o Electron, `StateManager` é um singleton de processo, migrations são `Base.metadata.create_all` + ALTERs hardcoded.
- Migrar para Go custaria 4-6 meses de rewrite com perda de velocidade — e em troca de quê? Os trechos que mais aproveitariam Go (embeddings, tool fan-out, browser worker pool) são uma fração pequena do código. O coração — prompt builder, team orchestrator, memory consolidation — é Python sweet spot. **Recomendação: não migrar. Refator faseado em Python, e só extrair serviço em Go se um gargalo concreto aparecer.**

---

## 1. Análise de Arquitetura

### Camadas e dependências

```
domain/         (modelos, ports, regras puras)           ~13k linhas
  ├── models/, repositories/, services/, prompts/, tools/, exceptions.py (49 erros tipados)
application/    (use cases, orquestradores, services)    ~18k linhas
  ├── use_cases/ (chat_completion, build_context, ...)
  ├── team_chat/ (orchestrator com blackboard, debate, voto)
  ├── tools/     (registry + orchestrator)
  ├── services/  (operational_memory, browser_workspace, ...)
  └── state/     (AppState + StateManager singleton)
infrastructure/ (adapters concretos)                     ~25k linhas
  ├── llm/       (7 adapters: llama, nvidia, vertex, kimi, deepseek, zenmux, codex)
  ├── browser/   (lightpanda CDP, 5735 linhas num arquivo)
  ├── tools/     (filesystem, shell, browser, mcp, worktree, ...)
  └── persistence/ (SQLAlchemy async + pgvector + 30 tabelas)
interfaces/     (FastAPI, CLI, DI container)             ~7k linhas
```

**O bom**: domain é limpo. Imports de `domain/*` para `application/*` ou `infrastructure/*`: **zero**.

**O ruim**:
- `application/` importa de `infrastructure/` em 8 lugares (artifacts utils, ORM models, embedding adapter). Tecnicamente quebra Clean Architecture — application deveria depender de ports/repositories abstratos, não de modelos ORM concretos.
- `domain/context/services/git_context.py` chama `subprocess.run` direto. I/O bloqueante na camada domain.
- Vários `subprocess.run` síncronos dentro de fluxos `async` (em `qa/service.py`, `session_panel.py`, `git_context.py`). Em desktop single-user passa; sob carga concorrente isso prende o event loop.

### Fluxo principal (chat sync)

```
HTTP request (FastAPI route)
   → ChatCompletionUseCase.execute()
   → BuildContext (workspace state, system context, user context)
   → PromptBuilder (compõe sections por mode/state/skill/command)
   → LLMBackend.chat_completion()
   → parse tool_calls
   → ToolOrchestrator.execute()  ──┐
        ├── partition em batches    │  loop até
        ├── batch concurrency-safe  │  acabarem
        │   → gather paralelo       │  tool_calls
        └── batch unsafe            │  ou aprovação
            → execução serial       │  bloquear
   → conversation.add_message(tool_results)
   → re-prompt o modelo  ───────────┘
```

**Risco real encontrado**: o `while True` em `ChatCompletionUseCase.execute()` (linha 236) e em `_stream_completion_turn()` (linha 489) **não checa `max_tool_iterations`**. O campo existe no DTO, é passado como metadata para o pending approval, mas nunca é enforced. Um modelo com bug ou um loop adversarial pode rodar indefinidamente. Bug latente concreto:

```python
# chat_completion.py:235
iteration = 0
while True:                              # nada limita iteration
    ...
    if not tool_calls or not tool_context:
        break
    await self._execute_tools_into_conversation(...)
    iteration += 1                        # incrementa mas nunca compara
```

### DI e composição

`interfaces/config/di_container.py` (597 linhas) faz wire dos singletons (LLM backends, tool registry, memory service, browser worker). Padrão razoável para um app monolítico — mas mistura responsabilidades de criação com cache de instâncias e leitura de env. Quando virar multi-tenant, vai ser difícil fatiar.

### Estado global mutável (problema sério)

`application/state/services/state_manager.py` é um singleton de processo. `AppState` carrega `conversation_id`, `system_context`, `user_context`, `workspace_root`, `permission_mode`, `tool_permissions`, etc. Em desktop com um usuário isso é OK. **No momento que o backend rodar como serviço com requisições concorrentes, uma request sobrescreve o `conversation_id` da outra** — `BuildContextUseCase` chama `set_conversation_id`/`set_workspace_root` em todo `execute`. Em K8s com múltiplos workers ainda é "ruim mas funcional"; numa única instância FastAPI com `uvicorn --workers > 1` ainda passa porque cada worker tem seu próprio processo — mas dentro do mesmo worker servindo várias conversas, **corre risco real de cross-talk**.

### Persistência e migrations

- 30 tabelas no `models.py` (conversations, messages, browser_workspaces, team_runs, memory_*, qa_*, ...). Esquema rico, mas:
  - Nenhum modelo tem `user_id`, `tenant_id`, `account_id` ou `owner_id`. Multi-tenant é refator não trivial em ~30 tabelas.
  - Migration system: existe pasta `migrations/` com 6 arquivos `.sql` (raw), mas eles **não são aplicados**. O que roda é `Base.metadata.create_all` + uma lista hardcoded de `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` em `database.py`. Alembic está no `pyproject.toml` mas não é usado. Em multi-instance isso vai dar dor.

---

## 2. Pontos Fortes do Harness de Agentes

Esta é a parte que vale a pena preservar a todo custo.

### 2.1 Prompt builder dinâmico

`domain/prompts/` separa em sections com cache breakpoints — permite que o modelo cacheie o que é estável e revalide o que muda. As sections compostas:
- `core_system_prompt_sections()` — response style, identity, acting contract, final response contract
- `agent_state_sections()` — 12 estados ordenados (intake → context_discovery → planning → implementation → tool_execution → debug_recovery → runtime_validation → context_compaction → memory_recall → user_checkpoint → finalization → plan_mode). Cada um sobrepõe instruções específicas para a fase ativa
- `prompt_mode_sections()` — auto/writing/exploring/research (analisador resolve `auto` a partir do contexto)
- `skill_sections()` e `command_sections()` — instruções condicionais por skill/comando ativo
- `provider_boundary_section()` — instruções de data boundary diferentes para llama local, codex subscription, hosted providers

Esse design de sections com `cache_break` é exatamente como prompt engineering sério faz. É um diferencial real.

### 2.2 Tool registry + orchestrator

- `ToolRegistry` com aliases, schema cache (importante — schemas OpenAI são pesados), filtro por allowlist, busca por query
- `BuiltTool` com **predicates por chamada**: `is_concurrency_safe(args)`, `is_read_only(args)`, `is_destructive(args)`. Não é por-tool fixo, é por-call — permite que `bash` seja read-only quando é só `ls` e destructive quando é `rm`
- `ToolOrchestrator.execute()` particiona chamadas em batches: batch concurrency-safe roda em `asyncio.gather`, batch não-safe roda serial. Estratégia conservadora e correta
- Permission model unificado: `ALLOW | DENY | ASK | UPDATE_INPUT` + Plan Mode + action approval signatures (assinatura HMAC do `args_hash` para evitar tampering entre frontend e backend)

### 2.3 Team Mode (multi-agente)

`application/team_chat/orchestrator.py` (3086 linhas — god file, mas o design é sofisticado):

```
execution_contract (coordinator define objetivo+subproblemas+sucesso+riscos)
   ↓
independent_round (cada agente raciocina sozinho)
   ↓
blackboard_publish (claim graph com novelty/coherency scores)
   ↓
debate_round (agentes discutem o que está no blackboard)
   ↓
vote (consenso com threshold + fast-vote heurística)
   ↓
tool_audit (auditor revisa mutações propostas)
   ↓
coordinator_final (síntese)
```

O `_Blackboard` mantém claim graph + cobertura por subproblema + scores de coerência/novidade + detecção de conflitos. Isso é arquitetura de pesquisa em multi-agent, não código de hackathon.

### 2.4 Memória operacional (RAG)

`infrastructure/persistence/operational_memory_repository.py` (1938 linhas):
- Embeddings vector(4096) com índice HNSW (`m=16, ef_construction=64`) num subvector de 2000 dims (truncamento explícito pra caber no limit do pgvector)
- Recall híbrido: 45% semantic + 40% lexical (tsvector) + 15% recent
- Outbox pattern para eventos de memória (`memory_outbox` com `dedupe_key`)
- Tabelas separadas para events, chunks, embeddings, structured_items, decisions, recall_logs, files, jobs, sessions, consolidation_locks
- Recall log persistido (para análise e replay)

Design correto. A consolidação é assíncrona via background tasks (`asyncio.create_task`) — funciona em single-process, vai precisar de worker queue (Celery/RQ/Temporal) em produção.

### 2.5 Domain exceptions tipadas

`domain/exceptions.py` define 49 erros em 17 categorias, com `code`, `category`, `severity`, `http_status`, `retryable`, `safe_for_model`, `safe_for_telemetry`. Toda a stack (FastAPI, SSE, WebSocket, ferramentas, telemetria) serializa pelo mesmo envelope. É o tipo de coisa que parece overengineering até o primeiro incidente de "erro do tool vazou pra UI sem contexto".

### 2.6 Streaming consistente

Tudo que vai pra UI segue o padrão `AsyncIterator[StreamChunk]`. WebSocket de Team Mode + SSE de chat single-agent reusam o mesmo modelo. Permite parar/retomar (`resume_after_tool_result_stream`).

### 2.7 Shell tool com defaults conservadores

`infrastructure/tools/shell_tool.py:27-76`:
- Whitelist de comandos read-only
- Whitelist específica para subcomandos git
- Block de meta-tokens (`|`, `>`, `;`, etc) por default
- Padrões críticos hard-blocked (`rm -rf /`, `sudo`, `systemctl`, ...)
- Tudo passa por `asyncio.create_subprocess_exec` (não shell)

---

## 3. Qualidade de Código

### Métricas

- Python backend: ~63k linhas em `src/` + 18.7k em tests (54 arquivos) → ~30% test-to-code ratio. Razoável para alpha.
- TypeScript desktop: ~32k linhas, ~14 arquivos de teste
- Type system: `from __future__ import annotations` global, mypy strict no `pyproject.toml`, Pydantic v2
- Linting: ruff com regras estritas em `pyproject.toml`
- Logging: structlog em todo o backend, eventos estruturados (`logger.info("event_name", key=value)`)
- 1 único `TODO` no código (`chat_completion.py:1774`). Limpeza acima da média.
- Apenas 13 `# type: ignore` e 1 `cast(`. Tipagem é levada a sério.

### Pontos fracos

**1. God files**

| Arquivo | Linhas | Métodos/classes |
|---|---|---|
| `infrastructure/browser/lightpanda.py` | 5735 | 1 classe principal com 161 métodos |
| `application/team_chat/orchestrator.py` | 3086 | 105 funções/métodos |
| `infrastructure/tools/browser_tools.py` | 2786 | 30+ factories |
| `application/use_cases/chat_completion.py` | 2633 | 1 classe com 87 métodos |
| `infrastructure/persistence/operational_memory_repository.py` | 1938 | 1 repo gigante |
| `desktop-electron/components/chat/session-panel.tsx` | 3960 | ? |
| `desktop-electron/stores/chat-store.ts` | 3305 | ? |
| `desktop-electron/components/chat/input-dock.tsx` | 1963 | ? |

Não é só estética — é o sinal de que abstrações estão escondidas dentro de classes monstro. `ChatCompletionUseCase` tem 87 métodos. Pelo menos 4 responsabilidades misturadas: orquestração do loop, persistência da conversa, gerenciamento de approval/plan mode, montagem de prompt, processamento de stream, captura de memória operacional.

**2. `dict[str, Any]` por toda parte**

985 ocorrências de `dict[str, Any]` no backend. Domínios sensíveis:
- Blackboard payloads (`_BlackboardEntry`, `claim_node`, `tool_audit`) — passa dict em vez de TypedDict/dataclass
- Tool arguments → no payload de tool_call, no `ToolUseContext`, no estado de approval
- Metadata genérica em todo lado (`Message.metadata`, `Conversation.metadata`, `result.data`, etc)

Isso aniquila o benefício do mypy strict. Em refator, trocar por `TypedDict` ou Pydantic models recupera a segurança.

**3. Sem enforcement de iteration cap**

Já mencionado. Concreto e crítico.

**4. Estado global singleton**

Já mencionado. Concreto e bloqueante para multi-tenant.

**5. Migrations ad-hoc**

Já mencionado. `ALTER TABLE ... IF NOT EXISTS` hardcoded em `database.py`. Risco em multi-instance e em rollback.

**6. Testes**

- 54 arquivos de teste, mas zero `conftest.py` e zero `setUp`/fixtures compartilhadas. Cada teste monta seu próprio cenário (verboso e propenso a divergência)
- Apenas 21 dos 54 usam mock/patch — bom no sentido de testar comportamento real, mas alguns testes de integração (`integration/`, `live/`) requerem chaves de API reais (NVIDIA, Vertex, Kimi)
- Não há coverage report no repo. Difícil saber cobertura efetiva dos orquestradores grandes
- Sem testes E2E end-to-end do harness (request HTTP → tool loop → resposta final)

**7. README desincronizado com o repo público**

O `.gitignore` exclui `docs/adr/`, `AGENTS.md` e `docker-compose.yml`. O README referencia:
- "21 ADRs em `docs/adr/`" — pasta não existe no repo
- "Quick Start: `docker compose up -d postgres`" — `docker-compose.yml` não existe no repo
- "GitHub Actions CI/CD" — não há `.github/workflows/` no repo
- "pre-commit hooks" — sem `.pre-commit-config.yaml`

A versão pública parece muito mais cuidada do que o que realmente está commitado. Quem clonar não vai conseguir setup limpo.

**8. Observabilidade quase ausente**

- structlog: sim, com eventos nomeados consistentes
- Métricas Prometheus: não
- Distributed tracing: 1 import isolado de OpenTelemetry em `qa/runtime_tracer.py` (usado pra instrumentar o código sendo testado, **não** o backend em si)
- Sentry / error monitoring: não
- Cost tracking: campos existem em `AppState` (`total_cost_usd`, `total_api_duration_ms`) mas nada é agregado por usuário/conversa de forma duradoura

**9. Sem background worker dedicado**

Memory consolidation, embeddings, browser cooperation, captura operacional de mensagens — tudo via `asyncio.create_task` no mesmo processo. Se o backend reinicia, jobs em voo somem. Sem retry persistente. Em produção quase certamente precisa Celery/RQ/Temporal/Cloud Tasks.

### Verdict de qualidade

A intenção de qualidade é alta (mypy strict, ruff, structlog, exceções tipadas, Clean Architecture, testes). A execução tem cabeças de hidra: god files e `dict[str, Any]` espalhado erodem o que deveria ser uma base sólida. **Não é código ruim — é código que cresceu rápido sem refator periódico.** É exatamente o tipo de débito técnico que vira intratável depois de mais 3 meses se não for atacado agora.

---

## 4. Viabilidade de Escalar como App

### O que falta para virar produto multi-tenant

Status atual: **single-user, single-machine, single-process**.

| Capability | Estado atual | Esforço para produto |
|---|---|---|
| Auth de usuário | Token compartilhado local (`~/.personagent/local_auth_token`) | Reescrever: JWT/OAuth, tabela `users`, RBAC, sessions, refresh tokens |
| Multi-tenant data isolation | Zero `user_id` em 30 tabelas | Adicionar `user_id`/`tenant_id` em todas, RLS no Postgres ou schema-per-tenant |
| Per-request state | Singleton `StateManager` global | Passar `RequestContext` pelo call chain (não dá pra fugir disso) |
| Rate limiting | Inexistente | Middleware (slowapi/limits) + quota por plano |
| Cost tracking | Em memória, perdido em restart | Agregar em DB por user/conversa/dia |
| API keys do usuário (BYOK) | `config.yaml` global | Tabela criptografada (Fernet/age) + secret manager |
| Migrations | `create_all` + ALTERs hardcoded | Alembic com versionamento e rollback |
| Background jobs | `asyncio.create_task` no processo | Worker queue (Celery/RQ/Temporal/Cloud Tasks) |
| Browser worker | Singleton LightPanda no processo | Pool de workers com sticky sessions via worker-id |
| Observability | structlog | + Prometheus, OpenTelemetry, Sentry |
| CI/CD | Não está no repo público | `.github/workflows/`, lint+test+build+deploy |
| Billing | Inexistente | Stripe / similar |
| Onboarding | Manual via Electron local | Signup, email verification, plan selection |
| Skill/tool marketplace | Local-only, sem manifesto público | Manifest público (estilo MCP), sandbox de execução |

### Custos operacionais previstos

- LLM: dependendo do plano, o usuário trazendo a própria key (BYOK) é mais barato pra você. Hosted-plan precisa de markup sobre OpenAI/Anthropic/Google
- Postgres + pgvector: o índice HNSW em vector(4096) com m=16 ef=64 é pesado. Estimar ~3-5 GB de RAM por 10M embeddings. Provisionar Aurora/Cloud SQL ou auto-host
- Browser worker: cada usuário ativo precisa de ~200-500 MB de processo LightPanda/Chromium. Containerizar e usar autoscaling com sticky sessions
- Storage: artifacts de tools (screenshots, downloads, content cache) — separar S3/GCS, evitar disk local
- Egress: streaming SSE/WS pesa, mas razoável

### Riscos não óbvios

1. **Conversation context blowup**: o RAG operacional + system prompt dinâmico + mensagens persistidas crescem muito. Sem context window management agressivo, latência e custo explodem por usuário ativo
2. **Tool loop runaway**: já citado, sem cap, custo descontrolado por sessão
3. **Browser worker hostage**: LightPanda travado mantém o worker preso. Precisa de circuit breaker e replace agressivo
4. **Memory consolidation lag**: a consolidação de memória em background pode ficar atrás da ingestão sob carga. Outbox pattern já existe, mas não há dimensionamento provado
5. **Compliance**: BYOK + logs estruturados = vai precisar política clara de retention, GDPR, e provavelmente um modo "ephemeral session"
6. **Modelo open vs hosted**: se o produto é "rode com seu llama.cpp local", você não está competindo com Claude Code / Cursor. Se é hosted, você está. Defina o posicionamento antes do refator

### Resposta direta

**Sim, é possível** virar produto escalável. **Não é trivial**. O harness justifica o investimento. A base de persistência e auth precisa ser reescrita conceitualmente (não a stack, o modelo) para multi-tenancy. Estimativa realista do que separa hoje de "MVP hosted vendável": **3-4 meses de refator focado + 1 mês de infra/billing**, sem mexer no harness — esse pode ficar quase intacto.

---

## 5. Migração para Go — Custo vs Benefício

Você levantou Go. Vamos olhar com frieza.

### O que Go te daria

- Binário estático, deploy mais simples
- Goroutines + channels para tool fan-out: modelo de concorrência mais previsível que asyncio
- Menos uso de memória e CPU por request (~30-50% típico em workloads I/O bound)
- Tipos fortes que matam `dict[str, Any]` por construção
- Ecossistema cloud-native maduro (K8s operators, observability)
- Tempo de startup curto (importante se for serverless)

### O que Go te tira

- **Ecossistema LLM/agent é IMATURO em Go**:
  - `langchaingo`: existe, mas atrás 1-2 anos em features de LangChain Python; reasoning, structured output, callbacks são limitados
  - `sashabaranov/go-openai`: parser OpenAI funciona, mas adapters customizados (NVIDIA NIM, Vertex AI streaming, Kimi Coding, Codex Subscription) vão precisar ser reimplementados from scratch
  - Embeddings: existe (`milvus-io/milvus-sdk-go`, `pgvector/pgvector-go`), mas o pipeline de chunking/extraction precisa ser portado
  - Prompt building: a manipulação textual rica de `domain/prompts/` é exatamente onde Python brilha. Em Go vira string templating verboso
  - Memory consolidation (regex, NLP-leve, dedupe heurístico, ranking híbrido): isso é trabalho de "linguagem ergonômica para texto", não Go
- **Browser worker**: LightPanda integration via CDP raw existe; em Go usaria `chromedp` ou `rod`. Reescrever 5735 linhas de browser worker.
- **Pydantic-like validation**: validação de DTOs em Go é mais boilerplate (`go-playground/validator`)
- **Async streaming**: Go faz bem, mas o modelo `AsyncIterator[StreamChunk]` que atravessa todo o backend vira refator estrutural completo
- **Rewrites históricamente matam produtos**: Joel Spolsky, "Things You Should Never Do, Part I". Você gasta 4-6 meses replicando o que já tem, perde velocidade de feature, e no fim a lógica é a mesma com sintaxe diferente

### O que NÃO precisa de Go

A heurística honesta é: o gargalo do PersonAgent não é CPU/RAM do processo Python — é tempo gasto no LLM remoto e em I/O com o Postgres/browser. Trocar Python por Go nesse cenário **não move o ponteiro**.

### Onde Go FAZ sentido (extração cirúrgica)

Se um gargalo concreto aparecer, você pode extrair como microserviço:
- **Embedding pipeline**: throughput de embedding em batch é onde Go bate Python feio. Worker dedicado em Go que consome `memory_outbox` e produz vetores
- **Browser worker pool**: orquestração de pool de Chromium/LightPanda em Go (`chromedp`) com health checks. O agente backend chama via gRPC
- **Tool sandbox runner**: shell/file tools que precisam isolamento forte (Firecracker, gVisor) podem ser um agent Go pequeno

Mas isso é otimização tardia. Hoje não tem dado que justifique.

### Veredito Go vs Python

**Não migre.** Refator o Python. Se em 6 meses um componente específico provar gargalo, extraia _aquele_ componente em Go. O harness em si — prompt builder, team orchestrator, memory consolidation, tool registry — vai ser sempre melhor em Python.

---

## 6. Recomendações concretas

Ordenadas por ROI. Prioridade do topo é o que destrava produto sem refator épico.

### Fase 0 — Anti-fogo (1-2 semanas)

Bloqueadores de qualquer escala, não dá pra adiar.

1. **Enforcement de `max_tool_iterations`** — adicionar check nos dois `while True` em `chat_completion.py`. Default razoável (ex: 30). Erro tipado quando excede.
2. **Kill do `StateManager` singleton** — criar `RequestContext` (dataclass) e passar pelo call chain de `BuildContextUseCase` e `ChatCompletionUseCase`. Sem isso, multi-tenant é impossível.
3. **Adicionar Alembic** — gerar revisão inicial a partir do schema atual, mover os `ALTER` hardcoded para migrations. CI bloqueia se schema divergir.
4. **Push do que está gitignorado pro repo público** — ou tirar do README, ou commitar `docker-compose.yml`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`. Reduz fricção de novos contribuidores e te força a manter eles funcionais.

### Fase 1 — Refator de god files (1 mês)

Sem isso, a velocidade de feature vai cair com o tempo. Atacar:

5. **Quebrar `chat_completion.py`** em submodules:
   - `chat/loop.py` — só o loop iterativo
   - `chat/prompt_preparation.py` — montagem de prompt package
   - `chat/streaming.py` — `_stream_assistant_pass` + normalização de chunks
   - `chat/approval.py` — plan mode + tool approval + user question
   - `chat/persistence.py` — captura operacional, persistência
   - `ChatCompletionUseCase` fica como façade fina (~300 linhas)
6. **Quebrar `team_chat/orchestrator.py`**:
   - `team_chat/phases/` — execution_contract, independent, blackboard, debate, vote, audit, final
   - `team_chat/blackboard.py` — `_Blackboard` extraído (já candidato natural)
   - `team_chat/voting.py` — voto + fast-vote
7. **Quebrar `infrastructure/browser/lightpanda.py`**:
   - `browser/cdp_client.py` — raw CDP
   - `browser/page.py`, `browser/tab.py`, `browser/snapshot.py`
   - `browser/actions/` — click, type, scroll, etc
8. **`dict[str, Any]` → TypedDict/dataclasses** nos lugares quentes: blackboard payloads, tool args, prompt context metadata. Reativa o valor do mypy strict.

### Fase 2 — Produto (2 meses)

9. **Multi-tenant primitives**:
   - Tabela `users` + `tenants` + `api_keys`
   - `user_id` / `tenant_id` em conversations, messages, memory_*, browser_workspaces, etc
   - RLS no Postgres (preferível) ou WHERE clause obrigatório via repositório
   - JWT auth com refresh tokens
   - CORS/origin restrito por tenant
10. **Background worker dedicado**:
    - Memory consolidation → Celery/RQ/Temporal worker
    - Outbox pattern já existe — só plugar consumer dedicado
    - Tools longos (browser cooperation, deep research) também
11. **Per-tenant rate limiting + cost tracking**:
    - Middleware com Redis (slowapi/limits)
    - Aggregator de cost em background
    - Hard cap por plano
12. **BYOK secrets**:
    - Tabela `user_secrets` criptografada (Fernet ou KMS)
    - Provider config resolvido por request a partir do user, não do `config.yaml` global
13. **Observability stack**:
    - Prometheus metrics (request count, latency, tool failures, tokens/cost)
    - OpenTelemetry tracing fim-a-fim
    - Sentry para erros não-tratados
    - Dashboard básico (Grafana)
14. **CI/CD real**:
    - Pipeline rodando lint+test+typecheck em PR
    - Container build + push
    - Deploy para staging automático
15. **Browser worker pool**:
    - LightPanda em container separado
    - Routing por sticky session
    - Health check + autoreplace

### Fase 3 — Escala e plataforma (3-6 meses)

16. **Skills/tools como marketplace**: manifest público (inspirado em MCP), sandbox de execução, versionamento, install/uninstall por usuário
17. **Hosted plan + BYOK plan**: dois SKUs, billing via Stripe
18. **Web client além do Electron**: extrair os componentes de chat reutilizáveis, oferecer experiência web (SaaS)
19. **Extração cirúrgica em Go SE necessário** (não antes): embedding pipeline ou browser worker pool, com gRPC

### Não-recomendações

- Não migre tudo pra Go
- Não tente fazer multi-tenant sem antes matar o singleton e ad-hoc migrations
- Não tente lançar como produto antes de Fase 1 (vai ter incidente de god file)
- Não adicione mais features no harness sem antes adicionar testes de cobertura do `ChatCompletionUseCase` e `TeamChatOrchestrator` end-to-end

---

## 7. TL;DR Final

**Arquitetura**: intenção Clean honesta, execução com leakage menor em `application → infrastructure` e um `subprocess.run` solto em domain. 7/10.

**Harness**: ponto forte real. Prompt builder dinâmico, tool orchestrator com paralelismo seguro, team mode com blackboard, memória operacional com RAG híbrido. 9/10 em design, 7/10 em organização (god files diluem o valor).

**Qualidade**: tipagem boa de intenção mas dict[str, Any] espalhado, testes existem mas god files não têm cobertura clara, README desincronizado com o repo público, sem CI/CD commitado. 6/10.

**Pronto para escalar?**: Não. Falta multi-tenant, auth real, migrations, worker queue, observabilidade, rate limit. Mas o gap é refator dirigido, não rewrite. 3-4 meses de trabalho focado.

**Migrar para Go?**: Não. Custo alto, benefício baixo, ecossistema LLM em Go imaturo. Refator Python primeiro; extrair Go cirurgicamente se gargalo concreto aparecer.

**Próximo passo recomendado**: Fase 0 desta semana. Sem isso, qualquer outro investimento (feature, marketing, refator) carrega risco operacional latente.
