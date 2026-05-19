# AI-Guides: Documentação para Agentes de IA

Este diretório contém documentação estruturada para permitir que agentes de IA naveguem, entendam e modifiquem o código do PersonAgent com precisão cirúrgica.

---

## Estrutura

```
docs/ai-guides/
├── README.md                          # Este arquivo
├── _inventory/
│   ├── backend_symbols.json             # 905 símbolos Python extraídos via AST
│   └── frontend_symbols.json            # 3262 símbolos TypeScript extraídos
├── backend/
│   ├── browser-action-arbiter.md      # Decision engine para ações do browser
│   ├── browser-cooperation.md         # Eventos e redação do browser
│   ├── build-context-use-case.md      # Montagem de contexto para chat
│   ├── command-registry.md            # Sistema de comandos slash
│   ├── dependency-graph.md            # Grafo de dependências entre subsistemas
│   ├── llm-adapters-deep-dive.md     # Detalhes dos 7 adapters LLM
│   ├── memory-jobs.md                 # Scheduler e workers de memória
│   ├── next-step-suggestion.md        # Sugestões pós-turno
│   ├── operational-memory-queue.md    # RabbitMQ adapter para memória
│   ├── qa-indexer-and-redaction.md   # QA tracing e redação
│   ├── session-memory-service.md      # Memória de sessão (filesystem)
│   ├── session-title-service.md       # Geração de títulos via LLM
│   ├── state-manager.md               # Estado global singleton
│   └── tools-schema-cache-and-task-store.md  # Cache de schemas e persistência de tasks
├── decisions/
│   ├── add-llm-provider.md            # Como adicionar provider LLM
│   ├── add-slash-command.md           # Como adicionar comando /
│   ├── add-sse-event.md               # Como adicionar evento SSE
│   ├── add-tool.md                    # Como adicionar ferramenta
│   ├── modify-browser-security.md     # Como ajustar segurança do browser
│   ├── modify-memory-chunking.md      # Como mudar chunking de memória
│   ├── modify-prompt.md               # Como modificar prompt
│   └── modify-retry.md                # Como ajustar retry policy
└── scripts/
    ├── extract_backend_symbols.py     # Script de inventário Python
    └── extract_frontend_symbols.py   # Script de inventário TypeScript
```

---

## Convenções de Referência

Toda referência de código segue o formato:
```
`ClassName.method_name` @ `file_path:line`
```

Para classes:
```
`ClassName` @ `file_path:line`
```

Para constantes:
```
`CONSTANT_NAME` @ `file_path:line`
```

Para funções de módulo:
```
`function_name()` @ `file_path:line`
```

---

## Como Navegar

### Quero entender um subsistema específico
→ Leia o guide em `backend/<subsistema>.md`

### Quero saber o impacto de uma mudança
→ Leia `backend/dependency-graph.md`

### Quero implementar uma mudança comum
→ Leia `decisions/<tipo-de-mudança>.md`

### Quero encontrar onde uma função/classe está definida
→ Busque em `_inventory/backend_symbols.json` ou `_inventory/frontend_symbols.json`

---

## Glossário

| Termo | Significado |
|-------|-------------|
| **ADR** | Architecture Decision Record |
| **DI** | Dependency Injection |
| **LLM** | Large Language Model |
| **RAG** | Retrieval Augmented Generation |
| **SSE** | Server-Sent Events |
| **CDP** | Chrome DevTools Protocol |
| **ORM** | Object-Relational Mapping |
| **QA** | Quality Assurance (tracing subsystem) |
| **MCP** | Model Context Protocol |
| **LSP** | Language Server Protocol |

---

## Inventário

### Backend (Python)
- **Arquivos parseados**: Todos os `.py` em `@backend/src/personagent/`
- **Símbolos extraídos**: 905 (classes, funções, métodos, constantes)
- **Cobertura**: Exclui arquivos de teste

### Frontend (TypeScript)
- **Arquivos parseados**: Todos os `.ts` e `.tsx` em `@desktop-electron/src/`
- **Símbolos extraídos**: 3262 (interfaces, types, funções, classes, consts)
- **Cobertura**: Exclui arquivos de teste

---

## Manutenção

Para regenerar o inventário após mudanças de código:
```bash
python3 docs/ai-guides/scripts/extract_backend_symbols.py
python3 docs/ai-guides/scripts/extract_frontend_symbols.py
```

Para validar que referências de linha ainda existem:
```bash
# (TODO: implementar script de validação)
```

---

## Subsistemas Documentados

### Backend (13 guides)
1. Browser Action Arbiter — segurança de ações no browser
2. Browser Cooperation — eventos e redação
3. Build Context Use Case — montagem de contexto
4. Command Registry — comandos slash
5. LLM Adapters — 7 adapters de provider
6. Memory Jobs — scheduler e workers
7. Next-Step Suggestion — sugestões pós-turno
8. Operational Memory Queue — RabbitMQ adapter
9. QA Indexer and Redaction — tracing e redação
10. Session Memory Service — memória de sessão
11. Session Title Service — títulos de conversa
12. State Manager — estado global
13. Tools Schema Cache and Task Store — cache e persistência

### Decision Trees (8 guides)
1. Adicionar LLM provider
2. Adicionar ferramenta
3. Adicionar comando slash
4. Adicionar evento SSE
5. Modificar prompt
6. Modificar segurança do browser
7. Modificar retry policy
8. Modificar chunking de memória

---

## Docs Humanas Relacionadas

- `docs/adr/` — Architecture Decision Records (0001-0021)
- `docs/backend/` — Documentação operacional do backend
- `docs/app/` — Documentação operacional da aplicação
- `docs/operations/` — Operações e diagnósticos
