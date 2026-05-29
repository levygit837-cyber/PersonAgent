# Memory Agent — Estratégia de Uso Inteligente de Memória

> Documento complementar ao ADR 0025. Descreve o approach prático para fazer Agentes usarem memórias corretamente, sem poluir o contexto nem desperdiçar tokens.

---

## O Problema

Salvamos memórias de alto valor (decisões, padrões, preferências), mas elas frequentemente não chegam ao Main Agent no momento certo. Se injetarmos tudo no system prompt, poluímos o contexto. Se deixarmos o Main Agent buscar sozinho, ele nem sempre sabe que precisa.

A memória é um dos nossos diferenciais — precisamos que ela seja **inteligente, não automática**.

---

## A Solução: Memory Agent

Um agente **menor e especializado** que opera em background, lê memórias de forma seletiva e injeta no Main Agent apenas quando há coerência de contexto.

### Princípios Fundamentais

1. **Leitura mínima**: o Memory Agent lê apenas tags, descrições curtas e fatos — nunca o corpo completo de memórias grandes.
2. **Respostas curtas**: deve ser "instantâneo", com o mínimo de tokens possível.
3. **Injeção sob demanda**: só coloca memórias na fila quando detecta que são úteis para o estado atual do Main Agent.
4. **Sem repetição**: nunca faz múltiplas requisições para o mesmo contexto; usa cache agressivo.

---

## Como Funciona

### Fase 1: Pré-turno (Início da Requisição)

Antes do Main Agent processar a requisição do usuário:

1. Memory Agent recebe o contexto filtrado da sessão (arquivos, intenção, estado).
2. Consulta o cache — se já avaliou este contexto, reutiliza.
3. Se não estiver no cache, busca memórias relevantes pelo projeto.
4. Avalia coerência em 1-2 passos (non-thinking).
5. Se útil, coloca mensagem na queue do Main Agent.

### Fase 2: Durante a Execução (Background)

Enquanto o Main Agent trabalha:

- Detectamos mudanças de estado crítica (ex: começou a editar um arquivo arquitetural).
- Memory Agent verifica o cache para este novo estado.
- Se não tiver no cache, reavalia memórias não-cacheadas.
- Se encontrar coerência, envia para a queue.

A queue é consumida pelo Main Agent em pontos naturais de pausa:

- Após finalizar um thinking block.
- Após completar uma tool call.
- Antes de gerar a resposta final.

---

## Gatilhos de Execução

Não execute o Memory Agent a cada interação. Use gatilhos seletivos:

| Gatilho | Condição |
| --------- | --------------------------------------------------------------- |
| **Pré-turno** | Toda requisição do usuário (obrigatório, barato se cache hit) |
| **Mudança de estado crítica** | Main Agent transita para estado arquitetural (ex: edita `docker-compose.yml`, `adr/`, `domain/`) |
| **Shift de contexto** | Arquivos sendo tocados são de projeto diferente da interação anterior |
| **Exceção** | Nunca executar mais de uma vez a cada 5 segundos para o mesmo contexto |

---

## Estratégia de Cache

### Chave de Cache

```python
cache_key = hash(projeto + estado_agente + arquivos_tocados_hash)
```

- **Projeto**: repositório/conversation context.
- **Estado do Agente**: `thinking`, `tool_call`, `architectural_change`.
- **Arquivos tocados**: hash dos paths normalizados.

### Comportamento

- Cache em memória, scoped por sessão de conversa.
- TTL curto: **30 segundos** (ou invalidação explícita em mudança de estado).
- Estrutura do cache:

```python
{
  "cache_key": "abc123",
  "last_evaluated_at": "2025-05-28T15:00:00Z",
  "relevant_memories": ["mem_1", "mem_2"],  # IDs das memórias consideradas úteis
  "irrelevant_memories": ["mem_3"],          # IDs avaliadas como não úteis (para não reavaliar)
  "queued": True  # se já foi colocado na queue do Main Agent
}
```

### Fluxo de Decisão

```text
Main Agent muda de estado
        │
        ▼
Verificar cache para nova chave
        │
    ┌───┴───┐
    ▼       ▼
  HIT     MISS
    │       │
    ▼       ▼
Coerência?  Ler memórias não-cacheadas
    │           │
    ▼           ▼
SIM → Colocar na queue   Avaliar relevância
    │                       │
    ▼                   ┌───┴───┐
Main Agent consome      ÚTIL    INÚTIL
                            │       │
                            ▼       ▼
                    Colocar na queue   Guardar como irrelevante
                            │           (não reavaliar por 5 min)
                            ▼
                    Main Agent consome
```

---

## Eficiência de Tokens

### Non-thinking Obrigatório (Padrão)

Para o Memory Agent, **non-thinking deve ser o default**:

- System prompt instrui a ser sistemático e objetivo.
- Respostas devem ter formato estrito (JSON curto ou lista de IDs).
- Sem reflexão, sem explicação — apenas matching.

Exemplo de system prompt para Memory Agent:

```text
Você é um Memory Agent especializado em identificar relevância.
Contexto do Main Agent: {filtered_context}
Memórias disponíveis (tags + resumo): {memories_summary}

Tarefa: identifique APENAS as memórias diretamente relevantes ao contexto atual.
Regras:
- Responda em JSON com array de IDs.
- Máximo 3 memórias.
- Sem explicações, sem pensamentos, sem markdown extra.
- Se nenhuma for relevante, retorne array vazio.
```

### Quando Usar Thinking

Apenas em casos de ambiguidade alta:

- Contexto envolve múltiplos projetos.
- Memória parece parcialmente relevante (edge case).
- Primeira interação de uma sessão longa.

Instruções de thinking enxuto:

```text
Pense em no máximo 2 passos:
1. Qual é a intenção principal do Main Agent agora?
2. Qual memória ajuda diretamente esta intenção?
Não reflita sobre sua própria resposta. Não use mais de 30 tokens de pensamento.
```

---

## Como o Memory Agent Entende o Contexto

O Main Agent gera muito "ruído" (tool outputs, thinking blocks, logs). O Memory Agent precisa de um **contexto filtrado**.

### O que Enviar para o Memory Agent

```python
memory_agent_context = {
  "user_intent": "adicionar autenticação JWT",
  "current_state": "tool_call",
  "files_being_touched": ["backend/src/auth/middleware.py"],
  "tools_recently_used": ["read_file", "edit_file"],
  "session_turn": 12,
  "project": "PersonAgent"
}
```

### O que REMOVER antes de enviar

- Tool outputs completos (logs, JSONs, payloads grandes).
- Thinking blocks do Main Agent.
- Conteúdo de arquivos lidos (manter apenas o path).
- Mensagens de sistema anteriores.
- Histórico completo — manter apenas as últimas 3-5 interações resumidas.

### Como Extrair Sinais de Contexto

1. **Arquivos**: paths + extensão indicam domínio (`.py` → backend, `.tsx` → frontend).
2. **Estado**: `thinking` → planejamento; `tool_call` → execução; após tool call → avaliação.
3. **Padrões de tool**: sequência de `read_file` seguido de `edit_file` indica modificação.
4. **Intenção do usuário**: primeira mensagem do turno + última resposta do Main Agent.

---

## Formato da Injeção na Queue

Quando o Memory Agent decide injetar, a mensagem deve ser precisa:

```json
{
  "type": "memory_recall",
  "injected_at": "2025-05-28T15:00:00Z",
  "context_trigger": "editing auth middleware",
  "priority": "high",
  "memories": [
    {
      "id": "mem_abc123",
      "tag": "auth-pattern",
      "layer": "operational",
      "summary": "Use JWT com refresh token rotation",
      "action": "apply_before_next_tool"
    }
  ]
}
```

### Prioridades

- **high**: memória arquitetural ou crítica — injetar imediatamente.
- **medium**: padrão de projeto — injetar antes da próxima tool call.
- **low**: preferência do usuário — injetar na próxima resposta.

### Campo `action`

- `apply_immediately`: Main Agent deve considerar antes de próxima ação.
- `apply_before_next_tool`: considerar antes de chamar próxima ferramenta.
- `apply_in_response`: incorporar na resposta final ao usuário.

---

## Pontos de Atenção

### 1. Não Disparar em Excesso

- Uma sessão de 50 turnos pode ter 50 requisições de usuário, mas o Memory Agent deve executar no máximo 10 vezes (cache + controle de estado).
- Implementar debounce: mínimo de 5 segundos entre execuções para o mesmo contexto.

### 2. Cache Sempre Atualizado

- Invalidar cache quando o estado muda significativamente.
- TTL de 30s é curto o suficiente para evitar desatualização, longo o suficiente para evitar re-leitura.

### 3. Feedback Loop

- Se o Main Agent ignorar uma memória injetada 3 vezes, marcar como "low relevance" para este contexto.
- Se o Main Agent usar ativamente, marcar como "high relevance" e priorizar em futuras sessões.

### 4. Fallback Seguro

- Se o Memory Agent falhar (timeout, erro), o Main Agent continua normalmente.
- Nunca bloquear o Main Agent esperando o Memory Agent.
- Logar falhas para análise posterior.

---

## Testes e Validação

### Fase 1: Testes Unitários (Validar Lógica)

```python
def test_cache_hit_avoids_re_read():
    # Contexto idêntico → deve retornar do cache sem buscar memórias
    pass

def test_architectural_state_triggers_re_evaluation():
    # Mudança para estado arquitetural → deve reavaliar mesmo com cache
    pass

def test_irrelevant_memories_are_filtered():
    # Memórias sobre frontend não devem ser injetadas quando editando backend
    pass

def test_queue_injection_format():
    # Formato da mensagem na queue deve ser válido e consumível
    pass
```

### Fase 2: Testes de Integração (Validar Pipeline)

- Simular sessão completa (20+ turnos) com mudanças de estado.
- Verificar que memórias arquiteturais são injetadas no momento certo.
- Medir tempo de execução do Memory Agent (meta: <200ms por execução).

### Fase 3: Benchmark de Tokens (Validar Eficiência)

| Cenário                     | Com Memory Agent | Sem Memory Agent |
| --------------------------- | ---------------- | ---------------- |
| Sessão curta (5 turnos)     | X tokens         | Y tokens         |
| Sessão longa (50 turnos)    | X tokens         | Y tokens         |

Meta: overhead do Memory Agent <5% do total de tokens da sessão.

### Fase 4: Teste A/B de Qualidade (Validar Utilidade)

- Grupo A: Main Agent com Memory Agent ativo.
- Grupo B: Main Agent sem Memory Agent (apenas RAG padrão).
- Métricas:
  - Taxa de reutilização de padrões documentados em memória.
  - Consistência arquitetural entre sessões.
  - Tempo até correção de erros relacionados a regras conhecidas.

---

## Roadmap de Experimentação

Esta é uma **tese em validação**. Iremos iterar:

| Fase | O que testar | Duração |
| ------ | ------------------------------------------------------ | --------- |
| **Alpha** | Non-thinking obrigatório, cache simples, gatilhos básicos | 1 semana |
| **Beta** | Adicionar thinking condicional, refinamento de contexto | 1 semana |
| **Gamma** | Feedback loop (relevance scoring), tuning de prioridades | 1 semana |
| **Release** | Configurável pelo usuário (on/off, agressividade) | Após validação |

### Variáveis de Teste

1. **Non-thinking vs thinking**: qual tem melhor precisão com menor custo?
2. **Tamanho do contexto filtrado**: 3 vs 5 vs 10 interações recentes.
3. **TTL do cache**: 10s vs 30s vs 60s.
4. **Número máximo de memórias injetadas por turno**: 1 vs 3 vs 5.
5. **Gatilhos**: apenas pré-turno vs pré-turno + mudança de estado.

---

## Resumo

- O Memory Agent é um **gatekeeper** de memória — ele decide *se* e *quando* uma memória vale a pena ser injetada.
- Opera em background, com **non-thinking default**, **cache agressivo** e **gatilhos seletivos**.
- Recebe apenas **contexto filtrado** do Main Agent (arquivos, estado, intenção — sem ruído).
- Injetar via **queue** em pontos naturais de pausa do Main Agent.
- **Tudo é tese** — vamos documentar, testar e iterar com dados reais.
