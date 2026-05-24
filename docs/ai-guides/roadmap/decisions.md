# Decisões arquiteturais travadas (roadmap-level)

Este arquivo guarda decisões **transversais ao roadmap** — coisas que
restringem mais de uma fase e que, se mudarem, invalidam parte do
plano. Decisões pontuais (ex.: "qual adapter usar pra LLM X") ficam
nos ADRs (`docs/adr/`), não aqui.

Formato: `DEC-XXX | Título | Status | Resumo | Phase impact`.

| ID      | Título                                | Status   | Resumo                                                                                                                                              | Phase impact                |
| ------- | ------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| DEC-001 | Não migrar para Go                    | accepted | Manter Python+TS. O ativo do projeto é o **harness do agente** (prompt builder, orchestrator, team mode, RAG); rewrite gasta meses sem destravar produto. | Todas                       |
| DEC-002 | Manter Clean Architecture             | accepted | Domain limpo, ports/adapters. Problemas reais são de execução (god files, `dict[str, Any]`), não de estilo arquitetural. CQRS/Event Sourcing são overkill aqui. | Todas                       |
| DEC-003 | BYOK first, não esconder chaves       | accepted | Cada usuário traz as próprias credenciais de LLM. O backend nunca persiste chaves em claro; ao virar SaaS, criptografia simétrica por tenant.        | Fase 2, Fase 3              |
| DEC-004 | Postgres + pgvector + RLS             | accepted | Sem trocar de DB. `pgvector` resolve RAG sem Pinecone/Weaviate. Row-Level Security (RLS) é o mecanismo de isolamento multi-tenant — não rotear por DB separado por cliente. | Fase 2, Fase 3              |
| DEC-005 | Alembic é a fonte de verdade do schema | accepted | Não usar `create_all` / `ALTER` hardcoded. Toda alteração de schema vira revision em `alembic/versions/`. PR #3 estabeleceu o baseline.            | Fase 0, Fase 2, Fase 3      |
| DEC-006 | Multi-tenant primitives sem RBAC ainda | accepted | Domain (`Conversation.tenant_id`) e schema (`tenants`, `users`) entram em Fase 1. Auth / RBAC / roles ficam para Fase 2.                            | Fase 1, Fase 2              |
| DEC-007 | God-file decomposition antes de tipagem | accepted | Não atacar `dict[str, Any]` (985 ocorrências) enquanto god files (chat_completion 2,742, team_chat 3,097, lightpanda 5,735, session-panel 3,960, chat-store 3,307) existirem — refactor de tipos em arquivo monolítico vira merge hell. | Fase 1 antes de Fase 2      |
| DEC-008 | Local-first hoje, SaaS-ready amanhã  | accepted | App roda 100% local hoje (Electron + backend localhost, ADR-0018 = bearer token local-only). Toda fase 2/3 deve manter o caminho local funcional — SaaS é **adicional**, não substituto. | Fase 2, Fase 3              |
| DEC-009 | CI gate é estrito por arquivo, não por pasta | accepted | Pinar nomes de arquivos na CI (ex.: `pytest tests/test_tools_runtime.py`) em vez de `tests/integration/` inteiro. Fixtures regionais (Postgres, sysprompt_benchmark) não devem entrar no gate. Aprendizado da PR #31. | Todas                       |

## Como adicionar uma decisão nova

1. Sempre que uma fase em execução tomar uma decisão que afeta outra
   fase (ou um padrão de código), crie aqui uma linha `DEC-XXX`.
2. Referencie no `phase-N.md` correspondente em "Decisões aplicáveis".
3. Se a decisão merece um documento de raciocínio completo (mais de
   2 parágrafos), abra um ADR em `docs/adr/` e referencie o ADR aqui.
4. Decisões nunca são removidas — só atualizam status
   (`accepted` → `superseded`) e ganham uma nota explicando o que
   substituiu.

## IDs reservados / futuros

Próximo ID livre: `DEC-010`.
