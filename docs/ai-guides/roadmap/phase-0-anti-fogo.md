# Fase 0 — Anti-fogo

| Chave        | Valor                                                                                 |
| ------------ | ------------------------------------------------------------------------------------- |
| Fase         | 0                                                                                     |
| Status       | `completed`                                                                           |
| Owner        | repo-maintainer                                                                       |
| Iniciada     | 2025-11-23                                                                            |
| Concluída    | 2025-11-23                                                                            |
| Depends on   | —                                                                                     |
| Unblocks     | Fase 1                                                                                |

## Objetivo

Estabelecer **bases não-negociáveis** antes de qualquer trabalho
estrutural: parar os incêndios visíveis (loop infinito de ferramentas
quando `max_tool_iterations` não estava setado, schema gerado por
`create_all`, singleton de estado), e instalar os gates mínimos (CI
no GitHub, pre-commit) pra que o trabalho da Fase 1 nasça já com
proteção.

## Contexto

A análise inicial (sessão `e35857f9...`, 2025-11-23) identificou
quatro riscos que poderiam contaminar qualquer refator subsequente:

1. Loop de ferramentas sem teto explícito quando o request não passa
   `max_tool_iterations` — agente podia consumir tokens
   indefinidamente.
2. Schema do banco criado por `create_all` + `ALTER` hardcoded em
   código — sem Alembic, migrar produção viraria roleta russa.
3. `StateManager` como singleton global — impossibilitava
   multi-tenant e tornava testes acoplados.
4. `.github/workflows/` no `.gitignore` — repo público sem CI
   verificável; qualquer regressão passava despercebida.

Sem fechar esses quatro pontos, Fase 1 (decomposição de god files)
mergeria PRs sem nenhuma rede de proteção.

## Decisões aplicáveis

- `DEC-002` — Manter Clean Architecture (a análise não detectou
  necessidade de mudar de estilo).
- `DEC-005` — Alembic é a fonte de verdade do schema.

## Deliverables

- [x] Loop de ferramentas tem teto enforced: `max_tool_iterations`
      respeitado em ambos os loops do chat completion + safety
      ceiling de 50 quando não setado + ceiling de 25 rounds para
      Team Mode. — PR #2.
- [x] Alembic configurado: revision `0001_baseline` substitui
      `create_all` + `ALTER`s hardcoded. — PR #3.
- [x] `RequestContext` substitui o singleton `StateManager`. — PR #4.
- [x] CI workflow no GitHub + pre-commit + `docker-compose.yml.example`
      checados em (`.github/workflows/ci.yml`, `.pre-commit-config.yaml`).
      README ajustado para refletir o que de fato existe no repo. — PR #5.

## Critérios de aceitação

- CI roda em todo PR e tem três jobs visíveis: `backend`, `desktop`,
  `gitleaks`. Verificável em
  [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml).
- `tests/test_tool_loop_limit.py` cobre as duas branches (config
  presente vs ausente) e está pinado como gate adicional em CI.
- `alembic upgrade head` aplica o schema atual em DB vazio sem
  precisar de `create_all`. Migração `20251123_0000_0001_baseline.py`
  existe no repo.
- Nenhum `StateManager` singleton restante; toda passagem de estado
  é por `RequestContext`. Grep em `application/state/__init__.py` e
  `application/state/request_context.py` confirma.
- `pre-commit install` aplica os hooks declarados em
  `.pre-commit-config.yaml`.

## Riscos & mitigações

| Risco                                                                                          | Mitigação                                                                                                                                        |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Safety ceiling de 50 iterações esconde bug de loop real (agente "funciona" mas consome demais) | Métrica `tool_loop_limit_source` exposta em logs/eventos pra identificar quando o ceiling é o que está cortando, não o config explícito.         |
| Alembic baseline + DB legado existente diverge                                                 | Revision baseline foi escrita a partir do schema real exportado; PR #3 inclui teste `tests/test_alembic_setup.py` que aplica em DB vazio.        |
| CI puxa runtime de minutos toda PR                                                              | Concurrency group cancela runs antigos do mesmo ref; cache de `uv` configurado em `setup-uv@v3`. Runtime atual ~3 min para `backend`.            |

## PRs vinculados

| PR  | Título                                                                                                      | Status  | Notas                                                       |
| --- | ------------------------------------------------------------------------------------------------------------ | ------- | ----------------------------------------------------------- |
| [#2](https://github.com/levygit837-cyber/PersonAgent/pull/2)  | Tool loop limit enforcement                                                  | merged  | +8 testes; nenhum teste pré-existente quebrou.              |
| [#3](https://github.com/levygit837-cyber/PersonAgent/pull/3)  | Alembic baseline revision                                                    | merged  | Substitui `create_all` + ALTERs hardcoded.                  |
| [#4](https://github.com/levygit837-cyber/PersonAgent/pull/4)  | `RequestContext` substitui `StateManager` singleton                          | merged  | Habilita multi-tenant primitives na Fase 1.                 |
| [#5](https://github.com/levygit837-cyber/PersonAgent/pull/5)  | CI workflow + pre-commit + `docker-compose.yml.example` + README ajustado    | merged  | `.github/workflows/` saiu do `.gitignore`.                  |

## Notas operacionais

- Esta fase é **imutável**: edite só typos. Se aparecer um problema
  relacionado a um destes quatro temas, abre uma fase de manutenção
  nova em vez de mexer aqui.
- A análise original (anexo `PersonAgent-analise.md` da sessão
  `e35857f9...`) não está mais acessível via URL pública; o conteúdo
  relevante para Fase 0 foi consolidado neste doc.
