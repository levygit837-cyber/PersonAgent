# Fase 1 — Hardening estrutural

| Chave        | Valor                                                                                 |
| ------------ | ------------------------------------------------------------------------------------- |
| Fase         | 1                                                                                     |
| Status       | `in_progress`                                                                         |
| Owner        | repo-maintainer                                                                       |
| Iniciada     | 2025-11-23                                                                            |
| Concluída    | —                                                                                     |
| Depends on   | Fase 0                                                                                |
| Unblocks     | Fase 2                                                                                |

## Objetivo

Tornar o backend **refatorável**: introduzir primitives de
multi-tenancy no domain/schema (sem RBAC ainda) e quebrar os god
files em colaboradores coesos, com testes unitários por colaborador.
A meta é deixar o repo em estado em que tipagem estrita (Fase 2) e
escalabilidade (Fase 3) possam ser atacadas sem mergulhar em
monolitos de 3 mil linhas.

## Contexto

A análise da Fase 0 listou cinco god files (`chat_completion.py`
2,742 L; `team_chat/orchestrator.py` 3,097 L; `lightpanda.py` 5,735 L;
`session-panel.tsx` 3,960 L; `chat-store.ts` 3,307 L) e 985
ocorrências de `dict[str, Any]` no backend. Decomposição **antes** de
tipagem (`DEC-007`): refatorar tipos em arquivo de 3 mil linhas vira
merge hell.

A Fase 1 tem dois eixos paralelos:

- **1.1 Multi-tenant primitives** — domain (`tenant_id` em
  `Conversation`), schema (tabelas `tenants`, `users`), sem auth.
- **1.2 God file decomposition** — extrair colaboradores de cada god
  file seguindo os playbooks em
  [`docs/ai-guides/decomposition/`](../decomposition/).

## Decisões aplicáveis

- `DEC-002` — Clean Architecture mantida.
- `DEC-004` — Postgres + pgvector + RLS (preparação aqui, RLS efetiva em Fase 3).
- `DEC-006` — Multi-tenant primitives sem RBAC ainda.
- `DEC-007` — God-file decomposition antes de tipagem.

---

## 1.1 — Multi-tenant primitives

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 1.1               |
| Status       | `completed`       |
| Iniciada     | 2025-11-23        |
| Concluída    | 2025-11-23        |

### Deliverables

- [x] Tabelas `tenants` e `users` criadas via Alembic revision
      `20251124_0000_0002_multi_tenant_primitives.py`.
- [x] Domain primitives em `domain/models/tenancy.py`:
      `DEFAULT_TENANT_ID` (UUID determinístico), `DEFAULT_TENANT_SLUG`.
- [x] `Conversation` carrega `tenant_id` sem violar boundaries (campo
      no domain, não na infrastructure).
- [x] `application/state/tenancy.py` expõe contexto de tenancy ao
      use-case layer.

### Critérios de aceitação

- `alembic upgrade head` em DB vazio cria a row default em `tenants`.
- `Conversation()` recém-instanciada tem `tenant_id ==
  DEFAULT_TENANT_ID`.
- Tests de fixtures não precisam declarar tenancy explicitamente
  (default fica transparente).

### PRs vinculados

| PR | Título | Status | Notas |
| --- | --- | --- | --- |
| [#6](https://github.com/levygit837-cyber/PersonAgent/pull/6) | Multi-tenant primitives (domain + schema) | merged | UUID default hard-coded; alembic revision 0002. |

---

## 1.2 — God file decomposition: `chat_completion.py`

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 1.2               |
| Status       | `completed`       |
| Iniciada     | 2025-11-23        |
| Concluída    | 2025-11-23        |

### Deliverables

- [x] `chat_completion.py` reduzido de 2,742 → 483 linhas (−82%).
- [x] 17 colaboradores extraídos em
      `application/use_cases/chat/` (4,040 LoC totais).
- [x] Cada colaborador tem testes unitários próprios em
      `tests/unit/test_chat_*.py` (~250 testes novos somados).
- [x] Comportamento preservado: ordem de side-effects (`update`
      antes de `pop("permission_mode")`), tratamento de
      `LLMBackendError` / `ToolLoopLimitExceededError`, chunk
      ordering — todos validados em review (PR #31 fixa as
      regressões de teste descobertas na revisão).
- [x] Playbooks atualizados em
      [`docs/ai-guides/decomposition/chat_completion.md`](../decomposition/chat_completion.md).
- [x] Review pós-merge identificou e corrigiu 6 testes que chamavam
      métodos privados removidos. — PR #31.
- [x] CI gate expandido para incluir `tests/test_tools_runtime.py` e
      `tests/integration/memory/test_chat_completion_with_memory.py`
      — testes de regressão pinados.

### Colaboradores extraídos

| Arquivo                          | Classe                          | PR                                                                   |
| -------------------------------- | ------------------------------- | -------------------------------------------------------------------- |
| `compaction.py`                  | `ConversationCompactor`         | [#7](https://github.com/levygit837-cyber/PersonAgent/pull/7)         |
| `tool_results.py`                | `ToolResultHandler`             | [#15](https://github.com/levygit837-cyber/PersonAgent/pull/15)       |
| `operational_memory.py`          | `OperationalMemoryCapture`      | [#9](https://github.com/levygit837-cyber/PersonAgent/pull/9)         |
| `memory_recall.py`               | `MemoryRecallCoordinator`       | [#10](https://github.com/levygit837-cyber/PersonAgent/pull/10)       |
| `prompt_surfaces.py`             | `PromptSurfacePreparer`         | [#11](https://github.com/levygit837-cyber/PersonAgent/pull/11)       |
| `prompt_package.py`              | `PromptPackageBuilder`          | [#13](https://github.com/levygit837-cyber/PersonAgent/pull/13)       |
| `message_preparation.py`         | `MessagePreparer`               | [#16](https://github.com/levygit837-cyber/PersonAgent/pull/16)       |
| `tool_context_builder.py`        | `ToolContextBuilder`            | [#18](https://github.com/levygit837-cyber/PersonAgent/pull/18)       |
| `after_turn.py`                  | `AfterTurnCoordinator`          | [#19](https://github.com/levygit837-cyber/PersonAgent/pull/19)       |
| `media_policy.py`                | `MediaPolicyHandler`            | [#20](https://github.com/levygit837-cyber/PersonAgent/pull/20)       |
| `conversation_lifecycle.py`      | `ConversationLifecycleHandler`  | [#22](https://github.com/levygit837-cyber/PersonAgent/pull/22)       |
| `stream_normalization.py`        | `StreamChunkNormalizer`         | [#23](https://github.com/levygit837-cyber/PersonAgent/pull/23)       |
| `state.py`                       | `StreamingTurnState` (dataclass) | [#24](https://github.com/levygit837-cyber/PersonAgent/pull/24)       |
| `assistant_pass.py`              | `AssistantPassRunner`           | [#25](https://github.com/levygit837-cyber/PersonAgent/pull/25)       |
| `streaming_turn.py`              | `StreamingTurnExecutor`         | [#28](https://github.com/levygit837-cyber/PersonAgent/pull/28)       |
| `tool_runtime.py`                | `ToolRuntime`                   | [#30](https://github.com/levygit837-cyber/PersonAgent/pull/30)       |
| `turn_context.py`                | `TurnContextResolver`           | [#30](https://github.com/levygit837-cyber/PersonAgent/pull/30)       |
| `background_tasks.py`            | `schedule_background` (função)  | [#30](https://github.com/levygit837-cyber/PersonAgent/pull/30)       |
| `helpers.py`                     | helpers de payload              | (vários, ver chat_completion.md)                                     |

### PRs vinculados (extras)

| PR | Título | Status | Notas |
| --- | --- | --- | --- |
| [#8](https://github.com/levygit837-cyber/PersonAgent/pull/8)   | Slice de preparação (pre-decomposition cleanup)            | merged | Não extraiu classe; preparou ground. |
| [#12](https://github.com/levygit837-cyber/PersonAgent/pull/12) | Playbooks de decomposição (`.github` + `docs/ai-guides`)   | merged | Cria `docs/ai-guides/decomposition/`. |
| [#31](https://github.com/levygit837-cyber/PersonAgent/pull/31) | Fix: testes migrados para nova superfície de colaboradores | merged | Corrige 6 regressões descobertas em review pós-merge. |

---

## 1.3 — God file decomposition: `team_chat/orchestrator.py`

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 1.3               |
| Status       | `in_progress`     |
| Iniciada     | 2025-11-23        |
| Concluída    | —                 |

### Deliverables

- [x] 6 colaboradores extraídos (PRs #14, #17, #21, #26, #27, #29) — `types`, `blackboard`, `agent_turn_runner`, `consensus_phase`, `coordinator_phase`, `final_synthesis`.
- [x] 108 testes (97 unit + 11 integration) verdes pós-extração.
- [ ] `orchestrator.py` reduzido para ≤ 600 linhas (atual: 982).
- [ ] `blackboard.py` (1,091 L) avaliado para nova fatia — pode ser
      candidato a sub-decomposição (estado de claims + evidence +
      blockers).

### Critérios de aceitação

- `wc -l application/team_chat/orchestrator.py` ≤ 600.
- `application/team_chat/blackboard.py` ≤ 800 ou justificativa
  documentada no playbook de por que parou aí.
- Todos os 108 testes existentes continuam passando.
- Playbook em
  [`docs/ai-guides/decomposition/team_chat_orchestrator.md`](../decomposition/team_chat_orchestrator.md)
  reflete o estado atual.

### PRs vinculados

| PR | Título | Status | Notas |
| --- | --- | --- | --- |
| [#14](https://github.com/levygit837-cyber/PersonAgent/pull/14) | Extract `team_chat/types.py`           | merged | Tipos compartilhados. |
| [#17](https://github.com/levygit837-cyber/PersonAgent/pull/17) | Extract `team_chat/blackboard.py`      | merged | Estado mutável compartilhado entre agentes. |
| [#21](https://github.com/levygit837-cyber/PersonAgent/pull/21) | Extract `team_chat/agent_turn_runner.py` | merged | Loop de turno individual. |
| [#26](https://github.com/levygit837-cyber/PersonAgent/pull/26) | Extract `team_chat/consensus_phase.py` | merged | Fase de consenso/votação. |
| [#27](https://github.com/levygit837-cyber/PersonAgent/pull/27) | Extract `team_chat/coordinator_phase.py` | merged | Fase de coordenação. |
| [#29](https://github.com/levygit837-cyber/PersonAgent/pull/29) | Extract `team_chat/final_synthesis.py` | merged | Síntese final. |

---

## 1.4 — God file decomposition: frontend

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 1.4               |
| Status       | `pending`         |
| Iniciada     | —                 |
| Concluída    | —                 |

### Deliverables

- [ ] `desktop-electron/src/components/chat/session-panel.tsx`
      (3,960 L) decomposto em sub-componentes; playbook em
      `docs/ai-guides/decomposition/session-panel.md` (criar).
- [ ] `desktop-electron/src/stores/chat-store.ts` (3,307 L) fatiado
      em slices Zustand; playbook em
      `docs/ai-guides/decomposition/chat-store.md` (criar).
- [ ] Cobertura vitest dos componentes extraídos mantida ou
      aumentada.

### Critérios de aceitação

- `wc -l session-panel.tsx` ≤ 800.
- `wc -l chat-store.ts` ≤ 1,000.
- Nenhum teste vitest pré-existente quebrou.
- Todos os sub-componentes têm seu próprio `*.test.tsx`.

---

## 1.5 — God file decomposition: `lightpanda.py`

| Chave        | Valor             |
| ------------ | ----------------- |
| Sub-fase     | 1.5               |
| Status       | `pending`         |
| Iniciada     | —                 |
| Concluída    | —                 |

### Deliverables

- [ ] `lightpanda.py` (5,735 L) fatiado conforme playbook em
      `docs/ai-guides/decomposition/lightpanda.md` (criar).
- [ ] `browser_tools.py` (2,786 L) avaliado para sub-decomposição.

### Critérios de aceitação

- `wc -l infrastructure/browser/lightpanda.py` ≤ 1,500.
- Cobertura dos colaboradores ≥ a do arquivo original (medida via
  pytest --cov).

---

## Critérios de aceitação da Fase 1 (consolidados)

Todos os critérios das sub-fases acima devem estar satisfeitos para
mover Fase 1 para `completed`. Resumo:

- Nenhum arquivo Python no backend > 1,500 LoC fora de `tests/`.
- Nenhum arquivo TS/TSX no frontend > 1,500 LoC fora de `*.test.tsx`.
- 100% dos PRs de decomposição com CI verde no merge.
- Todos os playbooks em `docs/ai-guides/decomposition/` refletem o
  estado atual do repo.
- Multi-tenant primitives (1.1) já mergeadas.

## Riscos & mitigações

| Risco                                                                              | Mitigação                                                                                                                                  |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Extração introduz regressão silenciosa de comportamento (ordem de side-effects)    | Review pós-merge obrigatório por slice (modelo do PR #31). Testes que chamam métodos privados removidos devem ser detectados antes do merge. |
| CI gate cobre só `tests/unit/` — regressões em `tests/integration/` passam batidas | `DEC-009`: pinar arquivos específicos no CI (modelo do gate adicionado em PR #31). Auditar gate a cada nova sub-fase.                       |
| `chat/` package vira nova "god folder" (17 arquivos hoje, vai crescer)             | Sub-pacotes (`chat/prompt/`, `chat/memory/`, `chat/tools/`, `chat/streaming/`, `chat/turn/`) propostos. Decidir em sub-fase quando ≥ 20 arquivos. |
| Refator de tipos (Fase 2) começa antes de Fase 1 fechar                            | Fase 2 está `pending` formalmente; bloquear PRs de tipagem em god files até a fatia daquele arquivo estar `completed`.                       |

## Notas operacionais

- O `chat_completion.py` foi a única god file 100% decomposta nesta
  fase. Os demais (team_chat, lightpanda, frontend) estão em
  diferentes estágios — sub-fases 1.3/1.4/1.5 acompanham.
- Aprendizado pós-merge documentado em
  [`/tmp/decomposition-review.md`](#) (relatório de revisão da
  decomposição do chat_completion): 7 falhas pré-existentes
  separadas das 6 introduzidas pela decomposição; lacuna no CI
  identificada e fechada via PR #31.
- A pergunta "criar sub-pacotes em `chat/`?" ficou *adiada*: 17
  arquivos hoje é manejável; voltar à pergunta quando bater 20.
