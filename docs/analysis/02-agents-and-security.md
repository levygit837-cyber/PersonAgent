# PersonAgent - Agentes e Seguranca

**Data:** 2026-05-14 | **Versao do software:** 0.1.0 (Alpha) | **Classificacao:** Tecnico/Seguranca

---

## 1. O Que Torna o PersonAgent Diferente em Agentes

### 1.1 Diferencial Tecnico Real

O PersonAgent se diferencia de outros coding agents por tres capacidades que nao existem combinadas em nenhum competitor open-source:

**A) Browser Nativo com CDP Completo**

O LightPanda worker (5735 LOC) implementa um browser headless via Chrome DevTools Protocol com:
- 19 ferramentas de browser (BrowserSearch, BrowserOpen, BrowserClick, BrowserType, BrowserScreenshot, BrowserScript, BrowserAct, etc.)
- Extracao de conteudo inteligente com scoring de relevancia (remove nav, footer, ads, popups)
- Caching de CSS e render snapshots
- Cooperacao agente-browser: anotacoes em elementos DOM, timeline de acoes, acoes propostas com arbitrio de seguranca (BrowserActionArbiter)
- Session management com TTL e max sessions configuravel

Nenhum outro agente open-source tem isso. Aider e Cline usam web_fetch simples; Cursor usa browser cloud; Devin tem browser mas e proprietario e SaaS-only.

**B) Team Mode com Blackboard e Votacao**

O TeamChatOrchestrator (3086 LOC) implementa:
- Fases: independent_round -> blackboard_publish -> debate_round -> vote -> execution_contract -> coordinator_planning -> coordinator_final
- Blackboard compartilhado: claim graph com deduplicacao por assinatura, coverage matrix, novelty scores
- Votacao com consenso: threshold configuravel, critical blockers, confidence scores
- Execution contracts: subproblems, success_criteria, risks, focus_assignments
- Tool phases: plan_tools -> read_tools -> mutating_proposal -> tool_audit
- Auditoria de ferramentas mutantes: Write, Edit, TodoWrite, TaskCreate/Update/Close

Isso e equivalente a um "jury system" para decisoes de codigo. Nenhum competitor tem isso integrado.

**C) Memoria com Consolidacao Automatica e Trace**

O sistema de memoria tem:
- Memoria estruturada (MemoryFile com headers e tipos)
- Memoria operacional com captura em tempo real, chunking, embeddings pgvector
- Recall semantico com HNSW indexes e subvector search
- AutoDream: consolidacao automatica (merge duplicatas, update outdated, remove obsoletas)
- Memory trace: rastreabilidade de como memorias foram selecionadas e usadas
- Trust levels e importance scoring

### 1.2 O Que Falta para Ser Realmente Util

| Gap | Impacto | Esforco |
|-----|---------|---------|
| Agentes nao podem criar sub-agentes | Limita tarefas complexas | Alto |
| Sem agendamento de tarefas | Limita automacao | Medio |
| Sem streaming de Team Mode para UI | UX quebrada | Medio |
| Browser tools dependem de LightPanda container | Setup complexo | Baixo |
| Sem retry/resilience em browser CDP | Falhas silenciosas | Medio |
| Memoria nao e compartilhada entre sessoes por padrao | Perda de contexto | Medio |

---

## 2. Analise do Sistema de Agentes

### 2.1 ChatCompletionUseCase (2633 LOC)

O use case principal de chat e o cerebro do agente. Fluxo:

1. Resolve conversation (get_or_create)
2. Build context (system + user + memory + workspace)
3. Prepare prompt surfaces (slash commands, context attachments, browser target)
4. Resolve tool schemas (com base no prompt_mode e agent_state)
5. Enforce provider data policy (scan de dados sensiveis)
6. LLM inference (streaming)
7. Tool loop (execute tools, feed results back, repeat)
8. Persist messages
9. Emit SSE events

**Pontos fortes:**
- Tool loop com max_iterations configuravel
- Plan mode com approval flow
- Memory recall integrado no context build
- Browser cooperation integrado no prompt
- Slash commands extensivel (CommandRegistry)

**Pontos fracos:**
- 2633 LOC em um unico use case - monolito que precisa de decomposicao
- Tool loop e sincrono dentro do async (await por tool, sem pipeline)
- Sem timeout total do use case (apenas timeout por tool)
- Sem cancelamento cooperativo (se o usuario cancelar, o loop continua)

### 2.2 TeamChatOrchestrator (3086 LOC)

O orquestrador de team mode e impressionante em complexidade:

**Fases implementadas:**
- `independent_round`: cada agente trabalha independentemente
- `blackboard_publish`: publicacao de claims no blackboard
- `debate_round`: agentes debatem sobre claims conflitantes
- `vote`: votacao com confidence e blockers
- `execution_contract`: contrato de execucao com subproblems e success criteria
- `coordinator_planning`: coordinator define focus assignments e debate goals
- `coordinator_final`: sintese final

**Blackboard features:**
- Claim graph com deduplicacao por assinatura (hash de conteudo)
- Coverage matrix: subproblem x agent coverage
- Novelty scores: penaliza agentes que repetem claims existentes
- Duplicate detection com similarity scoring

**Tool policy:**
- `guarded_autonomy`: ferramentas read-only automaticas, mutating com proposal + audit
- Tool audit: registra todas as calls mutantes para revisao
- Proposals: agentes proporem acoes mutantes, auditor valida

**Limitacoes:**
- 3086 LOC em um arquivo - precisa de decomposicao em modulos
- Sem streaming incremental para o frontend (coleta tudo e envia no final)
- Blackboard e in-memory por run (nao persiste entre runs)
- Sem persistencia de team runs no banco (apenas blackboard_events)
- Votacao e baseada em texto (LLM parse), nao estruturada

### 2.3 ToolOrchestrator (558 LOC)

O orquestrador de ferramentas e bem projetado:

**Features:**
- Particionamento automatico: ferramentas concurrency-safe rodam em paralelo, outras em serie
- Max concurrency configuravel
- Progress callbacks com SSE streaming
- Timeout por ferramenta
- Error handling com ToolError hierarchy
- Permission check com ALLOW/DENY/ASK

**Limitacoes:**
- Sem prioridade de ferramentas (roda na ordem que o modelo emite)
- Sem retry de ferramentas falhas
- Sem circuit breaker para ferramentas que falham repetidamente
- Sem resource limits (memoria, CPU) por ferramenta

---

## 3. Seguranca: Estado Atual

### 3.1 O Que Existe e Funciona

**Local Auth (security.py):**
- Token gerado com secrets.token_urlsafe(48)
- Armazenado com chmod 0o600
- Validacao com secrets.compare_digest (timing-safe)
- Header X-PersonAgent-Client obrigatorio
- CORS restrito a localhost

**Provider Data Policy (provider_data_policy.py):**
- Scan de dados sensiveis antes de enviar para providers hospedados
- Patterns: API keys, bearer tokens, OpenAI keys, NVIDIA keys, private keys, credit cards, CPF
- Bloqueio automatico se encontrar qualquer match

**Shell Safety (shell_tool.py):**
- Lista de comandos read-only (cat, ls, grep, git log, etc.)
- Bloqueio de comandos criticos (rm -rf /, sudo, mkfs, dd, mount, shutdown, systemctl)
- Bloqueio de shell meta tokens (|, >, <, ;, &&, ||, $(), backticks)
- Modos de permissão: read_only, manual, accept_edits, full, bypass

**Path Safety (path_safety.py):**
- resolve_within_allowed_roots: garante que paths estao dentro de roots permitidos
- Path traversal protection via Path.resolve()

**Action Approvals (Electron main.ts):**
- HMAC-SHA256 signed approvals
- TTL de 300 segundos
- Allowlist de acoes (git_commit, git_push, git_pr)
- Canonical args hash para impedir tampering

**Browser Safety (browser_tools.py):**
- CDP allowlist: apenas Runtime.evaluate, DOM.*, Page.captureScreenshot, Log.*
- Max script size: 10_000 chars
- Max script result: 12_000 chars
- URL validation com denylist de schemes (javascript:, data:, file:)
- BrowserActionArbiter: valida acoes antes de executar

### 3.2 Gaps de Seguranca Criticos

**A) Sem Autenticacao Multi-Usuario**

O sistema atual e single-tenant. Para deploy multi-usuario:

- Necessario: User model, JWT/OAuth, session management
- Risco atual: Qualquer pessoa com o token local tem acesso total
- Mitigacao: Implementar RBAC com roles (admin, user, viewer)

**B) Sem Isolamento de Workspace Entre Usuarios**

- Workspace grants sao in-memory no Electron (Map<string, string>)
- Backend aceita workspace_root sem validacao de propriedade
- Necessario: Workspace ownership, access control lists

**C) Prompt Injection**

O PersonAgent processa input do usuario e output de ferramentas no mesmo contexto LLM:
- Tool results sao incluidos no prompt sem sanitizacao
- Browser content e incluido sem escaping
- Necessario: Input sanitization, output filtering, prompt boundary markers

**D) Shell Tool - Bypasses Possiveis**

- `sed` esta na lista read-only mas pode modificar arquivos (`sed -i`)
- `find` com `-exec` pode executar comandos arbitrarios
- `git` com subcommands nao-read-only (git push, git reset --hard) nao sao bloqueados
- Pipes nao sao detectados dentro de argumentos (e.g., `echo foo | tee /etc/passwd`)

**E) MCP Tools - Execucao Arbitraria**

- MCP servers com `command` executam processos arbitrarios via stdio
- Sem sandboxing ou resource limits para MCP subprocesses
- Necessario: Sandbox (Docker/namespace), allowlist de comandos, resource limits

**F) Browser Script Injection**

- BrowserScript permite JavaScript arbitrario no contexto da pagina
- CDP allowlist e limitada mas Runtime.evaluate e muito permissivo
- Necessario: CSP enforcement, script validation, sandbox de execucao

**G) Sem Audit Log**

- Nao ha log persistido de acoes do agente (shell commands, file writes, browser actions)
- Necessario para compliance e debugging: audit trail com user_id, action, arguments, result, timestamp

### 3.3 Implicacoes para Deploy Escalavel

| Risco | Probabilidade | Impacto | Mitigacao |
|-------|---------------|---------|-----------|
| Usuario acessa workspace de outro | Alta sem auth | Critico | Multi-tenancy + workspace ACL |
| Shell bypass modifica sistema | Media | Alto | Shell allowlist + sandboxing |
| Prompt injection via tool output | Alta | Medio | Input sanitization + boundaries |
| MCP command execution | Media | Alto | Sandbox + allowlist |
| Browser script XSS | Baixa | Medio | CSP + script validation |
| Resource exhaustion por usuario | Alta sem limits | Alto | Rate limiting + resource quotas |
| Data leak para hosted providers | Media | Critico | Provider data policy (ja existe) |

---

## 4. Os Agentes Supriem Necessidades de Diversos Usuarios?

### 4.1 Persona de Usuarios

| Persona | Necessidade | PersonAgent Supre? | Gap |
|---------|-------------|-------------------|-----|
| **Dev Junior** | Ajuda para escrever codigo, explicar conceitos | Parcial | Sem onboarding, UX complexa |
| **Dev Senior** | Automacao de tarefas repetitivas, code review | Sim | Ferramentas completas, Team Mode |
| **Dev Lead** | Planejamento de arquitetura, documentacao | Parcial | Sem diagramacao, sem design docs |
| **DevOps** | Infra as code, CI/CD, deploy | Parcial | Shell tool limitado, sem cloud tools |
| **QA/Tester** | Testes automatizados, browser testing | Sim | Browser tools sao forte |
| **Data Scientist** | Notebooks, data analysis, ML | Nao | Sem notebook support, sem data tools |
| **Designer** | UI/UX, prototipagem | Nao | Sem design tools, sem visual editing |

### 4.2 Recomendacao

O PersonAgent atende bem **desenvolvedores backend/fullstack** que valorizam:
- Controle local e privacidade
- Automacao de tarefas de codigo
- Browser automation para testes e pesquisa
- Multi-agente para decisoes complexas

Para atingir mais personas, necessita:
- **Notebook support** (para Data Scientists)
- **Design/visual tools** (para Designers)
- **Cloud/infra tools** (para DevOps)
- **Simplified onboarding** (para Juniors)

---

## 5. Como Mostrar os Pontos Fortes aos Usuarios

### 5.1 Messaging Prioritario

1. **"Seu agente de codigo com browser proprio"** - Nenhum competitor open-source tem browser nativo
2. **"Time de agentes trabalhando junto"** - Team Mode e unico
3. **"Memoria que evolui"** - AutoDream e consolidacao sao diferenciais
4. **"Local-first, seus dados ficam com voce"** - Privacidade e trending

### 5.2 Demo Scenarios

| Scenario | Ferramenta | Impacto Visual |
|----------|-----------|----------------|
| Pesquisar docs e implementar feature | BrowserSearch + Read + Write + Edit | Alto |
| Code review com multi-agente | Team Mode (Analyst + Critic + Builder + Reviewer) | Muito Alto |
| Debug com browser testing | BrowserOpen + BrowserScreenshot + BrowserScript | Alto |
| Refatorar com memoria de contexto | Memory recall + Read + Edit + Shell (test) | Medio |
| Automatizar PR workflow | Workspace tools + Git tools + Action Approvals | Medio |

### 5.3 Product-Led Growth

- **Free tier**: Agente single com browser local, 1 provider, sem Team Mode
- **Growth trigger**: "Desbloqueie Team Mode e memoria avancada" apos N conversas
- **Viral loop**: Compartilhar skills e team configs na marketplace

---

## 6. Recomendacoes de Seguranca Prioritarias

### 6.1 Curto Prazo (1-2 meses)

1. **Corrigir shell bypasses**: remover `sed` da lista read-only, bloquear `find -exec`, bloquear git subcommands mutantes
2. **Adicionar audit log**: tabela no PostgreSQL com user_id, action, arguments_hash, result_hash, timestamp
3. **Sanitizar tool output antes de incluir no prompt**: strip de padroes de prompt injection
4. **Rate limiting basico**: por conversation_id e por IP

### 6.2 Medio Prazo (3-6 meses)

5. **Multi-tenancy**: User model, JWT auth, workspace ownership
6. **MCP sandboxing**: Docker containers ou namespaces para MCP subprocesses
7. **Browser script validation**: CSP, sandbox de execucao, script allowlist
8. **Resource quotas**: CPU, memoria, tempo por sessao de agente

### 6.3 Longo Prazo (6-12 meses)

9. **RBAC completo**: roles, permissions, access control lists
10. **Compliance**: SOC 2 Type II, audit logs imutáveis, data retention policies
11. **Encryption at rest**: dados sensiveis criptografados no PostgreSQL
12. **Penetration testing**: teste de seguranca profissional antes de launch
