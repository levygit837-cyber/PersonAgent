# Análise Completa: Sistema de Memórias do Claude Code vs PersonAgent

## 1. Análise de Memória do Claude Code

O Claude Code implementa um sistema de memória sofisticado e multicamadas. Abaixo está a análise completa de todos os seus componentes.

### 1.1 Taxonomia de Memórias

O Claude Code possui **5 sistemas de memória distintos**, operando em diferentes camadas de escopo e persistência:

| Sistema | Escopo | Persistência | Formato | Propósito |
|---------|--------|--------------|---------|-----------|
| **Managed Memory** | Global/Organização | Sistema de arquivos (`/etc/claude-code/`) | MD + rules | Instruções corporativas |
| **User Memory** | Usuário global | Sistema de arquivos (`~/.claude/`) | MD + rules | Instruções pessoais cross-project |
| **Project Memory** | Projeto | Sistema de arquivos (repo + `.claude/rules/`) | MD + rules | Instruções versionadas do projeto |
| **Local Memory** | Projeto + Máquina | Sistema de arquivos (`CLAUDE.local.md`) | MD | Instruções privadas não versionadas |
| **Auto Memory (MemDir)** | Conversação → Longo prazo | Sistema de arquivos (`~/.claude/projects/<slug>/memory/`) | MD com frontmatter | Aprendizado contínuo da sessão |
| **Team Memory** | Time/Organização | Sistema de arquivos (subdiretório do auto-mem) | MD com frontmatter | Memórias compartilhadas entre usuários |
| **Agent Memory** | Agente específico | Sistema de arquivos (`~/.claude/agent-memory/` ou `.claude/agent-memory/`) | MD com frontmatter | Memória persistente por tipo de agente |
| **Session Context** | Conversação atual | Memória RAM/transcript | JSONL + mensagens | Contexto da conversa ativa |

### 1.2 Sistema CLAUDE.md / Persona.md (Memória Estática)

Este é o sistema de **instruções estáticas** - arquivos MD escritos manualmente pelo usuário ou organização.

#### Hierarquia de Prioridade (do mais antigo para o mais recente):
1. **Managed** (`/etc/claude-code/CLAUDE.md`) - Políticas organizacionais
2. **User** (`~/.claude/CLAUDE.md`) - Preferências globais do usuário
3. **Project** (`CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*.md`) - Regras do projeto
4. **Local** (`CLAUDE.local.md`) - Regras privadas locais

#### Recursos avançados:
- **`@include`**: Diretiva para incluir outros arquivos via `@path`, `@./path`, `@~/path`, `@/absolute/path`
- **Frontmatter `paths`**: Suporta regras condicionais com glob patterns (ex: `paths: src/**/*.py` para aplicar regras apenas a arquivos Python)
- **HTML comment stripping**: Comentários `<!-- -->` são removidos automaticamente
- **Truncamento inteligente**: MEMORY.md é truncado em 200 linhas / 25KB
- **Deduplicação**: Arquivos já processados são rastreados por `processedPaths`
- **Symlink resolution**: Caminhos são resolvidos via `realpath` para segurança

#### Schema do MemoryFile (TypeScript):
```typescript
type MemoryFileInfo = {
  path: string
  type: 'Managed' | 'User' | 'Project' | 'Local' | 'AutoMem' | 'TeamMem'
  content: string
  parent?: string        // Path do arquivo que incluiu este via @include
  globs?: string[]       // Padrões glob do frontmatter (para regras condicionais)
  contentDiffersFromDisk?: boolean  // Se foi truncado/stripado
  rawContent?: string    // Conteúdo original do disco
}
```

### 1.3 Sistema Auto Memory / MemDir (Memória Dinâmica)

Este é o sistema de **memória de longo prazo automático** - a grande inovação do Claude Code.

#### Tipos de Memória (Taxonomia de 4 tipos):
```typescript
type MemoryType = 'user' | 'feedback' | 'project' | 'reference'
```

- **`user`**: Informações sobre o usuário (role, preferências, conhecimentos) - **sempre privado**
- **`feedback`**: Orientações de como trabalhar (o que evitar/repetir) - **default privado, pode ser team**
- **`project`**: Trabalho em andamento, bugs, incidentes, decisões - **bias para team**
- **`reference`**: Ponteiros para sistemas externos (Linear, Grafana, Slack) - **geralmente team**

#### Estrutura de arquivos:
```
~/.claude/projects/<sanitized-git-root>/memory/
├── MEMORY.md              # Índice/entrypoint (máx 200 linhas, 25KB)
├── user_role.md           # Memórias individuais
├── feedback_testing.md
├── project_auth_rewrite.md
├── reference_dashboards.md
└── logs/
    └── 2026/
        └── 04/
            └── 2026-04-27.md   # Logs diários (modo KAIROS/assistant)
```

#### Frontmatter Schema:
```markdown
---
name: {{memory name}}
description: {{one-line description — usado para decidir relevância}}
type: {{user | feedback | project | reference}}
---
{{memory content}}
```

#### Fluxo de criação de memórias:
1. **Escrita pelo agente principal**: Durante a conversa, quando o usuário pede "lembre-se disso" ou o agente detecta informação valiosa
2. **Extração automática (background)**: A cada turno completo, um **forked agent** analisa as mensagens recentes e extrai memórias duráveis
3. **Daily logs (modo KAIROS)**: Em sessões longas (assistant mode), memórias são append-only em arquivos diários
4. **Consolidação (auto-dream)**: Processo noturno que distila logs diários em arquivos tópicos + atualiza MEMORY.md

#### Mecanismo de extração automática (`extractMemories`):
- **Trigger**: Fim de cada query loop (quando o modelo produz resposta final sem tool calls)
- **Agente**: Forked agent (cópia perfeita da conversa pai, compartilhando prompt cache)
- **Ferramentas permitidas**: Read, Grep, Glob, Bash read-only, Edit/Write apenas dentro do memory dir
- **Throttle**: A cada N turnos elegíveis (configurável via GrowthBook)
- **Mutual exclusion**: Se o agente principal já escreveu memórias, o extrator pula
- **Budget**: Máximo 5 turns por extração
- **Surfacing**: Após extração, uma mensagem de sistema "Saved N memories" é injetada

#### Mecanismo de recall (`findRelevantMemories`):
- **Trigger**: Antes de cada query do usuário
- **Processo**:
  1. Scan dos arquivos .md no memdir (max 200 arquivos, ordenados por mtime)
  2. Leitura do frontmatter de cada arquivo
  3. Chamada ao modelo Sonnet para selecionar até 5 memórias mais relevantes à query
  4. Leitura do conteúdo completo das memórias selecionadas
  5. Injeção como `attachment` do tipo `relevant_memories` na mensagem do usuário
- **Deduplicação**: Memórias já surfacadas em turns anteriores são filtradas
- **Freshness**: Memórias >1 dia incluem caveat de staleness

#### Mecanismo de consolidação (`autoDream`):
- **Trigger**: Tempo (mín 24h desde última consolidação) + Sessões (mín 5 sessões novas)
- **Processo**: Forked agent lê logs/transcripts de sessões anteriores e reorganiza em tópicos
- **Lock file**: Previne execuções concorrentes
- **Rollback**: Em caso de falha, o lock é revertido para re-tentar

### 1.4 Sistema Team Memory

Extensão do auto-mem para compartilhamento entre usuários de um mesmo projeto.

#### Estrutura:
```
~/.claude/projects/<slug>/memory/
├── MEMORY.md              # Memórias privadas
├── user_role.md
└── team/
    ├── MEMORY.md          # Memórias compartilhadas
    └── project_standards.md
```

#### Características:
- **Scope guidance**: Cada tipo de memória indica se deve ser `private` ou `team`
- **Segurança**: Validação rigorosa de path traversal + symlink resolution (`realpathDeepestExisting`)
- **Sync**: Sincronizado no início de cada sessão
- **Prompt combinado**: Quando habilitado, o prompt de memória inclui ambos os diretórios

### 1.5 Sistema Agent Memory

Memória persistente por tipo de agente (explore, plan, coder, etc.).

#### Escopos:
- **`user`**: `~/.claude/agent-memory/<agentType>/` - Cross-project
- **`project`**: `.claude/agent-memory/<agentType>/` - Versionado com o projeto
- **`local`**: `.claude/agent-memory-local/<agentType>/` - Privado por máquina

#### Uso:
- Quando um agente é spawnado com `memory: 'user'|'project'|'local'`, seu system prompt inclui o conteúdo do MEMORY.md correspondente
- O agente pode ler e escrever em seu próprio memory dir
- Isolamento: Agente A não vê memórias do Agente B

### 1.6 Ciclo de Vida das Memórias

```
┌─────────────────────────────────────────────────────────────────┐
│                        CONVERSAÇÃO                              │
│  Usuário fala → Agent responde → (loop)                         │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────┐                                    │
│  │ findRelevantMemories    │ ← Scan + Sonnet selection          │
│  │ (antes da query)        │    Injeta memórias relevantes      │
│  └─────────────────────────┘                                    │
│       │                                                         │
│       ▼                                                         │
│  Agent processa com contexto (memórias no system prompt)        │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────┐     ┌──────────────────────────┐   │
│  │ extractMemories         │ OR  │ Usuário pede             │   │
│  │ (background fork)       │     │ "lembre-se disso"        │   │
│  └─────────────────────────┘     └──────────────────────────┘   │
│       │                              │                          │
│       ▼                              ▼                          │
│  ┌─────────────────────────────────────────┐                    │
│  │         ESCRITA EM .md FILES            │                    │
│  │  ~/.claude/projects/<slug>/memory/      │                    │
│  └─────────────────────────────────────────┘                    │
│       │                                                         │
│       ▼ (a cada N horas/sessões)                                │
│  ┌─────────────────────────┐                                    │
│  │ autoDream (consolidação)│ ← Reorganiza, remove duplicatas   │
│  └─────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 1.7 Contratos e APIs

#### Path Resolution (memdir/paths.ts):
```typescript
getMemoryBaseDir(): string        // ~/.claude ou CLAUDE_CODE_REMOTE_MEMORY_DIR
getAutoMemPath(): string          // ~/.claude/projects/<slug>/memory/
getAutoMemEntrypoint(): string    // .../memory/MEMORY.md
getAutoMemDailyLogPath(date): string  // .../memory/logs/YYYY/MM/YYYY-MM-DD.md
isAutoMemPath(absolutePath): boolean  // Verifica se path está dentro do memdir
```

#### Feature Gates:
- `tengu_passport_quail`: Habilita extractMemories
- `tengu_herring_clock`: Habilita team memory
- `tengu_onyx_plover`: Configura autoDream (minHours, minSessions)
- `tengu_moth_copse`: Skip index - não injeta MEMORY.md no system prompt, usa apenas prefetch
- `tengu_coral_fern`: Habilita "Searching past context" (grep em transcripts)
- `tengu_bramble_lintel`: Throttle de extração (a cada N turns)

#### Telemetry Events:
- `tengu_memdir_loaded`: Quando memória é carregada
- `tengu_extract_memories_extraction`: Métricas da extração
- `tengu_auto_dream_fired/completed/failed`: Ciclo de consolidação
- `tengu_claudemd__initial_load`: Carregamento inicial de CLAUDE.md

---

## 2. PersonAgent Memory - Estado Atual

### 2.1 Sistemas Existentes

O PersonAgent possui atualmente **2 sistemas de memória**:

#### A. Session Memory (`SessionMemoryService`)
- **Localização**: `~/.personagent/session-memory/<conversation_id>.md`
- **Propósito**: Manter um resumo da conversa atual para contexto
- **Mecanismo**: 
  - A cada interação, o LLM recebe o memory atual + últimas 12 mensagens e gera um novo memory consolidado
  - Template padrão: `SESSION_MEMORY_TEMPLATE`
  - Prompt de update: `SESSION_MEMORY_UPDATE_PROMPT`
- **Persistência**: Arquivo MD por conversation_id
- **Limitação**: **Apenas memória de sessão** - não há cross-session learning

#### B. Persona.md Loader (`PersonaMdLoader`)
- **Localização**: `personagent/domain/context/services/personamd_loader.py`
- **Propósito**: Carregar instruções estáticas do projeto/usuário
- **Hierarquia**:
  1. Managed (`/etc/claude-code/persona.md`)
  2. User (`~/.claude/persona.md`)
  3. Project (`persona.md`, `CLAUDE.md`, `.claude/*.md`, `.claude/rules/*.md`)
  4. Local (`persona.local.md`)
- **Recursos**: Suporte a `@include`, limitação de 50KB por arquivo
- **Limitação**: **Apenas leitura estática** - não há escrita automática ou aprendizado

### 2.2 Contexto de Conversa

O `ContextBuilder` monta:
- **SystemContext**: Git status, branch, environment variables
- **UserContext**: Persona.md combinado + data atual + user settings

O `BuildContextUseCase` orquestra a montagem e cache via `ContextRepository` (in-memory atualmente).

---

## 3. Proposta de Integração no PersonAgent

### 3.1 Sistemas a Preservar do Claude Code

**Todos os 5 sistemas de memória do Claude Code podem e devem ser adaptados.** Abaixo a prioridade de implementação:

| Prioridade | Sistema | Complexidade | Valor |
|------------|---------|--------------|-------|
| P0 | **Auto Memory (MemDir)** | Alta | Máximo - Este é o diferencial |
| P0 | **Relevant Memory Recall** | Média | Máximo - Recall inteligente |
| P1 | **Agent Memory** | Média | Alto - Para agents especializados |
| P1 | **AutoDream (Consolidação)** | Alta | Alto - Manutenção da memória |
| P2 | **Team Memory** | Média | Médio - Para uso em equipe |
| P2 | **Daily Logs (KAIROS mode)** | Baixa | Médio - Para sessões longas |

### 3.2 Arquitetura Proposta

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PERSONAGENT MEMORY SYSTEM                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    PRESENTATION LAYER (API/WebSocket)                │   │
│  │  /memory/* endpoints  │  MemoryCommand (/memory)  │  UI Components   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    APPLICATION LAYER (Use Cases)                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │   │
│  │  │BuildContext  │  │ExtractMemory │  │RecallMemory  │  │Consolidate│ │   │
│  │  │UseCase       │  │UseCase       │  │UseCase       │  │Memory    │ │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────┘ │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ManageMemory  │  │SyncTeamMemory│  │SearchTranscript│            │   │
│  │  │UseCase       │  │UseCase       │  │UseCase         │            │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    DOMAIN LAYER (Services + Entities)                │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │ContextBuilder   │  │MemoryExtractor  │  │MemoryRecallSelector │  │   │
│  │  │(refatorado)     │  │Service          │  │Service              │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │MemoryWriter     │  │MemoryConsolidator│  │TranscriptSearcher  │  │   │
│  │  │Service          │  │Service          │  │Service              │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │PersonaMdLoader  │  │AgentMemoryLoader│  │TeamMemorySync       │  │   │
│  │  │(existente)      │  │Service          │  │Service              │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  │                                                                      │   │
│  │  ENTITIES:                                                           │   │
│  │  - MemoryFile (path, type, content, frontmatter, mtime)             │   │
│  │  - MemoryHeader (filename, description, type, mtime)                │   │
│  │  - MemoryIndex (entrypoint MEMORY.md)                               │   │
│  │  - MemoryType (USER, FEEDBACK, PROJECT, REFERENCE)                  │   │
│  │  - MemoryScope (PRIVATE, TEAM, PROJECT, USER, LOCAL)                │   │
│  │  - RelevantMemory (path, content, mtime, relevance_score)           │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              INFRASTRUCTURE LAYER (Repositories + Adapters)          │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │FileSystemMemory │  │FileSystemContext│  │InMemoryContext      │  │   │
│  │  │Repository       │  │Repository       │  │Repository           │  │   │
│  │  │(memdir)         │  │(cache)          │  │(existente)          │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │LLMBackendAdapter│  │ConversationRepo │  │TranscriptRepository │  │   │
│  │  │(Sonnet/Claude)  │  │(PostgreSQL)     │  │(JSONL/logs)         │  │   │
│  │  │para recall      │  │                 │  │                     │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Estrutura de Diretórios Proposta (Backend)

```
@backend/src/personagent/
├── domain/
│   ├── memory/
│   │   ├── models/
│   │   │   ├── memory_file.py          # MemoryFile, MemoryHeader
│   │   │   ├── memory_types.py         # MemoryType, MemoryScope enums
│   │   │   ├── memory_index.py         # MemoryIndex (MEMORY.md)
│   │   │   └── relevant_memory.py      # RelevantMemory com score
│   │   ├── repositories/
│   │   │   ├── memory_repository.py    # Interface: read, write, scan, delete
│   │   │   └── transcript_repository.py # Interface: listar sessões, ler logs
│   │   └── services/
│   │       ├── memory_scanner.py       # Scan de diretório + parse frontmatter
│   │       ├── memory_recall_selector.py # Seleção via LLM (sideQuery)
│   │       ├── memory_extractor.py     # Extração automática de memórias
│   │       ├── memory_consolidator.py  # AutoDream / consolidação
│   │       └── memory_age_tracker.py   # Cálculo de idade/staleness
│   └── context/                        # (existente, refatorado)
│       ├── ...
│       └── services/
│           └── context_builder.py      # Integra memória no contexto
│
├── application/
│   ├── services/
│   │   ├── session_memory.py           # (existente - mantém)
│   │   └── memory_manager.py           # Orquestração de memória
│   └── use_cases/
│       ├── memory/
│       │   ├── extract_memory.py       # Trigger de extração
│       │   ├── recall_memory.py        # Busca relevante
│       │   ├── write_memory.py         # Escrita manual
│       │   ├── consolidate_memory.py   # Trigger do dream
│       │   └── manage_memory_files.py  # CRUD de arquivos
│       └── context/
│           └── build_context.py        # (existente, estendido)
│
└── infrastructure/
    ├── persistence/
    │   ├── memory/
    │   │   └── filesystem_memory_repository.py  # Implementação fs
    │   ├── transcript/
    │   │   └── filesystem_transcript_repository.py # Logs JSONL
    │   └── context/
    │       └── in_memory_context_repository.py  # (existente)
    └── llm/
        └── memory_llm_adapter.py       # Adapter para chamadas LLM de memória
```

### 3.4 Fluxo de Dados Proposto

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FLUXO DE MEMÓRIA                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. CONVERSAÇÃO INICIA                                                      │
│     │                                                                       │
│     ▼                                                                       │
│  ┌─────────────────────┐                                                    │
│  │ BuildContextUseCase │                                                    │
│  │                     │                                                    │
│  │ 1. Carrega persona.md (PersonaMdLoader) → UserContext                    │
│  │ 2. Carrega MEMORY.md (MemoryRepository) → UserContext                    │
│  │ 3. Carrega git context → SystemContext                                   │
│  │ 4. CACHE no ContextRepository                                            │
│  └─────────────────────┘                                                    │
│     │                                                                       │
│     ▼                                                                       │
│  2. USUÁRIO ENVIA MENSAGEM                                                  │
│     │                                                                       │
│     ▼                                                                       │
│  ┌─────────────────────────┐                                                │
│  │ RecallMemoryUseCase     │                                                │
│  │                         │                                                │
│  │ 1. scanMemoryFiles() → lista headers                                     │
│  │ 2. LLM selectRelevantMemories(query, headers) → até 5 filenames          │
│  │ 3. readMemoriesForSurfacing() → conteúdo completo                        │
│  │ 4. INJETA como attachment relevant_memories na mensagem                  │
│  └─────────────────────────┘                                                │
│     │                                                                       │
│     ▼                                                                       │
│  3. AGENTE PROCESSA COM CONTEXTO ENRIQUECIDO                                │
│     │                                                                       │
│     ▼                                                                       │
│  4. FIM DO TURN (resposta final, sem tool calls)                            │
│     │                                                                       │
│     ▼                                                                       │
│  ┌─────────────────────────┐                                                │
│  │ ExtractMemoryUseCase    │                                                │
│  │ (background, async)     │                                                │
│  │                         │                                                │
│  │ 1. Coleta mensagens desde última extração                                │
│  │ 2. Se agente principal escreveu memória → SKIP                           │
│  │ 3. LLM analyzeMessages() → identifica memórias duráveis                  │
│  │ 4. Write/Edit nos arquivos .md do memdir                                 │
│  │ 5. Atualiza MEMORY.md (índice)                                           │
│  │ 6. NOTIFICA via system message "Saved N memories"                        │
│  └─────────────────────────┘                                                │
│     │                                                                       │
│     ▼ (diariamente / a cada N sessões)                                      │
│  ┌─────────────────────────┐                                                │
│  │ ConsolidateMemoryUseCase│                                                │
│  │ (autoDream)             │                                                │
│  │                         │                                                │
│  │ 1. Verifica time-gate (24h) + session-gate (5 sessões)                   │
│  │ 2. Lista sessões desde última consolidação                               │
│  │ 3. Acquire lock                                                          │
│  │ 4. LLM lê logs/transcripts → reorganiza em tópicos                       │
│  │ 5. Atualiza/remove/merge arquivos                                        │
│  │ 6. Release lock                                                          │
│  └─────────────────────────┘                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.5 Infraestrutura Necessária

#### A. Sistema de Arquivos (já existe - apenas estruturar)
```
~/.personagent/
├── session-memory/              # (existente)
│   └── <conversation_id>.md
├── projects/
│   └── <workspace-slug>/
│       ├── memory/              # NOVO: Auto memory
│       │   ├── MEMORY.md
│       │   ├── user_role.md
│       │   ├── feedback_*.md
│       │   ├── project_*.md
│       │   ├── reference_*.md
│       │   └── logs/
│       │       └── YYYY/MM/YYYY-MM-DD.md
│       └── team/                # NOVO: Team memory (opcional)
│           └── MEMORY.md
├── agent-memory/                # NOVO: Agent memory (user scope)
│   └── <agent-type>/
│       └── MEMORY.md
└── context-cache/               # (existente - in-memory)
```

#### B. Banco de Dados (PostgreSQL já existe)
Tabelas sugeridas:
```sql
-- Metadados de memória (para queries rápidas sem scan de fs)
CREATE TABLE memory_files (
    id UUID PRIMARY KEY,
    conversation_id UUID,
    project_slug TEXT NOT NULL,
    file_path TEXT NOT NULL,
    memory_type TEXT CHECK (memory_type IN ('user', 'feedback', 'project', 'reference')),
    scope TEXT CHECK (scope IN ('private', 'team', 'project', 'user', 'local')),
    description TEXT,
    content_hash TEXT,
    mtime TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índice de sessões para autoDream
CREATE TABLE session_logs (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_slug TEXT,
    conversation_id UUID,
    message_count INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Locks de consolidação
CREATE TABLE consolidation_locks (
    project_slug TEXT PRIMARY KEY,
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    last_consolidated_at TIMESTAMPTZ
);
```

#### C. Serviços LLM (já existe - apenas extender)
- **Adapter para "sideQuery"**: Chamadas rápidas ao LLM (Sonnet) para seleção de memórias relevantes
- **Adapter para "extractMemories"**: Chamadas ao LLM para análise de transcript
- **Adapter para "consolidation"**: Chamadas ao LLM para reorganização de memórias

#### D. Background Task Runner (NOVO)
Necessário para executar:
- `extractMemories` após cada turn
- `autoDream` periodicamente
- `teamMemorySync` no início da sessão

Opções:
1. **Celery + Redis/RabbitMQ**: Mais robusto, escalável
2. **asyncio background tasks**: Mais simples, adequado para MVP
3. **APScheduler**: Scheduler em Python puro

#### E. Cache Layer (estender existente)
- `ContextRepository` já existe (in-memory)
- Adicionar cache de:
  - `MemoryFile` scan results (memoize por project_slug)
  - `RelevantMemory` selections (curto prazo, por query)
  - `MemoryIndex` (MEMORY.md content)

### 3.6 Mapeamento de Componentes Claude Code → PersonAgent

| Componente Claude Code | Componente PersonAgent Proposto | Status |
|------------------------|--------------------------------|--------|
| `memdir/memoryTypes.ts` | `domain/memory/models/memory_types.py` | Novo |
| `memdir/memdir.ts` | `domain/memory/services/memory_scanner.py` | Novo |
| `memdir/paths.ts` | `infrastructure/persistence/memory/filesystem_memory_repository.py` | Novo |
| `memdir/findRelevantMemories.ts` | `domain/memory/services/memory_recall_selector.py` | Novo |
| `memdir/memoryScan.ts` | `domain/memory/services/memory_scanner.py` | Novo |
| `memdir/memoryAge.ts` | `domain/memory/services/memory_age_tracker.py` | Novo |
| `services/extractMemories/extractMemories.ts` | `application/use_cases/memory/extract_memory.py` | Novo |
| `services/extractMemories/prompts.ts` | `domain/prompts/memory_extraction_prompts.py` | Novo |
| `services/autoDream/autoDream.ts` | `application/use_cases/memory/consolidate_memory.py` | Novo |
| `utils/claudemd.ts` | `domain/context/services/context_builder.py` | Refatorar |
| `PersonaMdLoader` | `domain/context/services/personamd_loader.py` | Manter/estender |
| `SessionMemoryService` | `application/services/session_memory.py` | Manter |
| `ContextBuilder` | `domain/context/services/context_builder.py` | Refatorar |
| `ContextRepository` | `domain/context/repositories/context_repository.py` | Manter |
| `InMemoryContextRepository` | `infrastructure/persistence/context/in_memory_context_repository.py` | Manter |
| `tools/AgentTool/agentMemory.ts` | `domain/memory/services/agent_memory_loader.py` | Novo |

### 3.7 Schema de Dados Proposto

```python
# domain/memory/models/memory_types.py

from enum import Enum, auto
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Optional

class MemoryType(str, Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"

class MemoryScope(str, Enum):
    PRIVATE = "private"
    TEAM = "team"
    PROJECT = "project"
    USER = "user"
    LOCAL = "local"

@dataclass(frozen=True)
class MemoryHeader:
    """Cabeçalho de um arquivo de memória (metadados do frontmatter)."""
    filename: str
    file_path: Path
    mtime_ms: int
    description: Optional[str]
    memory_type: Optional[MemoryType]
    scope: MemoryScope = MemoryScope.PRIVATE

@dataclass
class MemoryFile:
    """Arquivo de memória completo."""
    path: Path
    memory_type: MemoryType
    content: str
    frontmatter: dict
    globs: Optional[list[str]] = None
    mtime_ms: int = 0

@dataclass
class RelevantMemory:
    """Memória selecionada como relevante para uma query."""
    path: str
    content: str
    mtime_ms: int
    header: str  # "saved X days ago"
    relevance_score: float = 0.0
    limit: Optional[int] = None  # Se truncado

@dataclass
class MemoryIndex:
    """Índice MEMORY.md de um diretório de memória."""
    entrypoint_path: Path
    content: str
    line_count: int
    was_truncated: bool = False
```

### 3.8 Prompts de Sistema (adaptados do Claude Code)

Os prompts de memória do Claude Code (`buildMemoryLines`, `buildExtractAutoOnlyPrompt`, `buildConsolidationPrompt`) devem ser adaptados para o formato do PersonAgent. Os prompts originais usam XML tags e instruções específicas que podem ser preservadas.

#### Prompt de Memória no System Context:
```markdown
# Auto Memory

You have a persistent, file-based memory system at `~/.personagent/projects/<slug>/memory/`.

You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, what behaviors to avoid or repeat, and the context behind the work the user gives you.

## Types of memory
[user, feedback, project, reference - same as Claude Code]

## What NOT to save in memory
[same exclusions as Claude Code]

## How to save memories
Saving a memory is a two-step process:
**Step 1** — write the memory to its own file using frontmatter format
**Step 2** — add a pointer to that file in `MEMORY.md`

## When to access memories
[same guidance as Claude Code]

## Before recommending from memory
[same staleness verification as Claude Code]
```

### 3.9 Considerações de Segurança (do Claude Code)

Devem ser preservadas:
- **Path traversal validation**: `validateMemoryPath` - rejeita paths relativos, root, UNC, null bytes
- **Symlink resolution**: `realpathDeepestExisting` - resolve symlinks antes de validar containment
- **Write carve-out**: Ferramentas de escrita só podem escrever no memdir (não em paths arbitrários)
- **Sensitive data exclusion**: Team memory nunca deve conter API keys ou credenciais
- **Settings.json security**: `autoMemoryDirectory` só aceita de sources confiáveis (exclui projectSettings)

### 3.10 Feature Flags Propostas

```python
# infrastructure/config/settings.py

class MemorySettings:
    auto_memory_enabled: bool = True
    auto_memory_directory: Optional[Path] = None  # Override
    extract_memories_enabled: bool = True
    extract_memories_throttle_turns: int = 1
    auto_dream_enabled: bool = True
    auto_dream_min_hours: int = 24
    auto_dream_min_sessions: int = 5
    team_memory_enabled: bool = False
    kairos_mode_enabled: bool = False  # Daily logs instead of MEMORY.md index
    memory_recall_enabled: bool = True
    memory_max_files: int = 200
    memory_max_lines_per_file: int = 200
    memory_max_bytes_per_file: int = 25_000
```

### 3.11 Roadmap de Implementação Sugerido

#### Fase 1: Fundação (Semanas 1-2)
- [ ] Criar estrutura de diretórios do domínio de memória
- [ ] Implementar `MemoryFile`, `MemoryHeader`, `MemoryType` models
- [ ] Implementar `FileSystemMemoryRepository` (scan, read, write)
- [ ] Adaptar `ContextBuilder` para carregar MEMORY.md
- [ ] Adicionar MEMORY.md ao `UserContext`

#### Fase 2: Memória Manual (Semana 3)
- [ ] Permitir que o agente escreva memórias via tool calls
- [ ] Implementar validação de paths e segurança
- [ ] Criar comando `/memory` para gerenciamento manual
- [ ] UI para visualização/edição de memórias

#### Fase 3: Recall Inteligente (Semanas 4-5)
- [ ] Implementar `MemoryRecallSelector` (scan + LLM selection)
- [ ] Integrar recall no pipeline de mensagens
- [ ] Injetar `relevant_memories` como attachments
- [ ] Deduplicação e staleness tracking

#### Fase 4: Extração Automática (Semanas 6-7)
- [ ] Implementar `ExtractMemoryUseCase` (forked agent pattern)
- [ ] Criar prompts de extração
- [ ] Background task execution
- [ ] Mutual exclusion (skip se agente principal já escreveu)
- [ ] Telemetry e logging

#### Fase 5: Consolidação (Semanas 8-9)
- [ ] Implementar `ConsolidateMemoryUseCase` (autoDream)
- [ ] Sistema de locks
- [ ] Leitura de transcripts/sessões
- [ ] Reorganização automática de memórias

#### Fase 6: Agent Memory + Team Memory (Semanas 10-12)
- [ ] Implementar `AgentMemoryLoader`
- [ ] Suporte a scopes (user, project, local)
- [ ] Team memory sync
- [ ] Segurança e path validation para team

---

## 4. Resumo Comparativo

| Aspecto | Claude Code | PersonAgent Atual | PersonAgent Proposto |
|---------|-------------|-------------------|----------------------|
| **Memória estática** | CLAUDE.md (5 níveis) | persona.md (4 níveis) | ✅ Preservar + estender |
| **Memória de sessão** | Não (usa contexto raw) | SessionMemoryService | ✅ Manter + integrar |
| **Auto memory** | MemDir completo | ❌ Não existe | 🆕 Implementar |
| **Recall inteligente** | findRelevantMemories | ❌ Não existe | 🆕 Implementar |
| **Extração automática** | extractMemories (forked agent) | ❌ Não existe | 🆕 Implementar |
| **Consolidação** | autoDream | ❌ Não existe | 🆕 Implementar |
| **Agent memory** | Por agent type (3 scopes) | ❌ Não existe | 🆕 Implementar |
| **Team memory** | Subdiretório compartilhado | ❌ Não existe | 🆕 Opcional |
| **Daily logs** | Modo KAIROS | ❌ Não existe | 🆕 Opcional |
| **Frontmatter** | name, description, type | ❌ Não existe | 🆕 Implementar |
| **Regras condicionais** | `paths` glob | ❌ Não existe | 🆕 Implementar |
| **Cache de contexto** | memoize + cache keys | InMemoryContextRepository | ✅ Preservar |

---

## 5. Conclusão

O sistema de memórias do Claude Code é um dos seus diferenciais mais poderosos. Ele transforma o agente de um "stateless request-response" para um "parceiro de longo prazo que aprende e evolui com o usuário".

A arquitetura proposta para o PersonAgent preserva **100% dos conceitos** do Claude Code, adaptando-os para o ecossistema Python/backend do PersonAgent. A implementação pode ser feita de forma incremental, começando pela memória manual + recall, evoluindo para extração automática e consolidação.

A infraestrutura necessária é principalmente:
1. **Sistema de arquivos** (já existe - apenas organizar)
2. **Background task runner** (novo - Celery ou asyncio)
3. **Extensão do LLM adapter** (já existe - apenas novos prompts)
4. **Cache layer** (já existe - estender)
5. **Banco de dados** (já existe - adicionar tabelas)

O custo de implementação é médio-alto, mas o valor entregue ao usuário é máximo: um agente que realmente **lembra** de conversas passadas, preferências, feedbacks e contexto de projeto.
