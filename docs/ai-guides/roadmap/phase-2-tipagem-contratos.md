# Fase 2 — Tipagem & contratos

| Chave        | Valor                                                                                 |
| ------------ | ------------------------------------------------------------------------------------- |
| Fase         | 2                                                                                     |
| Status       | `pending`                                                                             |
| Owner        | repo-maintainer                                                                       |
| Iniciada     | —                                                                                     |
| Concluída    | —                                                                                     |
| Depends on   | Fase 1 (`completed`)                                                                  |
| Unblocks     | Fase 3                                                                                |

## Objetivo

Substituir `dict[str, Any]` por **dataclasses / Pydantic models** nos
contratos de domain e nas fronteiras (request/response, eventos
SSE/WebSocket, payloads de tool results). Cravar o gate do mypy em
modo **estrito** para todo o backend e estabelecer
schemas-source-of-truth para o frontend consumir.

A regra é: nenhum dado atravessa fronteira de módulo via
`dict[str, Any]`. Dentro de funções, `Any` continua permitido onde
faz sentido (parsing inicial de JSON externo, p.ex.); na borda, vira
modelo tipado.

## Contexto

Re-análise feita em 2025-11-23 sobre o `main` atual:

- **984 ocorrências** de `dict[str, Any]` em `@backend/src` (down de
  985 da análise inicial — praticamente intacto).
- **292 anotações** com `Any` em `@backend/src`.
- **176 ocorrências** de `getattr`/`setattr` (acesso dinâmico que
  esconde tipos).
- **16 `# type: ignore`** restantes.
- **301 erros** do mypy estrito no `src/` completo. Concentração:
  - `interfaces/api/routes/sessions.py` — 46 erros.
  - `interfaces/api/routes/chat.py` — 33 erros.
  - `infrastructure/persistence/models.py` — 33 erros.
  - `interfaces/config/di_container.py` — 19 erros.
  - `application/services/session_panel.py` — 19 erros.
  - `application/services/browser_cooperation.py` — 11 erros.
  - `infrastructure/browser/lightpanda.py` — 10 erros.

O CI atual escopa o mypy a um whitelist de módulos já limpos
(ver [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml)).
Fase 2 expande esse whitelist até **incluir todo o `src/`**.

## Decisões aplicáveis

- `DEC-002` — Clean Architecture (modelos no domain, schemas Pydantic
  na borda da interfaces layer).
- `DEC-007` — Decomposition antes de tipagem (Fase 1 é pré-requisito
  para esta fase).

## Sub-fases

### 2.1 — Schemas Pydantic na borda HTTP

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 2.1               |
| Status       | `pending`         |

#### Deliverables

- [ ] Todo `POST` / `GET` em `interfaces/api/routes/` retorna um
      `pydantic.BaseModel` específico (não `dict`, não `Any`).
- [ ] Request bodies têm classe `*Request` ou `*Payload` em
      `interfaces/api/schemas/` (criar diretório).
- [ ] OpenAPI gerado pelo FastAPI inclui todos os schemas (verificar
      via `GET /openapi.json` — todo `response_model` declarado).
- [ ] Frontend (`@desktop-electron/src/api/client.ts`) consome
      tipos gerados do OpenAPI (script `npm run generate-api-types`).

#### Critérios de aceitação

- `grep -nE "-> dict\[str, Any\]" @backend/src/personagent/interfaces/`
  retorna 0 ocorrências.
- `grep -nE "request: dict" @backend/src/personagent/interfaces/api/routes/`
  retorna 0 ocorrências.
- `npm run typecheck` no frontend continua passando.

### 2.2 — Domain models tipados

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 2.2               |
| Status       | `pending`         |

#### Deliverables

- [ ] `Conversation.metadata`, `Message.metadata` — substituir
      `dict[str, Any]` por dataclass / typed dict com keys conhecidas.
- [ ] `InferenceResult` e `StreamChunk` totalmente tipados
      (estão parcialmente tipados hoje).
- [ ] Tool runtime: `ToolContext`, `ToolCallResult`, `ToolMessage`
      revisados para zero `Any` em campos públicos.
- [ ] `memory_trace` (passa por várias camadas) ganha um modelo
      dedicado em `domain/models/memory_trace.py`.

#### Critérios de aceitação

- mypy estrito clean em `domain/models/` inteiro.
- Mensagens de erro em runtime apontam para o campo errado (ex.:
  Pydantic ValidationError em vez de `KeyError`).
- Migrações Alembic acompanham as mudanças de schema persistido.

### 2.3 — Eventos SSE/WebSocket tipados

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 2.3               |
| Status       | `pending`         |

#### Deliverables

- [ ] Cada `event_type` declarado em `interfaces/api/state_events.py`
      tem uma classe `*Event` com payload tipado.
- [ ] Frontend deriva tipos via OpenAPI ou TS file gerado.
- [ ] Audit table: lista de todos os `event_type` strings vs classe
      Python que os produz vs handler TS que os consome.

#### Critérios de aceitação

- `grep -nE 'yield .*"type":\s*"[a-z_]+"' @backend/src/` retorna
  apenas dentro de classes `*Event` ou suas factories.
- Adicionar um event novo sem declarar a classe quebra mypy.

### 2.4 — Auth real (não só primitives)

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 2.4               |
| Status       | `pending`         |

#### Deliverables

- [ ] OAuth2 / OIDC para uso multi-usuário (provider a definir:
      GitHub, Google ou Clerk/Auth0 como dependência externa).
- [ ] Mantém o caminho local: `LOCAL_AUTH_ONLY=1` continua usando
      bearer token (ADR-0018), só skipa o OAuth.
- [ ] `users` table de Fase 1.1 ganha `auth_provider`, `external_id`,
      `email_verified`.
- [ ] RBAC mínimo: roles `owner` / `member` por tenant (sem permissions
      granulares ainda).

#### Critérios de aceitação

- Endpoint `/auth/callback` integrado e coberto por integration test.
- `RequestContext.user_id` populado em toda request autenticada.
- `LOCAL_AUTH_ONLY=1` continua passando todos os testes existentes
  (não-regressão).

### 2.5 — mypy estrito em todo o backend

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 2.5               |
| Status       | `pending`         |

#### Deliverables

- [ ] CI job `backend` roda `uv run mypy src/` sem whitelist.
- [ ] `strict = true` em `pyproject.toml`.
- [ ] `# type: ignore` restantes (16 atualmente) todos com comentário
      explicando o porquê — formato `# type: ignore[<rule>]  # razão`.

#### Critérios de aceitação

- `uv run mypy src/` exit code 0 em `main`.
- 0 erros novos introduzidos por qualquer PR (gate enforced).

## Critérios de aceitação da Fase 2 (consolidados)

- ✅ Todas as sub-fases (2.1–2.5) com deliverables marcados.
- `dict[str, Any]` em `@backend/src` ≤ 100 (de 984 atuais) — restantes
  apenas em parsers de JSON externo e validações iniciais, todas
  documentadas.
- `Any` annotation count ≤ 50.
- mypy estrito clean no backend inteiro.
- Frontend consome tipos gerados do OpenAPI (uma fonte de verdade).
- Caminho local (`LOCAL_AUTH_ONLY=1`) continua funcionando idêntico
  ao Fase 1.

## Riscos & mitigações

| Risco                                                                                   | Mitigação                                                                                                                                              |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tipar metadata "aberto" (`Conversation.metadata`, `memory_trace`) quebra dados antigos | Migration Alembic + versionamento de schema com campo `metadata_version`; código aceita ambas as versões durante uma sprint de transição.              |
| OAuth adiciona dependência externa que quebra dev local                                | Provider de auth atrás de uma feature flag `LOCAL_AUTH_ONLY=1` (default em dev). CI roda os dois modos (matrix).                                       |
| Frontend descompassa do backend quando schemas mudam                                   | `npm run generate-api-types` rodado em pre-commit; CI valida que tipos estão em sync (`git diff --exit-code` após generate).                          |
| mypy estrito cria centenas de PRs ruidosos                                             | Atacar por arquivo, na ordem inversa do count de erros (sessions.py primeiro). Cada PR fecha um arquivo. Whitelist do CI cresce a cada merge.        |
| RBAC mínimo (owner/member) vira RBAC complexo no meio do caminho                       | Out of scope explícito: zero permissions granulares (Plan Mode, Workspace Grant, etc continuam aplicação-side). Roles são só sobre tenant access.    |

## PRs vinculados

Fase ainda não iniciada. Tabela cresce conforme PRs forem abrindo.

| PR  | Sub-fase | Título | Status | Notas |
| --- | -------- | ------ | ------ | ----- |
| —   | —        | —      | —      | —     |

## Notas operacionais

- **Ordem sugerida de execução:** 2.1 → 2.2 → 2.3 → 2.4 → 2.5.
  2.5 é o lock final; sem 2.1–2.4, não dá pra ligar `strict = true`
  sem milhares de erros simultâneos.
- **Antes de iniciar 2.4 (auth real),** revalidar ADR-0018: o ADR
  hoje declara "local-only forever". A Fase 2 muda essa decisão e
  precisa de ADR-0018 atualizado (status `superseded`) + ADR-0022
  novo cobrindo OAuth multi-tenant. Coordenar com `DEC-008`.
- A análise inicial (sessão `e35857f9...`) já apontava
  `dict[str, Any]` como a próxima dor depois dos god files. Esta
  fase materializa esse plano.
