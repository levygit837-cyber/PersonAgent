# Fase 3 — Escala & produto

| Chave        | Valor                                                                                 |
| ------------ | ------------------------------------------------------------------------------------- |
| Fase         | 3                                                                                     |
| Status       | `pending`                                                                             |
| Owner        | repo-maintainer                                                                       |
| Iniciada     | —                                                                                     |
| Concluída    | —                                                                                     |
| Depends on   | Fase 2 (`completed`)                                                                  |
| Unblocks     | Produto público                                                                       |

## Objetivo

Transformar o PersonAgent de "app local desktop" em "produto
escalável" — sem sacrificar o caminho local. Foco em:

1. **Isolamento real entre tenants** — RLS no Postgres + escopo de
   workspace via DB, não via filesystem.
2. **BYOK seguro** — usuário traz chave de provider; backend cifra
   em repouso, descriptografa só na hora de chamar o LLM.
3. **Observabilidade** — métricas Prometheus, tracing OpenTelemetry,
   eventos auditáveis (tool calls, approvals, payloads bloqueados).
4. **Workers e jobs persistentes** — extração de memória, dream
   consolidation, indexação saem do processo principal.
5. **Deploy & operação** — imagem Docker oficial, `docker-compose`
   pronto, runbook de operação, gates de release.
6. **Limites e billing primitives** — rate limiting por tenant +
   contagem de tokens consumidos (sem cobrança ainda, apenas leitura).

## Contexto

Re-análise feita em 2025-11-23 mostrou que o backend atual:

- **Não tem workers** — `asyncio.create_task` é o que existe; nada
  persistente (sem Celery/RQ/Dramatiq/Arq). Memória extraction roda
  inline em `MemoryJobScheduler`.
- **Não tem observabilidade externa** — zero refs a `prometheus`,
  `opentelemetry`, `otel`. Algumas estruturas internas (`runtime_tracer`,
  `blackboard` metrics) existem mas não exportam.
- **Não tem cifra de BYOK** — busca por `cryptography`, `fernet`,
  `cipher`, `encrypted_key` em `@backend/src` retorna zero.
- **Tem rate-limit logic primitiva** mas nada por-tenant: refs
  aparecem em `errors.py`, `settings.py`, `retry.py` (retry budget),
  mas não throttling de request.
- **Tem RLS aspiracional** (DEC-004) mas não aplicada — tabela
  `tenants` existe (PR #6), as outras tabelas não usam `tenant_id`
  em row policy.
- **ADR-0018 declara "local-only forever"** — Fase 2.4 muda isso.

## Decisões aplicáveis

- `DEC-003` — BYOK first, nunca persistir chave em claro.
- `DEC-004` — Postgres + pgvector + RLS (efetivar aqui).
- `DEC-008` — Local-first mantido, SaaS aditivo.

## Sub-fases

### 3.1 — RLS multi-tenant efetivo

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.1               |
| Status       | `pending`         |

#### Deliverables

- [ ] Toda tabela com dados de usuário ganha coluna `tenant_id NOT NULL`
      (revision Alembic em `infrastructure/persistence/alembic/versions/`).
- [ ] Policy `ROW LEVEL SECURITY` ativa em cada tabela; `current_setting('app.tenant_id')`
      filtra rows.
- [ ] Middleware FastAPI seta `SET LOCAL app.tenant_id = '<uuid>'`
      por request (escopo de conexão).
- [ ] Integration test: tenant A não vê dado de tenant B mesmo via SQL
      direto.

#### Critérios de aceitação

- Test suite com 2 tenants paralelos confirma isolamento.
- `EXPLAIN` de query mostra policy aplicada.

### 3.2 — BYOK criptografado em repouso

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.2               |
| Status       | `pending`         |

#### Deliverables

- [ ] Tabela `provider_credentials` com `tenant_id`, `provider`,
      `ciphertext`, `nonce`, `key_version`.
- [ ] Master key em variável de ambiente / KMS externo
      (`PERSONAGENT_MASTER_KEY` ou AWS KMS arn em config).
- [ ] Cifra simétrica: AES-256-GCM via `cryptography` lib. Key
      rotation via `key_version` (revision Alembic + lambda de
      re-encrypt).
- [ ] Endpoint `POST /me/credentials/{provider}` aceita chave,
      cifra, persiste. **Nunca retorna a chave plaintext** depois.
- [ ] Adaptadores LLM (`infrastructure/llm/*_adapter.py`) recebem a
      chave via `RequestContext`, decifrada apenas no escopo da
      request.

#### Critérios de aceitação

- `SELECT ciphertext FROM provider_credentials` no DB nunca expõe
  chave legível.
- `key_version` permite rotação sem downtime.
- Modo local (`LOCAL_AUTH_ONLY=1`) usa env vars como antes — chave
  nunca é gravada no DB.

### 3.3 — Workers persistentes

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.3               |
| Status       | `pending`         |

#### Deliverables

- [ ] Selecionar runtime: avaliar **Arq** (Redis-backed, async-native,
      leve) vs **Dramatiq** (broker-agnóstico, prod-grade). ADR
      novo com a decisão.
- [ ] `application/jobs/memory_job_scheduler.py` migrado de
      `asyncio.create_task` para job queue persistente.
- [ ] Auto-dream + extração + indexação rodam como jobs separados,
      retry com backoff exponential, visibilidade no painel.
- [ ] `docker-compose.yml.example` ganha serviço `worker` separado
      do `web`.

#### Critérios de aceitação

- Reiniciar o backend não perde job pendente (state no broker).
- Job que crasha não bloqueia o request loop.
- Endpoint `/admin/jobs` lista status (queue length, in_flight,
  failed last hour).

### 3.4 — Observabilidade

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.4               |
| Status       | `pending`         |

#### Deliverables

- [ ] Prometheus exporter em `/metrics`: counters de requests,
      histograms de latência por endpoint, gauges de queue depth.
- [ ] OpenTelemetry tracing: span por request, span por tool call,
      span por LLM completion. OTLP exporter configurável.
- [ ] Audit log estruturado: `tool_call_started`, `tool_call_completed`,
      `policy_block`, `approval_granted`, `model_inference_completed`
      etc. — payload JSON com `tenant_id`, `user_id`, `request_id`,
      `duration_ms`. Sink configurável (stdout, file, Loki).
- [ ] Dashboard exemplo (Grafana JSON) commitado em `ops/dashboards/`.

#### Critérios de aceitação

- `curl /metrics` retorna métricas em formato Prometheus.
- Span tree de uma request inclui ao menos: HTTP handler → use case
  → tool calls → LLM call.
- Audit log inclui todo `tool_call` com `tenant_id`.

### 3.5 — Rate limiting + billing primitives

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.5               |
| Status       | `pending`         |

#### Deliverables

- [ ] Rate limiter por tenant em request path (sliding window via
      Redis). Configurável por plano.
- [ ] Tabela `usage_events`: token_in, token_out, provider, model,
      cost_cents, tenant_id, user_id, ts.
- [ ] Adaptadores LLM emitem `usage_event` ao final de cada chamada
      (já têm os números, basta persistir).
- [ ] Endpoint `/me/usage` retorna agregado por mês.
- [ ] **Sem cobrança ainda** — só leitura.

#### Critérios de aceitação

- Tenant com plano "free" excedendo limite recebe 429 com header
  `Retry-After`.
- `usage_events` correlaciona 1-pra-1 com `conversation_id` (auditável).

### 3.6 — Deploy & runbook

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 3.6               |
| Status       | `pending`         |

#### Deliverables

- [ ] `Dockerfile` produção oficial (multi-stage, distroless ou
      alpine, < 200MB).
- [ ] Imagem publicada em registry (GitHub Container Registry).
- [ ] `docker-compose.production.yml.example` cobrindo `web`, `worker`,
      `postgres+pgvector`, `redis`, `nginx`.
- [ ] Runbook em `docs/ops/runbook.md`: rollback, restore de backup,
      rotação de chave master, hot-reload de config.
- [ ] Health checks: `/healthz`, `/readyz` cobrindo DB, Redis, workers.

#### Critérios de aceitação

- `docker compose up` traz o stack inteiro em < 60s em laptop padrão.
- Restart de qualquer container não derruba os demais (graceful).
- Backup + restore de DB testado em CI (smoke test).

## Critérios de aceitação da Fase 3 (consolidados)

- Stack production-ready: web + worker + DB + Redis + reverse proxy.
- 2+ tenants isolados via RLS comprovado em integration test.
- BYOK funciona end-to-end: cadastra chave → conversa → métrica de
  uso registrada → chave nunca aparece em log nem em disco em claro.
- Dashboard de observabilidade visualiza latência p50/p95/p99 e
  queue depth.
- Caminho local (`LOCAL_AUTH_ONLY=1`, sem Redis, sem worker
  separado) continua funcionando — testado em CI.

## Riscos & mitigações

| Risco                                                                                | Mitigação                                                                                                                                                  |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RLS adiciona overhead a toda query (10–30% típico)                                  | Bench antes/depois em `pgbench` + ajustar índices em `(tenant_id, ...)` para cada tabela. Aceitar o custo — segurança não é negociável.                  |
| BYOK cifrado complica debug (não dá pra inspecionar chave no DB)                    | Logging estruturado de tentativas de decrypt + endpoint admin (`/admin/decrypt-test`) gated por master key + auditoria.                                  |
| Worker queue adiciona ponto de falha novo                                            | Health check inclui worker readiness; backpressure quando queue depth > threshold. Modo local mantém async-only.                                          |
| Observabilidade explode cardinalidade (label `user_id` em métrica Prometheus)       | Labels só com `tenant_id` (não `user_id`); detalhe vai pra traces (OTel) onde a cardinalidade não é problema.                                            |
| OAuth (Fase 2.4) + BYOK (Fase 3.2) + RLS (Fase 3.1) viram superfície grande de bugs | Lançar com 1 tenant beta interno + 2 tenants externos antes de abrir signup. Audit log + replay de eventos.                                              |
| Fase 3 cresce indefinidamente ("billing real", "plans", "subscriptions")            | **Fora de escopo explícito**: pagamento de verdade (Stripe), plans, downgrades, refunds. Esses temas viram Fase 4 se justificarem.                       |

## Out of scope explícito

Para evitar scope creep no meio do caminho:

- **Pagamento de verdade.** Stripe, plans, subscriptions, refunds.
  Usage tracking sim, cobrança não.
- **Mobile.** Cliente Electron é o produto. Mobile é Fase 4+.
- **Sharing entre tenants.** Cada tenant é uma ilha; não há
  "compartilhar conversa com outro tenant" nesta fase.
- **Marketplace de skills entre tenants.** Skills continuam sendo
  arquivos no filesystem do usuário (ADR-0008).
- **Self-hosted enterprise.** O foco é PersonAgent gerenciado;
  self-hosted é caso de uso, não produto separado.

## PRs vinculados

Fase ainda não iniciada.

| PR  | Sub-fase | Título | Status | Notas |
| --- | -------- | ------ | ------ | ----- |
| —   | —        | —      | —      | —     |

## Notas operacionais

- **Ordem sugerida:** 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6. RLS antes de
  BYOK porque BYOK depende de isolamento real. Workers antes de
  observabilidade porque a métrica mais útil é "queue depth", que só
  existe quando tem worker.
- Cada sub-fase deve abrir um ADR novo se introduzir tech (Arq vs
  Dramatiq, Prometheus vs StatsD, etc.). Roadmap referencia o ADR;
  decisão real vive lá.
- **Trigger de início:** Fase 2 fechada (mypy estrito, schemas
  Pydantic, OAuth real). Sem 2 fechada, 3 vira "rebuild during
  rebuild".
