# Roadmap de Correções — PersonAgent

**Data:** 2026-05-14  
**Base da Análise:** Documentos `01` a `06` da pasta `analysis/`  
**Código de Referência:** `main` @ `e927786`

---

## 1. Visão Geral

Este roadmap transforma todas as lacunas identificadas na análise em **branches de trabalho independentes e trabalháveis**. Cada branch representa uma carga de trabalho significativa (1-3 semanas) e agrupa correções logicamente relacionadas.

**Princípios do Roadmap:**
- **Uma branch por domínio** — evita conflitos e permite review focado
- **Carga significativa** — nenhuma branch é menor que 1 semana de trabalho
- **Independência quando possível** — branches sem dependências podem ser executadas em paralelo
- **Funcionalidades quebradas primeiro** — bugs de UX e segurança crítica têm prioridade
- **Deploy readiness por último** — infraestrutura só faz sentido após o produto estar estável

---

## 2. Estrutura do Roadmap

```
Fase 1: SEGURANÇA CRÍTICA (Semanas 1-3)
├── Branch 1: security/prompt-injection-defenses
└── Branch 2: security/rate-limiting-and-auth

Fase 2: INFRAESTRUTURA BASE (Semanas 4-6)
├── Branch 3: infra/containerization-and-health
└── Branch 4: infra/tls-sandbox-rbac

Fase 3: REFATORAÇÃO DO BACKEND (Semanas 7-9)
├── Branch 5: backend/refactor-chat-completion
└── Branch 6: backend/separate-inference-runtime

Fase 4: FRONTEND E UX (Semanas 10-11)
└── Branch 7: frontend/ux-polish-and-onboarding

Fase 5: DEVOPS E DEPLOY (Semanas 12-14)
├── Branch 8: devops/ci-cd-observability
└── Branch 9: devops/cloud-infra-and-secrets
```

> **Nota sobre paralelismo:** As Fases 1, 4 e 5 podem ter trabalho paralelo se a equipe tiver múltiplos desenvolvedores. As Fases 2 e 3 possuem dependências internas (ver seção 6).

---

## 3. Branches em Detalhe

---

### Branch 1: `security/prompt-injection-defenses`
**Fase:** 1 | **Semanas:** 1-2 | **Dependências:** Nenhuma

**Problemas que resolve:**
- 8 superfícies de ataque de prompt injection documentadas e não mitigadas
- Tool results injetados diretamente no contexto do LLM sem sanitização
- Memórias RAG reinjetadas sem validação
- `max_tool_iterations` default ilimitado

**Escopo:**
Implementar defesas estruturais contra prompt injection em todas as superfícies de ataque identificadas, além de limitar loops de ferramentas.

**Tarefas Detalhadas:**

1. **Delimitadores estruturais XML** (`domain/prompts/`)
   - Criar funções de wrapping: `wrap_user_input(content)`, `wrap_tool_result(content)`, `wrap_memory(content)`
   - Modificar `PromptBuilder` para usar `<user_input>`, `<tool_result>`, `<relevant_memories>`, `<untrusted>` tags
   - Atualizar `chat_completion.py:206-211` para envolver `request.message` em `<user_input>`
   - Atualizar `_tool_message_from_result` (`chat_completion.py:855-867`) para envolver `result.content` em `<tool_result>`
   - Atualizar `prompt_builder.py:527-543` para envolver memórias em `<relevant_memories>`

2. **Sanitizador de tool results** (`domain/prompts/` ou `infrastructure/tools/`)
   - Criar classe `PromptInjectionSanitizer` com heurísticas de detecção:
     - Padrões de override de instruções ("ignore previous instructions", "system override", etc.)
     - Delimitadores suspeitos (`<!-- SYSTEM OVERRIDE -->`, `[SYSTEM]`, etc.)
     - Tags HTML/meta suspeitas em conteúdo de ferramentas
   - Integrar sanitizador no pipeline de `_tool_message_from_result`
   - Adicionar testes unitários com casos de ataque conhecidos

3. **Marcação de confiança**
   - Adicionar campo `trusted: bool` ao modelo `Message` (`domain/models/conversation.py`)
   - Mensagens de usuário e tool results são `trusted=False`
   - System prompt e instruções internas são `trusted=True`
   - Modificar `PromptBuilder` para incluir aviso de confiança no system prompt

4. **Validação de memória antes de persistir**
   - Modificar `session_memory.py` e `memory_extractor.py` para escanear novas memórias com o mesmo `PromptInjectionSanitizer`
   - Se memória contiver instruções maliciosas, rejeitar e logar alerta

5. **Limitar `max_tool_iterations`**
   - Modificar `runtime_config.py:10`: `DEFAULT_MAX_TOOL_ITERATIONS: int = 10`
   - Modificar `chat.py` route: `Field(default=10, ge=1, le=50)`
   - Adicionar teste para verificar que loops >10 são truncados

**Critérios de Aceitação:**
- [ ] Todas as mensagens de usuário envolvidas em `<user_input>` no prompt
- [ ] Todos os tool results envolvidos em `<tool_result>` no prompt
- [ ] `PromptInjectionSanitizer` detecta pelo menos 10 padrões de ataque conhecidos
- [ ] `max_tool_iterations` default é 10 (não `None`)
- [ ] Testes unitários passam para todos os novos componentes
- [ ] Documento `docs/security/prompt-injection-analysis.md` atualizado com mitigações implementadas

**Estimativa de Esforço:** 1.5-2 semanas (1 desenvolvedor sênior backend)

---

### Branch 2: `security/rate-limiting-and-auth`
**Fase:** 1 | **Semanas:** 2-3 | **Dependências:** Branch 1 (compartilha testes de segurança)

**Problemas que resolve:**
- API completamente desprotegida contra flooding e brute-force
- Sistema single-user sem autenticação real
- Sem RBAC, sessões, ou expiração

**Escopo:**
Proteger a API com rate limiting e implementar autenticação JWT com RBAC básico, preparando o sistema para multiusuário.

**Tarefas Detalhadas:**

1. **Rate limiting na API** (`interfaces/api/`)
   - Adicionar `slowapi` ou `fastapi-limiter` ao `pyproject.toml`
   - Criar middleware de rate limiting em `main.py`:
     - `/chat/completions`: 10 req/min por usuário, 100 req/min por IP
     - `/chat/completions/stream`: 5 req/min por usuário
     - `/workspace/*` mutating: 30 req/min por usuário
     - `/health`: ilimitado (para load balancers)
   - Configurar Redis como backend de rate limit (ou memory store para local-only)
   - Adicionar headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

2. **Proteção contra brute-force**
   - Implementar contador de tentativas falhas por IP no middleware de auth
   - Após 5 tentativas falhas em 5 minutos, bloquear IP por 15 minutos
   - Logar tentativas de brute-force com `structlog` (nível `warning`)

3. **Autenticação JWT** (`interfaces/api/security.py`)
   - Adicionar dependência `python-jose` ou `pyjwt` ao `pyproject.toml`
   - Criar modelo `User` no banco (PostgreSQL): `id`, `email`, `hashed_password`, `role`, `created_at`, `updated_at`
   - Criar endpoints:
     - `POST /auth/register` — registro de novo usuário
     - `POST /auth/login` — login retornando JWT access + refresh tokens
     - `POST /auth/refresh` — renovação de access token
     - `POST /auth/logout` — invalidação de refresh token
   - Modificar middleware `install_local_auth` para suportar tanto token local (legacy) quanto JWT
   - JWT deve conter claims: `sub` (user_id), `role`, `iat`, `exp`

4. **RBAC básico**
   - Definir roles: `admin`, `user`, `readonly`
   - Criar decorator `@require_role("admin")` para rotas administrativas
   - `user` pode executar chat, tools, workspace
   - `readonly` pode apenas ler conversas e arquivos
   - `admin` pode gerenciar usuários e configurações
   - Adicionar `user_id` como foreign key em `conversations`, `messages`, `memory_events`

5. **Migração de dados**
   - Criar usuário "default" para dados existentes (backward compatibility)
   - Script de migração: associar todas as conversas existentes ao usuário default

**Critérios de Aceitação:**
- [ ] Rate limiting funciona para todos os endpoints (testar com script de flood)
- [ ] Brute-force protection bloqueia IP após 5 tentativas falhas
- [ ] JWT auth funciona para login, refresh, e acesso a rotas protegidas
- [ ] RBAC impede que usuário `readonly` execute tools mutantes
- [ ] Token local legacy ainda funciona para desktop existente (backward compat)
- [ ] Todas as tabelas possuem `user_id` ou tenant isolation
- [ ] Testes de API security passam (`tests/test_api_security.py`)

**Estimativa de Esforço:** 2-2.5 semanas (1 desenvolvedor sênior backend)

---

### Branch 3: `infra/containerization-and-health`
**Fase:** 2 | **Semanas:** 4-5 | **Dependências:** Nenhuma (pode rodar em paralelo com Fase 1 se equipe permitir)

**Problemas que resolve:**
- Backend não containerizado
- Sem `.dockerignore`, `docker-compose.prod.yml`
- Health check superficial (`/health` retorna apenas `"healthy"`)
- Migrations SQL manuais (sem Alembic)

**Escopo:**
Containerizar o backend, configurar Alembic para migrations versionadas, e implementar health checks profundos.

**Tarefas Detalhadas:**

1. **Dockerfile multi-stage** (raiz e `@backend/`)
   - Stage 1 (`builder`): `python:3.11-slim`, instala build deps, compila dependências nativas
   - Stage 2 (`runtime`): copia apenas `.venv`/site-packages, sem build deps
   - Usar `uv` para instalação rápida (`COPY pyproject.toml uv.lock`, `uv sync`)
   - Expor porta 8000, entrypoint `uvicorn personagent.interfaces.api.main:app --host 0.0.0.0 --port 8000`
   - Usar usuário não-root (`USER app`)
   - `.dockerignore` excluindo: `.venv/`, `tests/`, `node_modules/`, `.git/`, `.env`

2. **Docker Compose de produção** (`docker-compose.prod.yml`)
   - Serviço `backend`: imagem buildada, `restart: unless-stopped`, healthcheck
   - Serviço `postgres`: `pgvector/pgvector:pg16`, volumes persistentes, healthcheck
   - Serviço `lightpanda`: `lightpanda/browser:nightly`, limites de memória/CPU
   - Serviço `redis`: `redis:7-alpine` (descomentar e habilitar)
   - Rede `personagent-network` com `driver: bridge`
   - Secrets via Docker secrets ou `.env` com `env_file`

3. **Alembic configurado**
   - Inicializar Alembic: `alembic init @backend/alembic`
   - Configurar `alembic.ini` com URL do banco via env var
   - Criar migration inicial baseada no schema atual (`Base.metadata`)
   - Converter migrations SQL manuais (001-007) para migrations Alembic
   - Adicionar comando CLI: `personagent db migrate` e `personagent db revision --autogenerate`
   - Remover `Base.metadata.create_all()` do lifespan (substituir por `alembic upgrade head`)

4. **Health checks profundos**
   - `GET /health` — mantém comportamento atual (lightweight, para load balancers)
   - `GET /health/deep` — novo endpoint:
     - Verifica conexão PostgreSQL (`SELECT 1`)
     - Verifica LLM backend (ping no `llama_server_url` ou status do adapter default)
     - Verifica browser worker (ping no LightPanda/CDP)
     - Verifica embedding server (ping no `embedding_server_url`)
     - Verifica Redis (se habilitado)
     - Retorna JSON detalhado com status de cada dependência:
       ```json
       {"status": "healthy", "checks": {"database": "ok", "llm": "ok", "browser": "ok", "embedding": "ok"}}
       ```
   - Se qualquer check falhar, retornar `503 Service Unavailable` com detalhes

5. **Script de setup one-click**
   - `scripts/setup.sh` (Linux/macOS) e `scripts/setup.ps1` (Windows)
   - Verifica Docker instalado, builda imagens, sobe compose, roda migrations
   - Wizard interativo: pede POSTGRES_PASSWORD, SECRET_KEY, provider padrão

**Critérios de Aceitação:**
- [ ] `docker build -t personagent-backend .` funciona sem erros
- [ ] `docker compose -f docker-compose.prod.yml up` sobe todos os serviços
- [ ] Alembic migrations aplicam schema corretamente em banco limpo
- [ ] `/health/deep` retorna status de todas as dependências
- [ ] `/health/deep` retorna 503 se PostgreSQL está down
- [ ] Setup script funciona em máquina limpa (testar em VM/fresh install)

**Estimativa de Esforço:** 1.5-2 semanas (1 desenvolvedor sênior backend/DevOps)

---

### Branch 4: `infra/tls-sandbox-rbac`
**Fase:** 2 | **Semanas:** 5-6 | **Dependências:** Branch 3 (containerização necessária para sandbox)

**Problemas que resolve:**
- Sem TLS/HTTPS
- Sem sandbox de execução (shell roda no host)
- RBAC de recursos (CPU, memória, rede) para ferramentas

**Escopo:**
Adicionar TLS auto-configurado, containerizar execução de ferramentas (shell, browser scripts), e implementar isolamento de recursos.

**Tarefas Detalhadas:**

1. **TLS auto-configurado**
   - Adicionar dependência `certbot` ou usar `mkcert` para desenvolvimento local
   - Criar script `scripts/generate-certs.sh` que gera certificados self-signed
   - Modificar `main.py` para suportar `ssl_keyfile` e `ssl_certfile` no Uvicorn
   - Adicionar configurações em `settings.py`:
     - `tls_enabled: bool = False`
     - `tls_cert_path: str = "~/.config/personagent/certs/cert.pem"`
     - `tls_key_path: str = "~/.config/personagent/certs/key.pem"`
   - Quando `tls_enabled=True`, redirecionar HTTP para HTTPS
   - Para produção: suporte a Let's Encrypt via `certbot` (Docker sidecar)

2. **Containerização de execução de tools**
   - Criar `Dockerfile.tool-sandbox` (imagem leve Alpine com bash, git, curl)
   - Modificar `shell_tool.py`:
     - Em vez de `asyncio.create_subprocess_exec` no host, executar via Docker:
       ```python
       docker_run = [
           "docker", "run", "--rm",
           "--network=none",  # sem acesso à internet por default
           "--cpus=1", "--memory=512m",
           "-v", f"{cwd}:{cwd}:ro",  # workspace read-only por default
           "-w", str(cwd),
           "personagent-tool-sandbox",
           "bash", "-c", command
       ]
       ```
     - Para comandos read-only: volume read-only (`:ro`)
     - Para comandos mutantes: volume read-write (`:rw`), mas apenas dentro do workspace
     - Timeout de 60s enforced pelo Docker (`--stop-timeout=60`)
   - Modificar `browser_tools.py`:
     - `BrowserScript` com `mode=evaluate` deve rodar em container sandbox separado
     - Limitar acesso de rede do container de scripts (bloquear acesso a `169.254.*`, `10.*`, `192.168.*`)

3. **Isolamento de rede**
   - Rede Docker dedicada `personagent-sandbox` para containers de ferramentas
   - Sem acesso à internet por padrão (`--network=none`)
   - Para ferramentas que precisam de internet (WebFetch, BrowserOpen), usar `--network=personagent-sandbox` com egress controlado via iptables
   - Bloquear acesso a hosts privados (`localhost`, `127.0.0.1`, `*.local`)

4. **Resource limits**
   - CPU: max 1 core por execução de tool
   - Memória: max 512MB por execução de tool
   - Disco: max 100MB de escrita temporária (`--storage-opt size=100M`)
   - Tempo: max 60s (shell), max 30s (browser script)

5. **Fallback para modo local**
   - Se Docker não está disponível (modo dev puro), fallback para execução local com warnings no log
   - Configuração `sandbox_mode: str = "docker" | "local_warn" | "local_deny"`

**Critérios de Aceitação:**
- [ ] Backend inicia com HTTPS quando `tls_enabled=True`
- [ ] Certificados auto-gerados funcionam para desktop local
- [ ] Shell tool executa em container Docker isolado
- [ ] Container de shell não consegue acessar `/etc/passwd` fora do workspace
- [ ] Container de shell não consegue fazer `curl` para a internet (com `--network=none`)
- [ ] Browser script executa em container isolado
- [ ] Resource limits (CPU, memória, tempo) são enforced
- [ ] Fallback para local funciona quando Docker não está disponível

**Estimativa de Esforço:** 2 semanas (1 desenvolvedor sênior backend/DevOps)

---

### Branch 5: `backend/refactor-chat-completion`
**Fase:** 3 | **Semanas:** 7-8 | **Dependências:** Branch 1 (prompt injection mitigations devem estar estáveis)

**Problemas que resolve:**
- `ChatCompletionUseCase` é um god class de 2.633 linhas
- Sem API versioning
- Lógica de streaming, tool loop, memory, plan mode, images tudo no mesmo arquivo

**Escopo:**
Decompor o use case monolítico em serviços especializados, implementar versionamento de API, e melhorar a testabilidade.

**Tarefas Detalhadas:**

1. **Extrair `ToolLoopOrchestrator`** (`application/services/`)
   - Responsabilidade: executar loop LLM → tool calls → results → LLM
   - Métodos: `async def run_loop(context, max_iterations)`, `async def execute_single_turn(context)`
   - Isolar lógica de: parsing de tool calls, execução paralela, streaming de progresso
   - ~400-500 linhas estimadas

2. **Extrair `PromptBuilderService`** (`application/services/`)
   - Responsabilidade: montar system prompt completo
   - Métodos: `build_system_prompt(context)`, `build_user_message(request)`, `inject_memories(memories)`, `inject_tools(tools)`
   - Usar as mitigações de prompt injection da Branch 1
   - ~300-400 linhas estimadas

3. **Extrair `StreamingEmitter`** (`application/services/`)
   - Responsabilidade: gerenciar SSE/WebSocket streaming
   - Métodos: `emit_chunk(chunk)`, `emit_tool_progress(progress)`, `emit_error(error)`, `close_stream()`
   - Isolar lógica de buffering, parse de reasoning, split content/reasoning
   - ~200-300 linhas estimadas

4. **Extrair `PlanModeOrchestrator`** (`application/services/`)
   - Responsabilidade: gerenciar modo de planejamento (aprovado/manual)
   - Métodos: `evaluate_plan(plan)`, `request_approval(plan)`, `resume_after_approval(approval_id)`
   - ~200 linhas estimadas

5. **Extrair `ImageGenerationService`** (`application/services/`)
   - Responsabilidade: gerenciar geração e armazenamento de imagens
   - ~150 linhas estimadas

6. **Refatorar `ChatCompletionUseCase`**
   - Reduzir para ~400-500 linhas (orquestração de alto nível apenas)
   - Delegar todo o trabalho para os serviços extraídos
   - Manter interface pública estável para não quebrar rotas

7. **API Versioning**
   - Criar `interfaces/api/v1/` — copiar rotas atuais para `/v1/`
   - Modificar `main.py`:
     ```python
     app.include_router(v1_artifacts.router, prefix="/v1")
     app.include_router(v1_chat.router, prefix="/v1")
     # ... etc
     ```
   - Manter rotas sem prefixo como alias para `/v1/` (backward compat por 2 versões)
   - Documentar contrato de versionamento em `docs/api/versioning.md`

8. **Testes de regressão**
   - Garantir que todos os testes existentes (`tests/test_*_api.py`) passam após refatoração
   - Adicionar testes unitários para cada novo serviço extraído
   - Cobertura mínima de 80% nos novos módulos

**Critérios de Aceitação:**
- [ ] `ChatCompletionUseCase` tem <600 linhas
- [ ] Cada novo serviço tem <600 linhas e responsabilidade única
- [ ] Todas as rotas existentes respondem em `/v1/` e em `/` (alias)
- [ ] Testes de regressão passam (zero breaking changes na API)
- [ ] Novos testes unitários cobrem edge cases de tool loop, streaming, e plan mode

**Estimativa de Esforço:** 2-2.5 semanas (1 desenvolvedor sênior backend)

---

### Branch 6: `backend/separate-inference-runtime`
**Fase:** 3 | **Semanas:** 9 | **Dependências:** Branch 3 (containerização) e Branch 5 (refatoração)

**Problemas que resolve:**
- Backend FastAPI gerencia `llama-server` e `embedding-server` como subprocessos (stateful)
- Impede horizontal scaling e deploy em Kubernetes

**Escopo:**
Separar o inference runtime (llama.cpp + embedding) em serviços independentes que o backend consome via HTTP, tornando o backend stateless.

**Tarefas Detalhadas:**

1. **Remover gerenciamento de subprocessos do lifespan**
   - Remover bloco `if settings.llama_auto_start:` de `main.py:54-60`
   - Remover `container._process_manager.stop()` de `main.py:94-95`
   - Remover `container.close_llm_backends()` (manter apenas para cleanup graceful)

2. **Criar serviço `inference` separado**
   - `inference/Dockerfile`: base CUDA + llama.cpp buildado
   - `inference/docker-compose.yml`: serviço `llama-server` + `embedding-server`
   - Entrypoint: `llama-server` com config via env vars
   - Healthcheck próprio: `GET /health` no llama-server

3. **Adapter de discovery para inference**
   - Modificar `LlamaCppAdapter` para descobrir `llama-server` via:
     - Env var `LLAMA_SERVER_URL` (já existe)
     - Ou service discovery (Docker DNS: `http://llama-server:8080`)
     - Ou fallback para local se URL não configurada
   - Mesmo padrão para `EmbeddingAdapter`

4. **Docker Compose atualizado**
   - `docker-compose.prod.yml` inclui serviço `inference` separado
   - Backend depende de `inference` (`depends_on` + `condition: service_healthy`)
   - GPU pass-through configurado para serviço `inference` (`deploy.resources.reservations.devices`)

5. **Documentação de deploy**
   - `docs/operations/inference-runtime.md`: como buildar, configurar, e escalar o inference service
   - `docs/operations/scaling.md`: como rodar múltiplas réplicas do backend com 1 inference service

**Critérios de Aceitação:**
- [ ] Backend inicia sem gerenciar subprocessos de LLM
- [ ] `docker compose up` sobe inference + backend como serviços separados
- [ ] Backend conecta ao inference via HTTP (não subprocesso)
- [ ] Múltiplas réplicas do backend podem compartilhar 1 inference service
- [ ] Health check do inference funciona

**Estimativa de Esforço:** 1 semana (1 desenvolvedor sênior backend/DevOps)

---

### Branch 7: `frontend/ux-polish-and-onboarding`
**Fase:** 4 | **Semanas:** 10-11 | **Dependências:** Pode rodar em paralelo com Fases 2-3

**Problemas que resolve:**
- Botão Stop sumindo temporariamente
- 2 elementos com `tabIndex={0}` ainda pendentes
- Chat store monolítica de 3.305 linhas
- Sem onboarding guiado
- Sem auto-update

**Escopo:**
Corrigir bugs de UX restantes, implementar onboarding, e preparar auto-update.

**Tarefas Detalhadas:**

1. **Corrigir botão Stop sumindo**
   - `chat-store.ts`: remover `isStreaming = false` de handlers que não devem resetar:
     - `conversation_saved` (linha 1469): manter `isStreaming` se ainda há chunks pendentes
     - `permission_required` (linha 1502): não resetar `isStreaming`, apenas pausar
     - `plan_approval_requested` (linha 1427): manter `isStreaming` enquanto aguarda aprovação
     - `finally` de `sendMessage` (linha 390): só resetar se `finish_reason` foi recebido
   - Adicionar re-hidratação de `isStreaming = true` no início de `handleChunk` quando novos chunks chegam após `finish_reason="stop"` (caso de multi-turn streaming)

2. **Corrigir tabIndex restantes**
   - `session-panel.tsx:1425` (close button de browser tabs): `tabIndex={-1}`
   - `session-panel.tsx:2300` (browser viewport): `tabIndex={-1}`
   - Adicionar teste a11y para garantir que nenhum elemento não-interativo tem `tabIndex >= 0`

3. **Onboarding guiado**
   - Criar componente `OnboardingWizard` (4 passos):
     - Passo 1: "Bem-vindo ao PersonAgent" — explicação do local-first
     - Passo 2: "Configure seu primeiro provider" — seletor de LLM (local/ hosted)
     - Passo 3: "Escolha seu workspace" — dialog de seleção de pasta
     - Passo 4: "Experimente" — demo interativa: "Crie um arquivo README.md"
   - Persistir estado do onboarding em `localStorage` (`personagent_onboarding_completed`)
   - `App.tsx`: renderizar `OnboardingWizard` se onboarding não completado
   - Adicionar botão "Restart Onboarding" nas configurações

4. **Auto-update Electron (preparação)**
   - Adicionar `electron-updater` ao `package.json`
   - Configurar `electron-builder` com `publish` target (GitHub Releases)
   - Em `electron/main.ts`: adicionar listener de `autoUpdater.checkForUpdatesAndNotify()`
   - Criar workflow `.github/workflows/release-desktop.yml`:
     - Trigger: tag `v*` push
     - Builda AppImage/DMG/NSIS
     - Publica no GitHub Releases
     - Atualiza feed URL automaticamente

5. **Decomposição da Chat Store (preparação)**
   - Criar stores especializadas (vazias inicialmente, com interface definida):
     - `message-store.ts` — estado de mensagens
     - `streaming-store.ts` — estado de streaming (isStreaming, buffers)
     - `approval-store.ts` — estado de aprovações (plan, tool)
   - Refatorar `chat-store.ts` para delegar para as novas stores (não mover tudo de uma vez)
   - Meta: reduzir `chat-store.ts` para <2.000 linhas nesta branch

**Critérios de Aceitação:**
- [ ] Botão Stop não some durante streaming multi-turn
- [ ] Nenhum elemento não-interativo tem `tabIndex >= 0`
- [ ] Onboarding wizard aparece na primeira execução
- [ ] Onboarding pode ser completado em <2 minutos
- [ ] `electron-updater` configurado (update manual testado)
- [ ] Workflow de release desktop funciona (testar com tag `v0.0.0-test`)
- [ ] `chat-store.ts` reduzido para <2.000 linhas

**Estimativa de Esforço:** 2 semanas (1 desenvolvedor sênior frontend)

---

### Branch 8: `devops/ci-cd-observability`
**Fase:** 5 | **Semanas:** 12-13 | **Dependências:** Branch 3 (containerização) e Branch 6 (inference separado)

**Problemas que resolve:**
- Sem CI/CD de build, release, deploy
- Sem observabilidade produtiva
- Sem scan de vulnerabilidades

**Escopo:**
Implementar pipelines de CI/CD completos, observabilidade (métricas, logs, traces), e segurança de dependências.

**Tarefas Detalhadas:**

1. **CI/CD Backend**
   - `.github/workflows/backend.yml`:
     - Trigger: push/PR em `main`
     - Jobs: lint (ruff), type check (mypy), test (pytest), build Docker image
     - Push image para GitHub Container Registry (`ghcr.io/personagent/backend`)
     - Tag: `latest` (main), `pr-{number}`, `sha-{short}`

2. **CI/CD Desktop**
   - `.github/workflows/desktop.yml`:
     - Trigger: push/PR em `main` (modificando `@desktop-electron/`)
     - Jobs: lint (tsc), test (vitest), build (electron-builder)
     - Upload artifacts para GitHub Actions

3. **Release automatizado**
   - `.github/workflows/release.yml`:
     - Trigger: tag `v*.*.*`
     - Jobs: build backend image + push, build desktop + create GitHub Release
     - Gerar changelog automático (conventional commits)
     - Bump version em `pyproject.toml` e `package.json`

4. **Observabilidade**
   - Adicionar `opentelemetry-distro`, `opentelemetry-exporter-otlp` ao `pyproject.toml`
   - Configurar OTLP exporter para traces (Jaeger/Tempo)
   - Adicionar Prometheus metrics:
     - `personagent_chat_requests_total` (counter, labels: provider, model)
     - `personagent_chat_duration_seconds` (histogram)
     - `personagent_tool_executions_total` (counter, labels: tool_name, status)
     - `personagent_llm_tokens_total` (counter, labels: provider, type=input/output)
   - Configurar `structlog` com `JSONRenderer` para produção
   - Docker Compose: adicionar serviços `prometheus`, `grafana`, `jaeger`
   - Dashboard Grafana básico: latência de chat, erros 5xx, uso de tokens

5. **Segurança de dependências**
   - Adicionar `bandit`, `pip-audit`, `semgrep` ao CI (`security.yml`)
   - Adicionar `npm audit` ao CI do desktop
   - Criar `.github/dependabot.yml` para updates automáticos de Python e npm

**Critérios de Aceitação:**
- [ ] Push em `main` dispara build de backend + desktop automaticamente
- [ ] Tag `v*` dispara release completo (backend image + desktop binaries)
- [ ] Prometheus expõe métricas em `/metrics`
- [ ] Grafana dashboard mostra latência e erros em tempo real
- [ ] Jaeger mostra traces distribuídos
- [ ] `bandit` e `pip-audit` passam no CI sem vulnerabilidades críticas
- [ ] Dependabot abre PRs de updates automaticamente

**Estimativa de Esforço:** 2 semanas (1 desenvolvedor sênior DevOps)

---

### Branch 9: `devops/cloud-infra-and-secrets`
**Fase:** 5 | **Semanas:** 13-14 | **Dependências:** Branch 8 (CI/CD) e Branch 4 (TLS + sandbox)

**Problemas que resolve:**
- Sem infraestrutura como código
- Sem secrets management
- Sem load balancer / CDN

**Escopo:**
Preparar infraestrutura cloud, secrets management, e configurações de produção.

**Tarefas Detalhadas:**

1. **Terraform / infra as code**
   - `infra/terraform/`:
     - `main.tf`: providers (AWS ou GCP)
     - `vpc.tf`: rede, subnets, security groups
     - `rds.tf`: PostgreSQL RDS (ou Cloud SQL) com pgvector
     - `ecr.tf`: container registry
     - `ecs.tf` (ou `gke.tf`): cluster para backend + inference
     - `alb.tf`: Application Load Balancer com HTTPS
     - `cloudfront.tf`: CDN para assets estáticos
     - `route53.tf`: DNS records
   - `infra/terraform/modules/personagent/`: módulo reutilizável

2. **Helm charts (opcional, se usar Kubernetes)**
   - `infra/helm/personagent/`:
     - `Chart.yaml`, `values.yaml`, `values.prod.yaml`
     - Templates: `deployment.yaml`, `service.yaml`, `ingress.yaml`, `hpa.yaml`
     - HPA: scale backend 2-10 réplicas baseado em CPU/latência

3. **Secrets management**
   - Adicionar suporte a AWS Secrets Manager / GCP Secret Manager:
     - `settings.py`: `secrets_provider: str = "env" | "aws_sm" | "gcp_sm"`
     - Script de bootstrap: `scripts/bootstrap-secrets.py` migra `.env` para cloud SM
   - Para local/self-hosted: HashiCorp Vault:
     - `docker-compose.vault.yml`: serviço Vault dev mode
     - `settings.py`: suporte a `VAULT_ADDR` e `VAULT_TOKEN`

4. **Documentação de deploy enterprise**
   - `docs/operations/deploy-aws.md`: passo a passo de deploy na AWS
   - `docs/operations/deploy-gcp.md`: passo a passo de deploy no GCP
   - `docs/operations/deploy-self-hosted.md`: deploy on-premise com Docker Compose
   - `docs/operations/scaling.md`: como escalar horizontalmente
   - `docs/operations/disaster-recovery.md`: backup, restore, RTO/RPO

5. **Air-gapped deployment**
   - `scripts/build-offline-bundle.sh`: empacota todas as imagens Docker em tarball
   - `scripts/load-offline-bundle.sh`: carrega imagens em ambiente sem internet
   - Documentação de deploy sem acesso à internet

**Critérios de Aceitação:**
- [ ] `terraform plan` executa sem erros
- [ ] `terraform apply` sobe infraestrutura completa em conta cloud
- [ ] Backend acessível via HTTPS pelo Load Balancer
- [ ] Secrets são carregados de Secret Manager (não `.env`)
- [ ] HPA escala backend automaticamente sob carga
- [ ] Documentação de deploy permite reproduzir ambiente em <1 hora

**Estimativa de Esforço:** 2 semanas (1 desenvolvedor sênior DevOps)

---

## 4. Dependências entre Branches

```
Branch 1 (prompt injection) ──┬──► Branch 2 (rate limiting + auth)
                              │    (compartilha testes de segurança)
                              │
Branch 3 (containerization) ──┼──► Branch 4 (TLS + sandbox)
                              │    (sandbox usa containers)
                              │
                              ├──► Branch 6 (separate inference)
                              │    (containerização necessária)
                              │
Branch 5 (refactor) ──────────┘    (independente, mas após Branch 1)

Branch 7 (frontend) ───────────► Pode rodar em paralelo com tudo

Branch 8 (CI/CD) ──────────────► Depende de Branch 3 e Branch 6
Branch 9 (cloud infra) ────────► Depende de Branch 8 e Branch 4
```

---

## 5. Linha do Tempo Consolidada

| Semana | Branch | Foco | Quem |
|--------|--------|------|------|
| 1 | `security/prompt-injection-defenses` | Defesas de prompt injection + limitação de tool iterations | Backend |
| 2 | `security/rate-limiting-and-auth` | Rate limiting + JWT + RBAC | Backend |
| 3 | `infra/containerization-and-health` | Dockerfile + Alembic + health checks | Backend/DevOps |
| 4 | `infra/tls-sandbox-rbac` | TLS + sandbox Docker + resource limits | Backend/DevOps |
| 5 | `backend/refactor-chat-completion` | Decompor use case + API versioning | Backend |
| 6 | `backend/separate-inference-runtime` | Separar inference do backend | Backend/DevOps |
| 7 | `frontend/ux-polish-and-onboarding` | Correções UX + onboarding + auto-update prep | Frontend |
| 8 | `devops/ci-cd-observability` | Pipelines CI/CD + Prometheus/Grafana/Jaeger | DevOps |
| 9 | `devops/cloud-infra-and-secrets` | Terraform + secrets + LB + CDN + docs | DevOps |

> **Total: 9 semanas** com 2-3 desenvolvedores trabalhando em paralelo (1 backend, 1 frontend, 1 DevOps). Se a equipe for menor (1 pessoa), expectativa é de 14-16 semanas sequenciais.

---

## 6. Definição de "Pronto para Deploy"

O PersonAgent estará pronto para deploy comercial quando:

1. ✅ Prompt injection mitigado (Branch 1)
2. ✅ API protegida contra abuse (Branch 2)
3. ✅ Backend containerizado (Branch 3)
4. ✅ Execução sandboxed (Branch 4)
5. ✅ Backend refatorado e testável (Branch 5)
6. ✅ Inference separado e escalável (Branch 6)
7. ✅ UX polida e onboarding pronto (Branch 7)
8. ✅ CI/CD automatizado (Branch 8)
9. ✅ Infraestrutura cloud documentada (Branch 9)

**Checklist final de deploy:**
- [ ] `docker compose -f docker-compose.prod.yml up` sobe sistema completo
- [ ] `/health/deep` retorna todos os checks OK
- [ ] Penetration test interno passa (prompt injection, shell bypass, auth bypass)
- [ ] Load test: 50 usuários simultâneos, <2s latência média
- [ ] Desktop instala e atualiza automaticamente
- [ ] Documentação permite deploy por terceiros em <2 horas

---

## 7. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Refatoração quebra API existente | Alta | Alto | Testes de regressão obrigatórios; manter rotas sem prefixo como alias |
| Sandbox Docker é lento para dev local | Média | Médio | Fallback para execução local com warnings; modo `local_warn` |
| JWT auth quebra desktop legacy | Média | Alto | Manter suporte a token local; transição gradual |
| llama.cpp separado aumenta latência | Média | Médio | Colocar inference no mesmo host/network; usar Unix sockets se possível |
| Terraform lock-in em cloud provider | Média | Médio | Usar módulos abstratos; documentar deploy self-hosted como alternativa |

---

## 8. Conclusão

Este roadmap transforma 45+ lacunas individuais em **9 branches de trabalho significativas**, cada uma com escopo claro, critérios de aceitação mensuráveis, e estimativa de esforço realista.

**A ordem foi desenhada para maximizar valor entregue cedo:**
- **Semanas 1-2:** Segurança crítica (prompt injection, rate limiting) — sem isso, não há produto seguro
- **Semanas 3-4:** Containerização e sandbox — sem isso, não há deploy confiável
- **Semanas 5-6:** Refatoração e separação de inference — sem isso, não há escalabilidade
- **Semanas 7:** UX e onboarding — sem isso, usuários não adotam
- **Semanas 8-9:** DevOps e infraestrutura — sem isso, não há operação sustentável

> **Recomendação final:** Não tente fazer tudo de uma vez. Priorize Branches 1 e 2 (segurança) e Branch 3 (containerização). Com essas 3 branches merged, o PersonAgent já estará em um estado tecnicamente respeitável para early adopters.
