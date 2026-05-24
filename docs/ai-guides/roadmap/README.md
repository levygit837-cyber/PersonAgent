# Roadmap auditável do PersonAgent

Este diretório guarda o roadmap **auditável** do projeto: cada fase
tem critérios de aceitação testáveis, PRs vinculados e checkboxes que
um revisor pode marcar olhando o repo, sem precisar de contexto da
sessão que executou.

**Não é um plano de marketing.** É a fonte de verdade que orienta os
próximos agentes (humanos ou Devin) sobre o que está feito, o que
está aberto e o que vem em seguida.

## Como usar

1. **Antes de começar trabalho novo**, leia o `phase-N.md` que cobre
   o seu objetivo. Se a fase estiver `pending`, ela ainda não foi
   iniciada — só comece se for o "Owner" registrado no header da
   fase ou se tiver autorização explícita.
2. **Durante o trabalho**, marque deliverables conforme PRs vão
   mergeando. Atualize a tabela "PRs vinculados".
3. **Ao final da fase**, se *todos* os deliverables estiverem marcados
   e todos os PRs estiverem `merged`, mude o status para `completed`
   e preencha a data em `Concluída`.

## Regras de auditoria

Lidas integralmente em `_format.md`. Resumo:

- Status reflete realidade. Nenhum `completed` com checkbox aberto.
- Sem expansão retroativa de escopo: novidades viram fase nova.
- Cada deliverable é um artefato observável de fora (PR, teste,
  métrica, doc).
- Fases são independentes: o repo deve rodar end-to-end com a fase N
  fechada, sem precisar da fase N+1.

## Índice de fases

| Fase | Título                                                    | Status         | Iniciada     | Concluída    |
| ---- | --------------------------------------------------------- | -------------- | ------------ | ------------ |
| 0    | [Anti-fogo](./phase-0-anti-fogo.md)                       | `completed`    | 2025-11-23   | 2025-11-23   |
| 1    | [Hardening estrutural](./phase-1-hardening-estrutural.md) | `in_progress`  | 2025-11-23   | —            |
| 2    | [Tipagem & contratos](./phase-2-tipagem-contratos.md)     | `pending`      | —            | —            |
| 3    | [Escala & produto](./phase-3-escala-produto.md)           | `pending`      | —            | —            |

## Decisões transversais

Restrições que afetam mais de uma fase vivem em
[`decisions.md`](./decisions.md). Toda fase referencia as decisões
aplicáveis pelo ID (`DEC-XXX`) — não duplique o raciocínio aqui.

## Documentos relacionados

- [`docs/ai-guides/decomposition/`](../decomposition/) — playbooks
  detalhados de extração para god files (alvo da Fase 1).
- [`docs/adr/`](../../adr/) — decisões pontuais (provider LLM novo,
  política de auth, schema de migração). ADRs **complementam** o
  roadmap; o roadmap referencia ADRs por número.
- [`docs/backend/`](../backend/) — guias de arquitetura específicos
  de subsistema (memória, browser, sessão, etc.).

## Histórico do roadmap

- 2025-11-23 — Roadmap criado (re-construção pós-perda da branch
  `devin/1779584356-auditable-roadmap` que tinha 3 docs nunca
  pushados). Fases 0 e 1 documentadas a partir dos PRs já mergeados
  no `main`. Fases 2 e 3 propostas a partir de re-análise do repo
  feita em 2025-11-23.
