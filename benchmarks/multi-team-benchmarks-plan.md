# Plano de Benchmarks: Multi-Team Efficacy

> **Status:** `Rascunho` — documento de planejamento; modelos de avaliação ainda serão construídos.  
> **Owner:** @levybonito  
> **Criado em:** 2026-05-24  
> **Próxima revisão:** quando os modelos de benchmark forem implementados.

---

## 1. Contexto & Motivação

O PersonAgent já possui um **Team Mode** (ADR-0011) orquestrado via `TeamChatOrchestrator`, com fases definidas (*Execution Contract → Independent Round → Blackboard Publish → Debate Round → Coordinator Planning → Vote → Final Synthesis*).  
Hoje o sistema tem um benchmark operacional (`@backend/scripts/team_mode_benchmark.py`) que mede latência, *token throughput*, cobertura de termos esperados e *hard gates* de qualidade.

Contudo, **ainda não existe uma bateria sistemática que prove que "múltiplos agentes cooperando" entrega resultados superiores a "um único agente com reflection prompt"** para classes de problema específicas.  
Este documento define o que precisa ser medido, por quê e como, para que futuramente possamos construir os modelos de benchmark e rodar avaliações contínuas.

---

## 2. Objetivos do Benchmark

| ID | Objetivo | Pergunta que responde |
|----|----------|-----------------------|
| OB-01 | **Validar ganho de qualidade** | A resposta multi-team é objetivamente melhor que a single-agent para o mesmo prompt? |
| OB-02 | **Quantificar overhead** | Qual o custo adicional em latência, tokens e custo financeiro por cenário? |
| OB-03 | **Medir cooperação real** | Os agentes de fato constroem uns sobre os outros, ou apenas repetem o mesmo raciocínio? |
| OB-04 | **Avaliar robustez** | Em cenários adversariais (conflito, ambiguidade, ferramentas falhando), o multi-team se recupera melhor? |
| OB-05 | **Direcionar evolução** | Quais configurações de time (nº de agentes, papéis, fases ativas) são ótimas para cada classe de problema? |

---

## 3. Métricas Propostas

As métricas estão agrupadas em quatro dimensões.  
*(Valores-alvo serão calibrados após baseline inicial; esta seção define apenas o que medir.)*

### 3.1 Qualidade da Resposta

| Métrica | Definição | Instrumentação futura |
|---------|-----------|----------------------|
| `quality_score` | Nota LLM-as-a-judge (0-100) comparando a resposta final com rubrica do cenário. | Prompt de avaliação estruturado + parser de JSON. |
| `expected_term_hits` | % de termos obrigatórios presentes na resposta final. | Busca de substring normalizada (já usada no benchmark V3). |
| `claim_graph_depth` | Profundidade média do grafo de claims publicado no blackboard. | Contagem de nós `evidence → claim → proposal` por agente. |
| `factual_consistency` | Taxa de claims contraditórias detectadas entre Independent e Debate rounds. | LLM judge ou embedding similarity entre claims com sinais opostos. |

### 3.2 Eficiência & Custo

| Métrica | Definição | Notas |
|---------|-----------|-------|
| `wall_ms` | Tempo total de wall-clock até `team_run_completed`. | Já medido no benchmark V3. |
| `token_overhead_ratio` | `(tokens_multi_team / tokens_single_agent) - 1`. | Permite decidir quando o overhead vale o ganho. |
| `vote_overhead_ratio` | Tokens gastos na fase de voto / tokens totais do run. | Threshold atual: 0.25. |
| `cost_usd` | Estimativa de custo por run baseada em tokens de input/output e modelo. | Requer integração com pricing table da NVIDIA / OpenAI / etc. |

### 3.3 Cooperação & Divergência

| Métrica | Definição | Por que importa |
|---------|-----------|-----------------|
| `independent_overlap` | Similaridade média entre as respostas do Independent Round. | Se for 1.0, os agentes não trouxeram perspectivas distintas. |
| `overlap_reduction` | `independent_overlap - debate_overlap`. | Mede se o Debate Round realmente refinou e diferenciou as visões. |
| `unique_focus_ratio` | % de áreas de foco atribuídas pelo Coordinator que foram de fato cobertas por apenas um agente. | Indica se o Coordinator está conseguindo reduzir duplicação. |
| `delta_publication_rate` | % de publicações no Debate Round que são `delta` (refinamento) vs. `claim` nova. | Alto = os agentes estão reagindo uns aos outros. |

### 3.4 Robustez & Segurança

| Métrica | Definição | Cenários-alvo |
|---------|-----------|---------------|
| `consensus_recovery` | Taxa de runs que falharam votação mas produziram resposta útil após redirect do Coordinator. | Cenários com `blocker` legítimo. |
| `tool_audit_coverage` | % de propostas de tool mutante que foram auditadas por outro agente antes de execução. | Cenários `requires_tools=True`. |
| `memory_contamination_score` | Similaridade entre resposta final e memória de trabalho de agentes individuais (deve ser baixa se a síntese for original). | Evita que o Coordinator apenas "copie e cole" uma memória. |

---

## 4. Categorias de Cenários (Taxonomia)

Cada benchmark scenario deve ser classificado em uma ou mais categorias. Isso permitirá responder: *"Para que tipo de problema o Multi-Team vale a pena?"*

| Categoria | Descrição | Exemplo de prompt |
|-----------|-----------|-------------------|
| **Análise Multi-Perspectiva** | Requer visões distintas (técnica, de risco, de negócio). | "Analise se devemos migrar de PostgreSQL para ClickHouse." |
| **Diagnóstico de Incidente** | Causa-raiz incerta; múltiplas hipóteses competem. | "O serviço está com latência P99 > 2s após o deploy de ontem." |
| **Design Arquitetural** | Trade-offs explícitos; decisão estrutural. | "Projete o sistema de notificações em tempo real para 1M usuários." |
| **Revisão de Código / Segurança** | Detecção de vulnerabilidades e code-smell. | "Revise este PR de autenticação JWT e identifique falhas." |
| **Síntese de Conhecimento Disperso** | Múltiplas fontes de informação devem ser combinadas. | "Sintetize os ADRs 0011, 0022 e 0023 em uma proposta de roadmap." |
| **Resolução de Conflito** | Agentes devem divergir e convergir. | "Um agente defende REST, outro defende gRPC; cheguem a uma recomendação." |
| **Execução com Ferramentas** | Requer uso de read-tools e guardrails para mutating-tools. | "Leia o diretório `src/`, identifique dead code e proponha remoção." |

---

## 5. Baseline Comparativa

Para que o benchmark seja científico, cada cenário multi-team deve ter um **par single-agent** correspondente:

| Variante | Descrição |
|----------|-----------|
| `single-shot` | Um único prompt para o modelo, sem reflection. |
| `single-agent-reflection` | Mesmo modelo, com prompt de auto-crítica e refine (2 turns). |
| `multi-team-v3` | Orquestração atual (Analyst, Critic, Builder, Reviewer + Coordinator). |
| `multi-team-variant-N` | Variações futuras (ex.: 3 agentes, fases reduzidas, Coordinator ausente). |

> **Regra de ouro:** a única variável que muda entre as variantes é a *estratégia de orquestração*; o modelo, temperatura e system prompt base devem ser idênticos.

---

## 6. Estrutura de Dados Sugerida (para futura implementação)

```python
@dataclass(frozen=True)
class MultiTeamBenchmarkScenario:
    id: str
    category: str           # uma das categorias da seção 4
    difficulty: int         # 1-5
    messages: tuple[str, ...]
    rubric: str             # critérios de avaliação para o LLM judge
    expected_terms: tuple[str, ...]
    required_perspectives: tuple[str, ...] | None  # ex.: ("analyst", "critic")
    requires_tools: bool
    requires_consensus: bool
    baseline_single_agent: str  # id do cenário single-agent correspondente

@dataclass(frozen=True)
class MultiTeamBenchmarkResult:
    scenario_id: str
    variant: str            # ex.: "multi-team-v3", "single-agent-reflection"
    model: str
    repetition: int
    metrics: dict[str, float | int | list[str]]  # todas as métricas da seção 3
    verdict: str            # "pass", "fail", "partial"
```

---

## 7. Infraestrutura de Execução (visão futura)

| Componente | Estado atual | O que falta |
|------------|--------------|-------------|
| Orquestrador | `TeamChatOrchestrator` pronto. | Modo "headless" para CI (sem WebSocket, apenas resultado JSON). |
| Scenarios | 15+ cenários em `team_mode_benchmark.py`. | Refatorar para a nova taxonomia e adicionar baselines single-agent. |
| Coletor de métricas | `RunAnalysis` dataclass. | Adicionar métricas de cooperação (overlap, delta rate, etc.). |
| Judge / Avaliador | `expected_term_hits` + thresholds fixos. | Implementar LLM-as-a-judge com rubrica por cenário. |
| Dashboard | Não existe. | Script que gera HTML/Markdown comparativo por categoria. |
| CI Gate | `test_team_mode_benchmark.py` valida estrutura. | Gate que falha se `quality_gain_pct < threshold` por categoria crítica. |

---

## 8. Checklist de Implementação (futuro)

- [ ] **Fase A — Baseline:** criar variantes `single-shot` e `single-agent-reflection` para todos os cenários existentes.
- [ ] **Fase B — Métricas de cooperação:** implementar `independent_overlap`, `overlap_reduction`, `delta_publication_rate` no blackboard.
- [ ] **Fase C — LLM Judge:** construir prompt de avaliação estruturada com rubrica por categoria.
- [ ] **Fase D — Categorização:** reclassificar cenários existentes na taxonomia da seção 4.
- [ ] **Fase E — Expansão:** adicionar 10+ cenários novos nas categorias ainda pouco cobertas.
- [ ] **Fase F — CI Gate:** adicionar job de CI que roda benchmark completo em modelo pequeno (ex.: `deepseek-v4-flash`) e falha em regressões.
- [ ] **Fase G — Dashboard:** gerar relatório Markdown/HTML comparativo a cada execução.

---

## 9. Riscos & Hipóteses

| Risco | Mitigação |
|-------|-----------|
| LLM-as-a-judge pode ser enviesado a favor de respostas mais longas (multi-team naturalmente produz mais tokens). | Normalizar `quality_score` pelo comprimento; ou usar judge com contexto das duas variantes lado a lado. |
| Overhead de token pode inviabilizar uso prático mesmo com ganho de qualidade. | Documentar "break-even point" por categoria (ex.: "só vale para cenários de difficulty ≥ 4"). |
| Métricas de cooperação podem ser *gameadas* (agentes publicando deltas vazios). | Validar delta com LLM judge ou exigir que delta cite claim anterior. |
| Custo de rodar benchmark completo pode ser alto. | Usar modelo barato no CI (flash/quantizado) e modelo forte apenas em releases. |

---

## 10. Referências

- ADR-0011: *Phase-Based Multi-Agent Team Mode with Shared Blackboard*
- `@backend/scripts/team_mode_benchmark.py` — benchmark operacional atual (V3)
- `@backend/tests/test_team_mode_benchmark.py` — testes de estrutura do benchmark
- `@backend/src/personagent/application/team_chat/` — implementação do Team Mode

---

*Este documento é um ponto de partida. Conforme os modelos de benchmark forem sendo implementados, ele deve ser atualizado com valores reais, thresholds calibrados e lições aprendidas.*
