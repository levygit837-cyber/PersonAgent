# ADR 0025: Memory Agent — Injeção Inteligente de Memória em Background

Date: 2025-05-28
Status: Proposed

## Context

Temos três camadas de memória (ADR 0012), mas o problema não é apenas *onde* armazenar — é **quando e como** trazer memórias para o contexto do Main Agent sem poluir o prompt ou desperdiçar tokens.

Problemas identificados:

- Memórias de alto valor (decisões arquiteturais, regras de projeto, preferências do usuário) ficam perdidas no vetorstore e nunca são recuperadas no momento certo.
- Injetar *todas* as memórias relevantes no system prompt sobrecarrega o contexto e aumenta o custo.
- O Main Agent não tem como saber, no meio de uma execução, que existe uma memória crucial para a tarefa atual.
- Requisições repetidas de busca de memória a cada turno são caras e lentas.

## Decision

Criar um **Memory Agent** — agente leve especializado que opera em background, lê memórias de forma seletiva e injeta no Main Agent apenas quando há coerência de contexto.

### Arquitetura

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Main Agent    │◄────│   Message Queue  │◄────│  Memory Agent   │
│  (thinking/     │     │  (memories to    │     │  (background,   │
│   tool calls)   │     │   inject)        │     │   lightweight)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              ▲                            │
                              └────────────────────────────┘
                                         (cache hit / miss)
```

### 1. Memory Agent — Responsabilidades

- Executa **antes** do Main Agent iniciar o processamento de cada requisição.
- Também pode executar **durante** a execução do Main Agent, em background, quando detectamos mudança de estado crítica.
- Lê apenas **tags, descrições curtas e fatos** sobre memórias — nunca o corpo completo.
- Respostas devem ser **instantâneas, curtas e de muito pouco conteúdo**.
- Avalia coerência entre o estado atual do Main Agent e as memórias disponíveis.
- Se houver coerência, coloca uma mensagem na fila para o Main Agent consumir.

### 2. Gatilhos de Execução

O Memory Agent NÃO roda a cada interação. Gatilhos controlados:

| Gatilho | Quando | Por que |
|---------|--------|---------|
| Pré-turno | Início de cada requisição do usuário | Contexto inicial da sessão |
| Mudança de estado crítica | Main Agent muda de "thinking" → "tool_call", ou altera arquivos arquiteturais | Momento onde memória arquitetural é mais valiosa |
| Mudança de contexto de projeto | Arquivos diferentes daqueles sendo editados na sessão anterior | Detecta contexto shift |

**Nunca** disparar múltiplas vezes para o mesmo estado/contexto dentro de uma janela curta.

### 3. Estratégia de Cache

- Guardar conteúdo já lido em **cache do Background Agent** (em memória, scoped por sessão).
- Chave de cache: `projeto + estado_agente + arquivos_tocados_hash`.
- Se o Main Agent troca de estado para algo crítico/arquitetural:
  1. Verificar cache — se tiver coerência, botar mensagem na queue imediatamente.
  2. Se não tiver no cache, reler as memórias não-cacheadas.
  3. Avaliar utilidade — se útil, enviar para a queue do Main Agent e atualizar o cache.

### 4. Eficiência de Tokens

- **Non-thinking obrigatório** para o Memory Agent em operação normal.
- System prompt instrui a ser **sistemático, objetivo, respostas curtas**.
- Se "thinking" for necessário (avaliação de relevância complexa), instruir o modelo a:
  - Pensar em no máximo 1-2 passos.
  - Pensamentos devem ser objetivos: "arquivo X está sendo editado → memória Y sobre padrão Z é relevante".
  - Sem reflexão metacognitiva — apenas matching direto.

### 5. Contexto para o Memory Agent

O Memory Agent precisa entender o que o Main Agent está fazendo. Para isso:

- Receber o **histórico de contexto mais recente** da conversa.
- **Filtrar conteúdo excessivo**:
  - Remover tool outputs grandes (logs, JSONs, payloads).
  - Remover blocos de thinking do Main Agent.
  - Manter apenas: nome das ferramentas chamadas, arquivos tocados, intenção do usuário, estado atual.
- Extrair sinais de contexto:
  - Arquivos sendo editados (paths + linguagem).
  - Estado atual do Main Agent (`thinking`, `tool_call`, `responding`).
  - Tipo de tarefa (bugfix, feature, refactor, arquitetura).
- Usar esses sinais para filtrar quais memórias são relevantes.

### 6. Formato da Injeção

Quando o Memory Agent decide que uma memória é relevante, a mensagem na queue deve ser:

```json
{
  "type": "memory_recall",
  "priority": "high | medium | low",
  "context_trigger": "editing auth_middleware.py",
  "memories": [
    {
      "id": "mem_abc123",
      "tag": "auth-pattern",
      "summary": "Use JWT com refresh token rotation; nunca armazene secrets em env var sem prefixo APP_",
      "source": "operational_memory"
    }
  ]
}
```

O Main Agent consome essa mensagem e injeta as memórias no próximo contexto de forma nativa.

## Consequences

- **Easier**: memórias de alto valor realmente chegam ao Main Agent no momento certo; não dependemos do RAG "adivinhar" sozinho.
- **Easier**: contexto do Main Agent permanece enxuto — apenas memórias validadas como relevantes são injetadas.
- **Harder**: precisamos de um mecanismo de queue confiável entre agentes.
- **Harder**: definir "estado crítico" e "contexto shift" requer heurísticas que precisam de tuning.
- **Risk**: se o Memory Agent falhar silenciosamente, o Main Agent opera sem memória (degradation graceful, mas não ideal).
- **Risk**: cache desatizado pode injetar memórias irrelevantes — TTL curto (ex: 30s) ou invalidação por mudança de estado.
- **Out of scope**: memória cross-project (federation); memória de nível global do usuário.

## Alternatives Considered

- **Injetar todas as memórias RAG no system prompt a cada turno**: rejeitado — poluição de contexto, custo alto, perda de foco.
- **Main Agent mesmo buscar memória quando precisar (tool call)**: rejeitado — adiciona latência no caminho crítico; o Main Agent nem sempre sabe que precisa buscar.
- **Memória como camada síncrona no PromptBuilder**: rejeitado — torna cada requisição lenta; não permite reação a mudanças de estado durante a execução.

## Validation

- Testes unitários do Memory Agent com casos de borda (cache hit, cache miss, estado irrelevante).
- Testes de integração: simular sessão longa (>50 turnos) e verificar que o Memory Agent não dispara mais que o limite configurado.
- Benchmark de tokens: comparar consumo de tokens com/without Memory Agent — meta: <5% overhead por turno.
- Métrica de eficácia: taxa de memórias de alto valor que foram efetivamente usadas pelo Main Agent (avaliação manual em amostra).

## Testes Planejados

| Cenário | Objetivo | Métrica |
|---------|----------|---------|
| Sessão curta (5 turnos) | Validar que não há disparo excessivo | Max 3 execuções do Memory Agent |
| Sessão longa (50+ turnos) | Validar cache e controle de estado | Max 10 execuções do Memory Agent |
| Mudança de arquivo arquitetural | Validar injeção de memória arquitetural | Memória injetada em <500ms |
| Cache hit | Validar queue imediata | Tempo de resposta <50ms |
| Cache miss + relevância negativa | Validar filtro eficiente | Nenhuma memória injetada |
| Non-thinking vs thinking | Comparar tokens e qualidade | Non-thinking deve ter 80%+ de precisão com 50% de tokens |
